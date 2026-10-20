from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import registry
from .models import Guild, Subscription, _aware, utcnow
from .plans import Plan


def ensure_guild(session: Session, guild_id: int, **fields) -> Guild:
    guild = session.get(Guild, guild_id)
    if guild is None:
        guild = Guild(id=guild_id)
        session.add(guild)
    for key, value in fields.items():
        if value is not None:
            setattr(guild, key, value)
    return guild


def effective_plan(session: Session, guild_id: int) -> Plan:
    """Highest-ranked live subscription wins; otherwise Free."""
    plans = registry.plans()
    best = plans.free
    subs = session.scalars(select(Subscription).where(
        Subscription.guild_id == guild_id, Subscription.status == "active")).all()
    now = utcnow()  # after the query: it autoflushes pending grants whose starts_at defaults to "now"
    for sub in subs:
        plan = plans.get(sub.plan)
        if plan and sub.is_live(now) and plan.rank > best.rank:
            best = plan
    return best


def grant(session: Session, guild_id: int, plan: str, *, days: int | None, source: str = "manual",
          note: str = "", granted_by: int | None = None) -> Subscription:
    p = registry.plans().get(plan)
    if p is None or p.rank == 0:
        raise ValueError(f"cannot grant plan {plan!r}")
    sub = Subscription(guild_id=guild_id, plan=plan, source=source, note=note, granted_by=granted_by, starts_at=utcnow(),
                       expires_at=(utcnow() + timedelta(days=days)) if days else None)
    session.add(sub)
    return sub


def revoke(session: Session, guild_id: int) -> int:
    n = 0
    for sub in session.scalars(select(Subscription).where(
            Subscription.guild_id == guild_id, Subscription.status == "active")):
        sub.status = "canceled"
        n += 1
    return n


def start_trial(session: Session, guild: Guild, days: int) -> bool:
    """One free trial per guild. Returns False if already used or already paying."""
    if guild.trial_used or effective_plan(session, guild.id).rank > 0:
        return False
    guild.trial_used = True
    grant(session, guild.id, registry.spec().trial_plan, days=days, source="trial", note="self-serve trial")
    return True


def current_expiry(session: Session, guild_id: int) -> datetime | None:
    plan = effective_plan(session, guild_id)
    if plan.rank == 0:
        return None
    now = utcnow()
    subs = [s for s in session.scalars(select(Subscription).where(Subscription.guild_id == guild_id))
            if s.is_live(now) and s.plan == plan.key]
    if any(s.expires_at is None for s in subs):
        return None
    return max(_aware(s.expires_at) for s in subs)
