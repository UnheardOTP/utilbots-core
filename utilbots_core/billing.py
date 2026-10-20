"""Stripe billing, shared by every bot on one Stripe account.

Everything Stripe-side is scoped to the bot so bots never see each other's money:
- Prices are found by lookup key `<slug>_<plan>_monthly` and synced from the PlanSet on startup (a price change
  creates a new Price and moves the lookup key; existing subscribers keep their old price).
- Each bot gets its own webhook endpoint (`<PUBLIC_URL>/stripe/webhook`). Stripe sends every account event to every
  endpoint, so `apply_subscription` ignores subscriptions whose metadata `bot` isn't this bot.
- Each bot gets its own customer-portal configuration, so "change plan" only offers this bot's prices.
The webhook signing secret and portal configuration id are stored in the `kv` table, so the only Stripe value a
server needs is STRIPE_SECRET_KEY in the shared .env.
"""
import logging
from datetime import datetime, timedelta, timezone

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import registry
from .config import settings
from .db import SessionLocal
from .models import KV, BillingCustomer, Guild, Subscription

log = logging.getLogger(__name__)
GRACE = timedelta(days=2)  # keep access briefly past the period end so a late renewal webhook doesn't cut service
LIVE_STATUSES = {"active", "trialing", "past_due"}
EVENTS = ["customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"]
KV_WEBHOOK = "stripe_webhook"
KV_PORTAL = "stripe_portal"
_price_cache: dict[str, str] = {}


def lookup_key(plan: str) -> str:
    return f"{registry.spec().slug}_{plan}_monthly"


def _kv(db: Session, key: str) -> dict:
    row = db.get(KV, key)
    return dict(row.value) if row else {}


def _kv_set(db: Session, key: str, value: dict) -> None:
    row = db.get(KV, key)
    if row is None:
        db.add(KV(key=key, value=value))
    else:
        row.value = value


def webhook_secret(db: Session) -> str:
    return settings.stripe_webhook_secret or _kv(db, KV_WEBHOOK).get("secret", "")


def configured(db: Session) -> bool:
    return bool(settings.stripe_secret_key and webhook_secret(db))


# ---- provisioning ---------------------------------------------------------------------------------------------
def ensure_stripe() -> None:
    """Idempotent: sync products/prices, the portal configuration and the webhook endpoint. Called in a background
    thread on web startup; failures are logged, never fatal (the site works without payments)."""
    if not settings.stripe_secret_key or not settings.stripe_auto_setup:
        return
    try:
        product_prices = sync_prices()
        with SessionLocal() as db:
            ensure_portal(db, product_prices)
            if settings.public_url.startswith("https://"):
                ensure_webhook(db)
            else:
                log.info("stripe: PUBLIC_URL is not https, skipping webhook endpoint setup")
            db.commit()
        log.info("stripe: catalog, portal and webhook are in place")
    except Exception:
        log.exception("stripe: automatic setup failed (payments stay disabled until it succeeds)")


def sync_prices() -> dict[str, str]:
    """Make sure every paid plan has an active monthly Price at its lookup key. Returns {product_id: price_id}."""
    spec, plans = registry.current()
    key = settings.stripe_secret_key
    out: dict[str, str] = {}
    for plan in plans.paid:
        lk = lookup_key(plan.key)
        found = stripe.Price.list(api_key=key, lookup_keys=[lk], active=True, limit=1).data
        price = found[0] if found else None
        if price and price.unit_amount == plan.price_cents and price.currency == "usd":
            out[price.product] = price.id
            _price_cache[plan.key] = price.id
            continue
        if price:
            product_id = price.product
            stripe.Product.modify(product_id, api_key=key, name=f"{spec.name} {plan.name}")
        else:
            product_id = stripe.Product.create(
                api_key=key, name=f"{spec.name} {plan.name}",
                metadata={"bot": spec.slug, "plan": plan.key}).id
        new = stripe.Price.create(
            api_key=key, product=product_id, currency="usd", unit_amount=plan.price_cents,
            recurring={"interval": "month"}, lookup_key=lk, transfer_lookup_key=True,
            metadata={"bot": spec.slug, "plan": plan.key})
        if price:  # retire the old price for new checkouts; current subscribers keep it
            stripe.Price.modify(price.id, api_key=key, active=False)
        log.info("stripe: %s price for %s is now %s", "updated" if price else "created", plan.key, new.id)
        out[product_id] = new.id
        _price_cache[plan.key] = new.id
    return out


def ensure_portal(db: Session, product_prices: dict[str, str]) -> None:
    spec, _ = registry.current()
    key = settings.stripe_secret_key
    wanted = sorted([{"product": p, "prices": [pr]} for p, pr in product_prices.items()], key=lambda x: x["product"])
    stored = _kv(db, KV_PORTAL)
    if stored.get("id") and stored.get("products") == wanted:
        return
    features = {
        "customer_update": {"enabled": True, "allowed_updates": ["email"]},
        "invoice_history": {"enabled": True},
        "payment_method_update": {"enabled": True},
        "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
        "subscription_update": {"enabled": bool(wanted), "default_allowed_updates": ["price"] if wanted else [],
                                "products": wanted, "proration_behavior": "create_prorations"},
    }
    profile = {"headline": f"{spec.name} subscription",
               "privacy_policy_url": f"{settings.legal_base_url}/privacy",
               "terms_of_service_url": f"{settings.legal_base_url}/terms"}
    if stored.get("id"):
        conf = stripe.billing_portal.Configuration.modify(stored["id"], api_key=key, features=features,
                                                          business_profile=profile)
    else:
        conf = stripe.billing_portal.Configuration.create(api_key=key, features=features, business_profile=profile,
                                                          metadata={"bot": spec.slug})
    _kv_set(db, KV_PORTAL, {"id": conf.id, "products": wanted})


