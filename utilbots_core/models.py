"""Tables every bot has. Bot-specific settings go in the bot's own tables keyed by guild_id
(ForeignKey("guilds.id", ondelete="CASCADE"))."""
from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat them as UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


class Guild(Base):
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), default="")
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    installed: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)  # set by site admins
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="guild", cascade="all, delete-orphan", order_by="Subscription.id.desc()")


class Subscription(Base):
    """An entitlement grant: manual (admin), trial, or mirrored from Stripe."""
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), index=True)
    plan: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | canceled
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | trial | stripe
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    granted_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    guild: Mapped[Guild] = relationship(back_populates="subscriptions")

    def is_live(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        exp = _aware(self.expires_at)
        return self.status == "active" and _aware(self.starts_at) <= now and (exp is None or exp > now)


class BillingCustomer(Base):
    """Guild -> Stripe customer, so checkout reuses the customer and the portal can be opened."""
    __tablename__ = "billing_customers"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    customer_id: Mapped[str] = mapped_column(String(64), unique=True)


class Usage(Base):
    """Metered usage per guild per UTC day, e.g. ("rips", 12) or ("radio_seconds", 240). See quotas.py."""
    __tablename__ = "usage"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD, UTC
    amount: Mapped[int] = mapped_column(Integer, default=0)


class KV(Base):
    """Small runtime state the bot provisions for itself (Stripe webhook secret, portal configuration id...)."""
    __tablename__ = "kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(String(500), default="")


class WebSession(Base):
    __tablename__ = "web_sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(100))
    avatar: Mapped[str | None] = mapped_column(String(64), nullable=True)
    guilds: Mapped[list] = mapped_column(JSON, default=list)  # [{id,name,icon,owner}]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    @property
    def expired(self) -> bool:
        return _aware(self.expires_at) < utcnow()
