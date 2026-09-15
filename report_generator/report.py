import logging
from typing import List

import pandas as pd

logger = logging.getLogger(__name__)


def summarize_totals(df: pd.DataFrame, group_by: List[str]) -> pd.DataFrame:
    """
    Sums per-interval deltas into a total-messages-processed figure per group
    for the whole reporting window.

    Negative deltas (which occur when a counter resets, e.g. collector or
    queue manager restart) are dropped rather than summed, since including
    them would understate the true total further. This is logged so
    undercounts are visible rather than silent.
    """
    if df.empty:
        return pd.DataFrame(columns=group_by + ["total_messages_processed"])

    reset_count = int((df["value"] < 0).sum())
    if reset_count:
        logger.warning(
            f"Dropped {reset_count} negative delta datapoint(s) — likely counter "
            f"reset(s) during the reporting window. Totals may undercount."
        )

    clean = df[df["value"] >= 0]
    totals = clean.groupby(group_by, dropna=False)["value"].sum().reset_index()
    totals = totals.rename(columns={"value": "total_messages_processed"})
    return totals.sort_values("total_messages_processed", ascending=False)
