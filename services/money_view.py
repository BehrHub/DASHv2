from __future__ import annotations

# If today's displayed dollar figures are treated as net (post-tax/expense),
# this is the assumed fraction that survives to become "net" — so gross-up
# reverses it. 0.65 net -> divide by 0.65 to get back to gross.
GROSS_MARGIN = 0.62

DAYS_PER_YEAR = 365
WEEKS_PER_YEAR = 52
MONTHS_PER_YEAR = 12


def annualize(amount: float, periods_per_year: float) -> float:
    """For genuine time-rate figures (a day's rate, a month's revenue,
    a week's revenue) — extrapolates that rate across a full year.
    """
    return amount * periods_per_year


def annualize_gross(amount: float, periods_per_year: float) -> float:
    """Rate-based figures also carry the same assumed net margin as
    point-value figures, so the annualized/gross toggle should apply
    BOTH transformations together, not just the period multiplier alone.
    """
    return gross_up(amount) * periods_per_year


def gross_up(amount: float) -> float:
    """For point-value figures (a single transaction, a per-visit average,
    a career-to-date total) — annualizing doesn't mean anything for these,
    so the toggle instead reverses the assumed net margin to show the
    gross figure.
    """
    if not GROSS_MARGIN:
        return amount
    return amount / GROSS_MARGIN
