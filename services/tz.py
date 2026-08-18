"""Single source of truth for "what day/time is it right now."

Streamlit Cloud containers run in UTC, not Eastern. Every naive call like
`pd.Timestamp.now()` or `date.today()` was silently using the server's
UTC clock instead of the operator's actual Maryland/DC/VA timezone —
wrong for a chunk of every single day (worse in the evening, when UTC
has already rolled over to the next calendar date but it's still
yesterday-equivalent locally). Route every "today"/"now" through here
instead so there's exactly one place this logic lives.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd

EASTERN = ZoneInfo("America/New_York")  # handles EST/EDT (DST) automatically


def eastern_now() -> pd.Timestamp:
    """Current instant, correctly localized to Eastern time."""
    return pd.Timestamp.now(tz=EASTERN)


def eastern_today_naive() -> pd.Timestamp:
    """Today's calendar date in Eastern time, as a timezone-naive
    midnight Timestamp. Deliberately naive (not tz-aware) so it compares
    cleanly against the Service Date / Date-Timing columns parsed from
    the sheet, which are plain calendar dates with no timezone of their
    own — comparing a tz-aware Timestamp against those raises a
    TypeError in pandas rather than silently doing the wrong thing.
    """
    return eastern_now().normalize().tz_localize(None)


def eastern_today() -> date:
    """Today's calendar date in Eastern time, as a plain `date` — for
    st.date_input() defaults and filenames, where a Timestamp isn't
    the right type.
    """
    return eastern_now().date()
