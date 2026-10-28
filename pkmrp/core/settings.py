"""Planning settings. Defaults here; the stored copy (mrp_settings in PK_Ops)
overrides them once the store exists.

Several defaults are open questions for Jared -- they are marked OPEN and
chosen to be conservative and visible rather than clever.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlanSettings:
    # Which SO date places backlog demand in time. OPEN: CUSDUE_28 is
    # rewritten to the planned ship date, CURDUE_28 is MAX's current due;
    # PK Dispatch's Planning lists use CUSDUE, so this does too until decided.
    demand_date: str = "cus_due"

    # A line due in this year or later is unscheduled demand parked on a
    # placeholder date (2032-34 year-ends): kept off the time-phased plan and
    # put on a worklist. Same rule as Control Tower's Orders page.
    unscheduled_from_year: int = 2030

    # Product_Structure.TYPCDE_02 codes that are real components. OPEN: 'N'
    # is 432K rows and what existing code uses; 'E' (20K), 'P', 'R' and blank
    # are unexplained, so they are left out and counted on the worklist.
    bom_type_codes: tuple = ("N",)

    # Part_Master.TYPE_01: A = make (explode through), B = buy (plan
    # purchases). Everything else (Y bulk, X, P, M, O, S, T, ...) is not
    # planned; a shortage on one is reported, not ordered. OPEN beyond A/B/Y.
    make_types: tuple = ("A",)
    buy_types: tuple = ("B",)

    # Printed-on-demand documentation, never bought or built as stock.
    doc_prefixes: tuple = ("90-", "97-")

    # MAX's master-schedule (-FAMILY) entries double-count booked orders.
    include_master_schedule: bool = False

    # An open receipt that won't be needed for this many calendar days after
    # it lands is a push-out candidate.
    push_out_days: int = 30

    # Until core/segment.py exists: a part whose lead time is at least this
    # many business days (~90 calendar) is bought ahead of the backlog on
    # purpose, so an open receipt no backlog line needs is "covering beyond
    # the backlog", not a cancel candidate. The 370-day FPGA's 290 units on
    # order were placed for demand past the backlog horizon.
    committed_lead_bdays: int = 63

    # Respect MAX's order modifiers on planned orders.
    use_min_mult_qty: bool = True

    # Part classes switched to live (buyers act on them). Empty = all shadow.
    live_classes: tuple = field(default_factory=tuple)
