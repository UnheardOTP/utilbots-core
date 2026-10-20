"""__NAME__'s own tables. Core tables (guilds, subscriptions, usage, audit...) live in utilbots_core.models."""
from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from utilbots_core.db import Base


class GuildSettings(Base):
    __tablename__ = "__SNAKE___settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True)
