"""Discord client base class. A bot's `app/bot/main.py` is typically:

    class MediaBot(UtilBot):
        def __init__(self):
            super().__init__(status_text="links · /rip")
            self.add_cog(RipCog(self))

    def main():
        run(MediaBot, seed=seed)
"""
import asyncio
import logging
from collections.abc import Callable

import discord
from sqlalchemy.orm import Session

from . import entitlements, quotas, registry
from .config import settings
from .db import SessionLocal, init_db
from .models import Guild
from .plans import Plan

log = logging.getLogger("utilbots.bot")


class FeatureLocked(discord.ApplicationCommandError):
    def __init__(self, feature: str):
        self.feature = feature
        super().__init__(feature)


class QuotaExceeded(discord.ApplicationCommandError):
    def __init__(self, message: str):
        super().__init__(message)


class ServerDisabled(discord.ApplicationCommandError):
    pass


def billing_url(guild_id: int) -> str:
    return f"{settings.public_url}/guild/{guild_id}/billing"


def locked_message(feature: str, guild_id: int | None) -> str:
    _, plans = registry.current()
    need = plans.min_plan_for(feature)
    label = plans.features.get(feature, feature)
    where = f" Upgrade at {billing_url(guild_id)}" if guild_id else ""
    return f"🔒 **{label}** needs the **{need.name}** plan.{where}"


class UtilBot(discord.Bot):
    """Keeps the `guilds` table in sync, blocks disabled servers, and turns FeatureLocked/QuotaExceeded into
    friendly ephemeral replies."""

    def __init__(self, *, status_text: str | None = None, intents: discord.Intents | None = None, **kwargs):
        activity = discord.Activity(type=discord.ActivityType.watching, name=status_text) if status_text else None
        super().__init__(intents=intents or discord.Intents.default(), activity=activity, **kwargs)
        self.add_check(self._not_disabled)
        self.add_cog(PlanCog(self))

    # ---- plan helpers -----------------------------------------------------------------------------------------
    @staticmethod
    def plan_for(guild_id: int | None, session: Session | None = None) -> Plan:
        if guild_id is None:
            return registry.plans().free
        if session is not None:
            return entitlements.effective_plan(session, guild_id)
        with SessionLocal() as s:
            return entitlements.effective_plan(s, guild_id)

    def require(self, guild_id: int | None, feature: str, session: Session | None = None) -> Plan:
        plan = self.plan_for(guild_id, session)
        if not plan.has(feature):
            raise FeatureLocked(feature)
        return plan

    @staticmethod
    def consume(session: Session, guild_id: int, key: str, amount: int, limit: int | None, what: str) -> None:
        """Count usage against a daily allowance or raise QuotaExceeded."""
        if not quotas.consume(session, guild_id, key, amount, limit):
            raise QuotaExceeded(f"⏳ This server has used today's {what} allowance ({limit}). It resets at 00:00 UTC, "
                                f"or upgrade for more: {billing_url(guild_id)}")

    # ---- guards -----------------------------------------------------------------------------------------------
    @staticmethod
    async def _not_disabled(ctx: discord.ApplicationContext) -> bool:
        if ctx.guild_id is None:
            return True
        with SessionLocal() as s:
            row = s.get(Guild, ctx.guild_id)
            if row is not None and row.disabled:
                raise ServerDisabled()
        return True

    async def on_application_command_error(self, ctx: discord.ApplicationContext, error: Exception):
        err = getattr(error, "original", error)
        if isinstance(err, FeatureLocked):
            text = locked_message(err.feature, ctx.guild_id)
        elif isinstance(err, QuotaExceeded):
            text = str(err)
        elif isinstance(err, ServerDisabled):
            text = f"{registry.spec().name} has been disabled for this server."
        elif isinstance(err, discord.CheckFailure):
            text = "You can't use that command here."
        else:
            log.exception("command %s failed", getattr(ctx.command, "qualified_name", "?"), exc_info=err)
            text = "Something went wrong. Please try again in a moment."
        try:
            if ctx.response.is_done():
                await ctx.followup.send(text, ephemeral=True)
            else:
                await ctx.respond(text, ephemeral=True)
        except discord.HTTPException:
            pass

    # ---- guild sync -------------------------------------------------------------------------------------------
    @staticmethod
    def _sync(guild: discord.Guild, installed: bool | None = True) -> None:
        with SessionLocal() as s:
            entitlements.ensure_guild(s, guild.id, name=guild.name, icon=guild.icon.key if guild.icon else None,
                                      owner_id=guild.owner_id, installed=installed)
            s.commit()

    async def on_ready(self):
        live = {g.id for g in self.guilds}
        with SessionLocal() as s:
            for g in self.guilds:
                entitlements.ensure_guild(s, g.id, name=g.name, icon=g.icon.key if g.icon else None,
                                          owner_id=g.owner_id, installed=True)
            for row in s.query(Guild).filter(Guild.installed.is_(True)):
                if row.id not in live:
                    row.installed = False
            s.commit()
        log.info("ready as %s in %d guild(s)", self.user, len(live))

    async def on_guild_join(self, guild: discord.Guild):
        self._sync(guild)
        log.info("joined %s (%s)", guild.name, guild.id)

    async def on_guild_remove(self, guild: discord.Guild):
        with SessionLocal() as s:
            row = s.get(Guild, guild.id)
            if row:
                row.installed = False
                s.commit()

    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        self._sync(after, installed=None)


class PlanCog(discord.Cog):
    """/plan: every bot shows the server's plan, what's locked, and where to upgrade."""

    def __init__(self, bot: UtilBot):
        self.bot = bot

    @discord.slash_command(name="plan", description="Show this server's plan and what upgrading unlocks")
    async def plan(self, ctx: discord.ApplicationContext):
        spec, plans = registry.current()
        current = self.bot.plan_for(ctx.guild_id)
        lines = [f"{'✅' if current.has(k) else '🔒'} {label}" for k, label in plans.features.items()]
        embed = discord.Embed(title=f"{spec.emoji} {spec.name} · {current.name} plan", description="\n".join(lines),
                              color=0x5865F2)
        for h in current.highlights:
            embed.add_field(name="\u200b", value=h, inline=False)
        if ctx.guild_id:
            embed.add_field(name="Manage", value=billing_url(ctx.guild_id), inline=False)
        await ctx.respond(embed=embed, ephemeral=True)


def run(bot_cls: type[UtilBot], *, seed: Callable[[Session], None] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.discord_token:
        raise SystemExit("DISCORD_TOKEN is not set")
    init_db(seed)
    bot = bot_cls()
    bot.run(settings.discord_token)


async def to_thread(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)
