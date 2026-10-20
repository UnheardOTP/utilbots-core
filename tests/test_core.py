import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

import utilbots_core
from utilbots_core import billing, db, entitlements, quotas
from utilbots_core.models import BillingCustomer, Guild, Subscription, WebSession, utcnow
from utilbots_core.plans import Plan, PlanSet

FEATURES = {"basic": "Basic thing", "fancy": "Fancy thing"}
PLANS = PlanSet(FEATURES, {
    "free": Plan("free", "Free", 0, 0, frozenset({"basic"}), {"things_per_day": 2}),
    "plus": Plan("plus", "Plus", 1, 300, frozenset({"basic", "fancy"}), {"things_per_day": None}),
})
utilbots_core.configure(utilbots_core.BotSpec(slug="testbot", name="TestBot", emoji="🧪", tagline="Tests things."),
                        PLANS)


@pytest.fixture(autouse=True)
def fresh_db():
    db.use_engine("sqlite://")
    db.init_db()
    yield


def session():
    return db.SessionLocal()


def test_planset_validation():
    with pytest.raises(ValueError):
        PlanSet(FEATURES, {"plus": PLANS.plans["plus"]})
    with pytest.raises(ValueError):
        PlanSet({"basic": "x"}, PLANS.plans)
    assert PLANS.min_plan_for("fancy").key == "plus"
    assert PLANS.plans["plus"].price_label == "$3 / month"


def test_entitlements_and_trial():
    with session() as s:
        g = entitlements.ensure_guild(s, 1, name="G", installed=True)
        s.flush()
        assert entitlements.effective_plan(s, 1).key == "free"
        assert entitlements.start_trial(s, g, 7)
        assert entitlements.effective_plan(s, 1).key == "plus"
        assert not entitlements.start_trial(s, g, 7)
        assert entitlements.revoke(s, 1) == 1
        assert entitlements.effective_plan(s, 1).key == "free"


def test_quotas():
    with session() as s:
        assert quotas.consume(s, 1, "things", 1, 2)
        assert quotas.consume(s, 1, "things", 1, 2)
        assert not quotas.consume(s, 1, "things", 1, 2)
        quotas.refund(s, 1, "things", 1)
        assert quotas.remaining(s, 1, "things", 2) == 1
        assert quotas.consume(s, 1, "things", 50, None)


def _sub(bot="testbot", plan="plus", status="active", lookup=None):
    sub = {"id": "sub_1", "status": status, "customer": "cus_1", "current_period_end": int(utcnow().timestamp()) + 86400,
           "metadata": {"guild_id": "1", "plan": plan}}
    if bot is not None:
        sub["metadata"]["bot"] = bot
    if lookup:
        sub["items"] = {"data": [{"price": {"lookup_key": lookup}}]}
    return sub


def test_stripe_scoping():
    with session() as s:
        entitlements.ensure_guild(s, 1, installed=True)
        s.flush()
        assert not billing.apply_subscription(s, _sub(bot="otherbot")), "another bot's subscription must be ignored"
        assert not billing.apply_subscription(s, _sub(bot=None)), "unscoped subscriptions are ignored by default"
        assert billing.apply_subscription(s, _sub())
        s.flush()
        assert entitlements.effective_plan(s, 1).key == "plus"
        assert s.get(BillingCustomer, 1).customer_id == "cus_1"
        billing.apply_subscription(s, _sub(status="canceled"))
        s.flush()
        assert entitlements.effective_plan(s, 1).key == "free"
        assert billing.lookup_key("plus") == "testbot_plus_monthly"


def _client(**kw):
    from utilbots_core.web import create_app
    return TestClient(create_app(**kw))


def _login(c: TestClient, user_id=42, guilds=(1,)):
    with session() as s:
        ws = WebSession(token="tok", csrf="c", user_id=user_id, username="u",
                        guilds=[{"id": str(g), "name": f"G{g}", "icon": None, "owner": True} for g in guilds],
                        expires_at=utcnow().replace(year=utcnow().year + 1))
        s.add(ws)
        s.commit()
    c.cookies.set("ub_session", "tok")


def test_web_public_pages():
    with _client() as c:
        assert c.get("/healthz").json() == {"ok": True, "bot": "testbot"}
        r = c.get("/pricing")
        assert r.status_code == 200 and "Fancy thing" in r.text and "$3 / month" in r.text
        assert "TestBot" in c.get("/").text
        assert c.get("/dashboard", follow_redirects=False).headers["location"].startswith("/login")


