"""Plans and features. Each bot declares its own PlanSet; this module only defines the shape."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Plan:
    key: str                         # "free" | "plus" | "pro" (any keys work; "free" must exist, rank 0)
    name: str
    rank: int
    price_cents: int                 # monthly price in USD cents; 0 for free. Stripe prices are synced from this.
    features: frozenset[str]
    limits: dict[str, int | None] = field(default_factory=dict)  # e.g. {"rips_per_day": 15}; None = unlimited
    highlights: tuple[str, ...] = ()  # short lines shown above the feature checklist ("15 rips a day")

    def has(self, feature: str) -> bool:
        return feature in self.features

    def limit(self, key: str, default: int | None = None) -> int | None:
        return self.limits.get(key, default)

    @property
    def price_label(self) -> str:
        if not self.price_cents:
            return "$0"
        dollars = self.price_cents / 100
        return f"${dollars:.0f} / month" if dollars.is_integer() else f"${dollars:.2f} / month"

    def __hash__(self) -> int:
        return hash(self.key)


@dataclass(frozen=True)
class PlanSet:
    features: dict[str, str]         # feature key -> human description (pricing page, order preserved)
    plans: dict[str, Plan]

    def __post_init__(self):
        if "free" not in self.plans or self.plans["free"].rank != 0:
            raise ValueError("a PlanSet needs a 'free' plan with rank 0")
        unknown = {f for p in self.plans.values() for f in p.features} - set(self.features)
        if unknown:
            raise ValueError(f"plans use undeclared features: {sorted(unknown)}")

    @property
    def free(self) -> Plan:
        return self.plans["free"]

    @property
    def paid(self) -> list[Plan]:
        return sorted((p for p in self.plans.values() if p.rank > 0), key=lambda p: p.rank)

    def get(self, key: str) -> Plan | None:
        return self.plans.get(key)

    def min_plan_for(self, feature: str) -> Plan:
        return min((p for p in self.plans.values() if p.has(feature)), key=lambda p: p.rank)

    def ordered(self) -> list[Plan]:
        return sorted(self.plans.values(), key=lambda p: p.rank)
