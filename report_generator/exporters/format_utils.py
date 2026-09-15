"""Shared display-formatting helpers for the Excel/PDF exporters — purely
presentational (friendlier column labels, rounded numbers); does not touch
the underlying totals/trend DataFrames used for the actual numbers."""

import pandas as pd

FRIENDLY_COLUMNS = {
    "ibm.mq.queue.manager": "Queue Manager",
    "messaging.destination.name": "Queue",
    "total_messages_processed": "Total Messages",
    "avg_per_interval": "Avg / Interval",
    "peak_interval_value": "Peak / Interval",
    "pct_of_total": "% of Total",
    "period_start": "Period",
}


def format_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Rounds numeric columns to readable precision and renames columns to
    friendlier labels for the exported report (does not mutate the input)."""
    display = df.copy()
    for col in ("total_messages_processed", "peak_interval_value"):
        if col in display.columns:
            display[col] = display[col].round(0).astype("Int64")
    if "avg_per_interval" in display.columns:
        display["avg_per_interval"] = display["avg_per_interval"].round(1)
    if "pct_of_total" in display.columns:
        display["pct_of_total"] = display["pct_of_total"].round(2)
    return display.rename(columns=FRIENDLY_COLUMNS)
