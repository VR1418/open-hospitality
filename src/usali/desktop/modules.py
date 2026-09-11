"""ModuleRegistry (PRD 5.2 & 5.4, ADR-D3): the single source of truth.

Each module names the `create_app` surfaces it mounts, the portal pages it
puts in the navigation, and its published limitations — together, so the
limitations can never drift from what is actually mounted (PRD L-2), and a
module without limitations text fails a test rather than shipping (L-4).

Limitations are written in the product's plain language (L-5), and where
there is a workaround it sits beside the limitation (L-3).
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Limitation:
    text: str
    workaround: str | None = None


@dataclass(frozen=True)
class Module:
    id: str
    name: str
    summary: str
    status: Literal["available", "coming_soon"]
    required: bool
    default_on: bool
    surfaces: frozenset[str]
    nav: tuple[str, ...]
    limitations: tuple[Limitation, ...]


# Surfaces the desktop never mounts, whatever is chosen: the invite-gated
# signup and the anonymous marketing preview belong to the hosted service.
HOSTED_ONLY: frozenset[str] = frozenset({"signup", "preview"})

# Mounted whenever the app runs. `workforce` also carries GET /api/me, the
# portal's identity call, so it cannot follow Payroll & People off; turning
# that module off hides its pages, and ADR-D3 records the gap (the fix is an
# upstream split of /me into its own router, offered back).
ALWAYS_MOUNTED: frozenset[str] = frozenset({"workforce"})

ACCOUNTING = Module(
    id="accounting",
    name="Accounting & Reporting",
    summary=(
        "Your night-audit reports turned into a USALI operating statement, "
        "statistics, a ledger, bank checks and exports."
    ),
    status="available",
    required=True,
    default_on=True,
    surfaces=frozenset({
        "portal", "property_config", "night_audit", "checklist", "integrations",
        "integrations_callback", "gl", "ingest",
    }),
    nav=(
        "/dashboard", "/setup", "/sos", "/upload", "/reports", "/performance", "/qbo",
        "/integrations", "/coverage", "/night-audit", "/gl", "/property-config",
    ),
    limitations=(
        Limitation(
            "Reads reports from three PMS systems: Opera, AutoClerk and choiceADVANTAGE.",
            "For any other system, forward us a sample report so we can add it.",
        ),
        Limitation(
            "If your PMS vendor changes a report's layout, we won't be able to read it "
            "until an update ships. The report is set aside with the reason — nothing "
            "wrong is written to your books.",
        ),
        Limitation(
            "Your hotel's own transaction codes need sorting into categories once, by "
            "you. Expect 10–20 minutes in the first month.",
        ),
        Limitation("This is not a tax product. It won't work out, file or advise on any tax."),
        Limitation(
            "It doesn't route bills for approval or pay them. It reads what happened.",
        ),
        Limitation(
            "Checking against your bank works well for card settlements and payroll, "
            "less well for cash deposits and anything paid from other accounts.",
        ),
    ),
)

PAYROLL = Module(
    id="payroll",
    name="Payroll & People",
    summary=(
        "Employee records, schedules against rooms sold, an iPad time clock, "
        "timecard approval and labour cost by department."
    ),
    status="available",
    required=False,
    default_on=False,
    surfaces=frozenset({
        "face_enrollment", "kiosk_admin", "kiosk", "timecard", "schedule", "crm",
        "pii", "sick_leave", "payroll_run",
    }),
    nav=(
        "/payroll-dashboard", "/employees", "/schedule", "/payroll", "/timecards",
        "/kiosk", "/kiosk-devices",
    ),
    limitations=(
        Limitation(
            "This doesn't pay anybody. It prepares an approved pay period and hands it "
            "to ADP or Gusto, which work out take-home pay, withhold tax and move the money.",
        ),
        Limitation("No tax calculation or filing. Ever."),
        Limitation(
            "Overtime and sick-leave rules are built in for a few states only. "
            "Elsewhere, hours are counted correctly but the legal reading is yours.",
            "Check overtime and sick-leave rules with your advisor for your state.",
        ),
        Limitation(
            "The face-matching time clock is off, and won't switch on in most states: "
            "biometric privacy law varies too much to guess.",
        ),
        Limitation(
            "Pay rates are visible only to a payroll administrator, and every look is "
            "recorded. This can't be changed.",
        ),
        Limitation(
            "Labour figures for a department with fewer than two paid people are hidden "
            "and left out of totals, so nobody's pay can be worked out from them.",
        ),
    ),
)

UTILITIES = Module(
    id="utilities",
    name="Hotel Management Utilities",
    summary=(
        "Housekeeping board, maintenance tickets, a document register, a vendor "
        "directory and a guest-demand feed."
    ),
    status="coming_soon",
    required=False,
    default_on=False,
    surfaces=frozenset(),
    nav=(),
    limitations=(
        Limitation(
            "None of this is built yet. It is shown here so you can see where the "
            "product is going, not so you can plan around it.",
        ),
    ),
)

MODULES: tuple[Module, ...] = (ACCOUNTING, PAYROLL, UTILITIES)
BY_ID: dict[str, Module] = {m.id: m for m in MODULES}


def resolve(selected: Collection[str] | None) -> frozenset[str]:
    """The module ids that will actually be on. Required modules always are;
    coming-soon and unknown ids never are; no selection means the defaults."""
    chosen = (
        {m.id for m in MODULES if m.default_on} if selected is None else set(selected)
    )
    return frozenset(
        m.id for m in MODULES
        if m.status == "available" and (m.required or m.id in chosen)
    )


def mounted_surfaces(enabled: Collection[str]) -> frozenset[str]:
    surfaces = set(ALWAYS_MOUNTED)
    for module_id in resolve(enabled):
        surfaces |= BY_ID[module_id].surfaces
    return frozenset(surfaces - HOSTED_ONLY)


def mount_predicate(enabled: Collection[str]) -> Callable[[str], bool]:
    """The `create_app(mount=…)` predicate for a set of enabled modules."""
    surfaces = mounted_surfaces(enabled)
    return lambda surface: surface in surfaces
