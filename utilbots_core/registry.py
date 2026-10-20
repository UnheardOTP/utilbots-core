"""Which bot this process is. Set once by the bot package at import time."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .plans import PlanSet


@dataclass(frozen=True)
class BotSpec:
    slug: str                     # "mediabot" — also the subdomain, Stripe lookup-key prefix and Docker project name
    name: str                     # "MediaBot"
    emoji: str                    # "🎬"
    tagline: str                  # one line, shown in the hero and the utilbots.com catalog
    support_url: str = "https://discord.gg/DymH3AyAUU"
    trial_plan: str = "plus"      # plan granted by the one-time self-serve trial
    footer_note: str = ""         # e.g. a data-source credit or disclaimer
    admin_links: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # extra admin sub-nav (label, href)
    bot_permissions: int = 1024 + 2048 + 16384 + 32768 + 65536  # view, send, embed, attach, history


_spec: BotSpec | None = None
_plans: PlanSet | None = None


def configure(spec: BotSpec, plans: PlanSet) -> None:
    global _spec, _plans
    _spec, _plans = spec, plans


def current() -> tuple[BotSpec, PlanSet]:
    if _spec is None or _plans is None:
        raise RuntimeError("utilbots_core.configure(spec, plans) has not been called; import the bot's app package first")
    return _spec, _plans


def spec() -> BotSpec:
    return current()[0]


def plans() -> PlanSet:
    return current()[1]