def ensure_webhook(db: Session) -> None:
    """One endpoint per bot. The signing secret is only returned at creation, so an endpoint we don't hold the
    secret for is deleted and recreated."""
    spec, _ = registry.current()
    key = settings.stripe_secret_key
    url = f"{settings.public_url}/stripe/webhook"
    stored = _kv(db, KV_WEBHOOK)
    endpoints = [e for e in stripe.WebhookEndpoint.list(api_key=key, limit=100).auto_paging_iter() if e.url == url]
    for ep in endpoints:
        if ep.id == stored.get("id") and stored.get("secret"):
            if sorted(ep.enabled_events) != sorted(EVENTS) or ep.status != "enabled":
                stripe.WebhookEndpoint.modify(ep.id, api_key=key, enabled_events=EVENTS, disabled=False)
            return
    for ep in endpoints:
        stripe.WebhookEndpoint.delete(ep.id, api_key=key)
    ep = stripe.WebhookEndpoint.create(api_key=key, url=url, enabled_events=EVENTS,
                                       description=f"{spec.name} subscriptions", metadata={"bot": spec.slug})
    _kv_set(db, KV_WEBHOOK, {"id": ep.id, "secret": ep.secret})
    log.info("stripe: created webhook endpoint %s for %s", ep.id, url)


# ---- checkout / portal ----------------------------------------------------------------------------------------
def price_id(plan: str) -> str:
    if plan in _price_cache:
        return _price_cache[plan]
    found = stripe.Price.list(api_key=settings.stripe_secret_key, lookup_keys=[lookup_key(plan)], active=True,
                              limit=1).data
    if not found:
        raise ValueError("That plan isn't available for purchase yet.")
    _price_cache[plan] = found[0].id
    return found[0].id


def create_checkout(guild_id: int, plan: str, customer_id: str | None) -> str:
    spec, plans = registry.current()
    p = plans.get(plan)
    if p is None or p.rank == 0:
        raise ValueError("That plan isn't available for purchase.")
    meta = {"bot": spec.slug, "guild_id": str(guild_id), "plan": plan}
    kwargs = {"customer": customer_id} if customer_id else {}
    session = stripe.checkout.Session.create(
        api_key=settings.stripe_secret_key, mode="subscription", line_items=[{"price": price_id(plan), "quantity": 1}],
        client_reference_id=str(guild_id), metadata=meta, subscription_data={"metadata": meta},
        allow_promotion_codes=True,
        success_url=f"{settings.public_url}/guild/{guild_id}/billing?msg=Payment+received.+Your+plan+activates+in+a+few+seconds.",
        cancel_url=f"{settings.public_url}/guild/{guild_id}/billing", **kwargs)
    return session.url


def create_portal(db: Session, guild_id: int, customer_id: str) -> str:
    conf = _kv(db, KV_PORTAL).get("id")
    kwargs = {"configuration": conf} if conf else {}
    session = stripe.billing_portal.Session.create(
        api_key=settings.stripe_secret_key, customer=customer_id,
        return_url=f"{settings.public_url}/guild/{guild_id}/billing", **kwargs)
    return session.url


def parse_event(db: Session, payload: bytes, signature: str):
    return stripe.Webhook.construct_event(payload, signature, webhook_secret(db))


# ---- webhook mirroring ----------------------------------------------------------------------------------------
def _period_end(sub: dict) -> int | None:
    if sub.get("current_period_end"):  # older API versions
        return sub["current_period_end"]
    items = (sub.get("items") or {}).get("data") or []  # newer API versions moved it onto items
    return max((i["current_period_end"] for i in items if i.get("current_period_end")), default=None)


def is_ours(sub: dict) -> bool:
    bot = (sub.get("metadata") or {}).get("bot")
    if bot is None:
        return settings.stripe_accept_unscoped
    return bot == registry.spec().slug


def apply_subscription(db: Session, sub: dict) -> bool:
    """Idempotently mirror a Stripe subscription into our table. Returns False if it isn't this bot's."""
    if not is_ours(sub):
        return False
    meta = sub.get("metadata") or {}
    plan = meta.get("plan")
    p = registry.plans().get(plan or "")
    if not str(meta.get("guild_id", "")).isdigit() or p is None or p.rank == 0:
        return False
    guild_id = int(meta["guild_id"])
    if db.get(Guild, guild_id) is None:
        log.warning("stripe subscription %s for unknown guild %s", sub.get("id"), guild_id)
        return False

    end = _period_end(sub)
    expires = datetime.fromtimestamp(end, tz=timezone.utc) + GRACE if end else None
    status = "active" if sub.get("status") in LIVE_STATUSES else "canceled"

    row = db.scalar(select(Subscription).where(Subscription.source == "stripe", Subscription.external_id == sub["id"]))
    if row is None:
        row = Subscription(guild_id=guild_id, source="stripe", external_id=sub["id"], plan=plan,
                           note="Stripe subscription")
        db.add(row)
    # Portal plan switches change the price, not our metadata: derive the plan from the price lookup key.
    items = (sub.get("items") or {}).get("data") or []
    for item in items:
        lk = ((item.get("price") or {}).get("lookup_key") or "")
        for candidate in registry.plans().paid:
            if lk == lookup_key(candidate.key):
                plan = candidate.key
    row.plan, row.status, row.expires_at = plan, status, expires

    customer = sub.get("customer")
    if isinstance(customer, str) and customer:
        existing = db.get(BillingCustomer, guild_id)
        if existing is None:
            db.add(BillingCustomer(guild_id=guild_id, customer_id=customer))
        else:
            existing.customer_id = customer
    return True
