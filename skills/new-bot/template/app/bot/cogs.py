import discord

from utilbots_core.bot import UtilBot
from utilbots_core.db import SessionLocal


class MainCog(discord.Cog):
    def __init__(self, bot: UtilBot):
        self.bot = bot

    @discord.slash_command(description="An example command", contexts={discord.InteractionContextType.guild})
    async def example(self, ctx: discord.ApplicationContext):
        with SessionLocal() as s:
            plan = self.bot.require(ctx.guild_id, "example", s)
            self.bot.consume(s, ctx.guild_id, "uses", 1, plan.limit("uses_per_day"), "daily use")
            s.commit()
        await ctx.respond("It works!", ephemeral=True)
