"""Per-guild daily usage allowances (UTC days)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Usage, utcnow


def today() -> str:
    return utcnow().strftime("%Y-%m-%d")


def used(session: Session, guild_id: int, key: str) -> int:
    row = session.get(Usage, (guild_id, key, today()))
    return row.amount if row else 0


def remaining(session: Session, guild_id: int, key: str, limit: int | None) -> int | None:
    return None if limit is None else max(0, limit - used(session, guild_id, key))


def consume(session: Session, guild_id: int, key: str, amount: int, limit: int | None) -> bool:
    """Add `amount` if it fits under `limit` (None = unlimited, still recorded). Locks the row on Postgres so two
    concurrent requests can't both slip under the limit. Caller commits."""
    day = today()
    stmt = select(Usage).where(Usage.guild_id == guild_id, Usage.key == key, Usage.day == day)
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    row = session.scalar(stmt)
    current = row.amount if row else 0
    if limit is not None and current + amount > limit:
        return False
    if row is None:
        session.add(Usage(guild_id=guild_id, key=key, day=day, amount=amount))
    else:
        row.amount = current + amount
    session.flush()
    return True


def refund(session: Session, guild_id: int, key: str, amount: int) -> None:
    row = session.get(Usage, (guild_id, key, today()))
    if row:
        row.amount = max(0, row.amount - amount)
