import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi.testclient import TestClient

import app  # noqa: F401  (configures utilbots_core)
from app.plans import FEATURES, PLANS
from utilbots_core import db


@pytest.fixture()
def client():
    db.use_engine("sqlite://")
    from app.web.app import app as web
    with TestClient(web) as c:
        yield c


def test_every_feature_is_offered_by_some_plan():
    offered = set().union(*(p.features for p in PLANS.plans.values()))
    assert offered == set(FEATURES)


def test_site_serves(client):
    assert client.get("/healthz").json()["bot"] == "__SLUG__"
    assert client.get("/").status_code == 200
    assert client.get("/pricing").status_code == 200


def test_bot_builds():
    import asyncio
    from app.bot.main import __CLASS__
    asyncio.set_event_loop(asyncio.new_event_loop())
    names = {c.name for c in __CLASS__().pending_application_commands}
    assert "plan" in names
