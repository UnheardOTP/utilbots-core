"""utilbots-core: the shared foundation every UtilBots Discord bot is built on.

A bot calls `configure(BotSpec(...), PlanSet(...))` once at import time (in its `app/__init__.py`), then builds its
website with `utilbots_core.web.create_app(...)` and its Discord client by subclassing `utilbots_core.bot.UtilBot`.
"""
from .registry import BotSpec, configure, current

__version__ = "0.1.0"
__all__ = ["BotSpec", "configure", "current", "__version__"]
