"""Settings every bot shares. Values come from the environment: the server's shared
`/mnt/user/appdata/utilbots-shared/.env` is loaded first, then the bot's own `.env` (which wins)."""
import os
from dataclasses import dataclass


def _ids(value: str) -> frozenset[int]:
    return frozenset(int(x) for x in value.replace(" ", "").split(",") if x.isdigit())


def _bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./local.db")
    discord_token: str = os.getenv("DISCORD_TOKEN", "")
    discord_client_id: str = os.getenv("DISCORD_CLIENT_ID", "")
    discord_client_secret: str = os.getenv("DISCORD_CLIENT_SECRET", "")
    public_url: str = os.getenv("PUBLIC_URL", "http://localhost:8080").rstrip("/")
    session_secret: str = os.getenv("SESSION_SECRET", "change-me")
    admin_ids: frozenset[int] = _ids(os.getenv("ADMIN_IDS", ""))
    trial_enabled: bool = _bool(os.getenv("TRIAL_ENABLED", "true"))
    trial_days: int = int(os.getenv("TRIAL_DAYS", "14"))
    # Stripe: one account for every bot (key lives in the shared .env). Products, prices, the webhook endpoint and
    # the customer-portal configuration are created per bot automatically on web startup (see billing.ensure_stripe).
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    # Optional override; normally the auto-created endpoint's secret is stored in the database instead.
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    stripe_auto_setup: bool = _bool(os.getenv("STRIPE_AUTO_SETUP", "true"))
    # Only for bots that sold subscriptions before bot-scoped metadata existed (StormBot): treat Stripe
    # subscriptions without a `bot` metadata key as this bot's.
    stripe_accept_unscoped: bool = _bool(os.getenv("STRIPE_ACCEPT_UNSCOPED", "false"))
    legal_base_url: str = os.getenv("LEGAL_BASE_URL", "https://utilbots.com")


settings = Settings()
