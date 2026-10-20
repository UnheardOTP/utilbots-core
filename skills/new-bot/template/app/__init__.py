"""__NAME__. Registers the bot with utilbots-core; every other module imports from here first."""
import utilbots_core

from .plans import PLANS

SPEC = utilbots_core.BotSpec(
    slug="__SLUG__",
    name="__NAME__",
    emoji="__EMOJI__",
    tagline="__TAGLINE__",
    trial_plan="plus",
)
utilbots_core.configure(SPEC, PLANS)
