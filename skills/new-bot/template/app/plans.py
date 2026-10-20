"""Plans for __NAME__. Single source of truth for the bot, the website and Stripe: prices here are synced to
Stripe automatically on deploy (a change creates a new price; existing subscribers keep theirs)."""
from utilbots_core.plans import Plan, PlanSet

FEATURES = {
    "example": "An example feature",
    "example_plus": "An example Plus feature",
}

_FREE = frozenset({"example"})
_PLUS = _FREE | {"example_plus"}

PLANS = PlanSet(FEATURES, {
    "free": Plan("free", "Free", 0, 0, _FREE, {"uses_per_day": 10}, ("10 uses a day",)),
    "plus": Plan("plus", "Plus", 1, 300, _PLUS, {"uses_per_day": 100}, ("100 uses a day",)),
    "pro": Plan("pro", "Pro", 2, 600, _PLUS, {"uses_per_day": None}, ("Unlimited use",)),
})
