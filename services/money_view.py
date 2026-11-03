"""One set of money rules for the whole site.

Three display modes, chosen by the header switch:
  NET        - the recorded amounts, untouched.
  GROSS      - every dollar figure / NET_SHARE (net is NET_SHARE of gross,
               so 0.65 turns $65 net into $100 gross).
  ANNUALIZED - GROSS, and any figure that belongs to a time period is then
               multiplied up to a year: per day x260 (work days), per week
               x52, per month x12. Totals and per-event figures stay GROSS.
               An open (unfinished) period uses its projected run-rate.

NET_SHARE starts at 0.65 and is edited from the Ledger page; app.py loads
the saved value from the Google Sheet "Settings" tab on every run and calls
set_net_share(), so every page reads the same number.
"""
from __future__ import annotations

NET_SHARE_DEFAULT = 0.65
_net_share = NET_SHARE_DEFAULT

DAYS_PER_YEAR = 260      # work days, not calendar days
WEEKS_PER_YEAR = 52
MONTHS_PER_YEAR = 12
PER_YEAR = {"day": DAYS_PER_YEAR, "week": WEEKS_PER_YEAR, "month": MONTHS_PER_YEAR}

NET, GROSS, ANNUAL = "net", "gross", "annual"


def clean_net_share(value) -> float | None:
    """Accepts 0.65 or 65 (as a percent); returns a float in [0.30, 1.00] or None."""
    try:
        v = float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    if v > 1.0:
        v = v / 100.0
    if not (0.30 <= v <= 1.0):
        return None
    return round(v, 4)


def set_net_share(value) -> None:
    global _net_share
    v = clean_net_share(value)
    _net_share = v if v is not None else NET_SHARE_DEFAULT


def net_share() -> float:
    return _net_share


def gross_up(amount: float) -> float:
    """NET -> GROSS for any dollar figure."""
    return amount / _net_share if _net_share else amount


def annualize(amount: float, periods_per_year: float) -> float:
    return amount * periods_per_year


def annualize_gross(amount: float, periods_per_year: float) -> float:
    """NET per-period figure -> ANNUALIZED (gross, then x periods/year)."""
    return gross_up(amount) * periods_per_year


def money(amount: float, mode: str, period: str | None = None) -> float:
    """The one conversion every page uses.
    period: None for totals / per-event figures, or "day" / "week" / "month"
    for a figure that is a rate over that period (only matters in ANNUAL)."""
    if mode == NET:
        return amount
    g = gross_up(amount)
    if mode == ANNUAL and period in PER_YEAR:
        return g * PER_YEAR[period]
    return g