def test_web_guild_and_billing_pages():
    with _client() as c:
        with session() as s:
            entitlements.ensure_guild(s, 1, name="G1", installed=True)
            s.commit()
        _login(c)
        assert "G1" in c.get("/dashboard").text
        r = c.get("/guild/1/billing")
        assert r.status_code == 200 and "Start trial" in r.text
        r = c.post("/guild/1/billing/trial", data={"csrf": "c"}, follow_redirects=False)
        assert r.status_code == 303 and "trial+started" in r.headers["location"].replace("%20", "+")
        assert c.get("/guild/2").status_code == 403
        assert c.get("/admin").status_code == 403


def test_bot_routes_override_core():
    router = APIRouter()

    @router.get("/guild/{guild_id}")
    async def mine(guild_id: int):
        return {"bot_page": guild_id}

    with _client(routers=[router]) as c:
        assert c.get("/guild/5").json() == {"bot_page": 5}


def test_webhook_rejects_without_secret():
    with _client() as c:
        assert c.post("/stripe/webhook", content=b"{}").status_code == 503


class _Obj(dict):
    __getattr__ = dict.get


class FakeStripe:
    """Just enough of the stripe module for the provisioning code."""
    def __init__(self):
        self.prices, self.products, self.endpoints, self.portals, self.n = [], [], [], [], 0

    def _id(self, p):
        self.n += 1
        return f"{p}_{self.n}"

    def install(self, mp):
        fs = self

        class Price:
            @staticmethod
            def list(lookup_keys, active, **_):
                return _Obj(data=[p for p in fs.prices if p.lookup_key in lookup_keys and p.active])

            @staticmethod
            def create(product, unit_amount, lookup_key, transfer_lookup_key, **_):
                for p in fs.prices:
                    if p.lookup_key == lookup_key:
                        p["lookup_key"] = None
                p = _Obj(id=fs._id("price"), product=product, unit_amount=unit_amount, currency="usd",
                         lookup_key=lookup_key, active=True)
                fs.prices.append(p)
                return p

            @staticmethod
            def modify(pid, active, **_):
                next(p for p in fs.prices if p.id == pid)["active"] = active

        class Product:
            @staticmethod
            def create(name, **_):
                p = _Obj(id=fs._id("prod"), name=name)
                fs.products.append(p)
                return p

            @staticmethod
            def modify(pid, **_):
                pass

        class _Pager(list):
            def auto_paging_iter(self):
                return iter(self)

        class WebhookEndpoint:
            @staticmethod
            def list(**_):
                return _Pager(fs.endpoints)

            @staticmethod
            def create(url, enabled_events, **_):
                e = _Obj(id=fs._id("we"), url=url, enabled_events=enabled_events, status="enabled",
                         secret=f"whsec_{fs.n}")
                fs.endpoints.append(e)
                return e

            @staticmethod
            def delete(eid, **_):
                fs.endpoints[:] = [e for e in fs.endpoints if e.id != eid]

            @staticmethod
            def modify(eid, **_):
                pass

        class Configuration:
            @staticmethod
            def create(**kw):
                c = _Obj(id=fs._id("bpc"), **kw)
                fs.portals.append(c)
                return c

            @staticmethod
            def modify(cid, **kw):
                return _Obj(id=cid, **kw)

        mp.setattr(billing.stripe, "Price", Price)
        mp.setattr(billing.stripe, "Product", Product)
        mp.setattr(billing.stripe, "WebhookEndpoint", WebhookEndpoint)
        mp.setattr(billing.stripe.billing_portal, "Configuration", Configuration)


def test_stripe_provisioning_is_idempotent(monkeypatch):
    from dataclasses import replace
    fs = FakeStripe()
    fs.install(monkeypatch)
    monkeypatch.setattr(billing, "settings", replace(billing.settings, stripe_secret_key="sk_test",
                                                     public_url="https://testbot.utilbots.com"))
    billing._price_cache.clear()
    billing.ensure_stripe()
    billing.ensure_stripe()
    assert len(fs.products) == 1 and len([p for p in fs.prices if p.active]) == 1
    assert len(fs.endpoints) == 1 and len(fs.portals) == 1
    with session() as s:
        assert billing.webhook_secret(s) == fs.endpoints[0].secret
    # an endpoint for our URL whose secret we don't hold is replaced
    fs.endpoints[0]["id"] = "we_foreign"
    billing.ensure_stripe()
    assert len(fs.endpoints) == 1 and fs.endpoints[0].id != "we_foreign"
    # a price change creates a new price on the same product and retires the old one
    plus = PLANS.plans["plus"]
    monkeypatch.setitem(PLANS.plans, "plus", replace(plus, price_cents=500))
    billing.ensure_stripe()
    active = [p for p in fs.prices if p.active]
    assert len(fs.products) == 1 and len(active) == 1 and active[0].unit_amount == 500
    assert active[0].lookup_key == "testbot_plus_monthly"
