import logging
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_FREQ_ALIASES = {"hourly": "h", "daily": "D"}


def clean_negative_deltas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drops negative-value datapoints (counter resets, e.g. collector or queue
    manager restart) and logs how many were dropped. Call once on the raw
    per-interval DataFrame before passing it to summarize_totals()/
    summarize_trend() so the drop is logged exactly once.
    """
    if df.empty:
        return df
    reset_count = int((df["value"] < 0).sum())
    if reset_count:
        logger.warning(
            f"Dropped {reset_count} negative delta datapoint(s) — likely counter "
            f"reset(s) during the reporting window. Totals may undercount."
        )
    return df[df["value"] >= 0]


def infer_resolution_ms(df: pd.DataFrame) -> Optional[int]:
    """Infers the query's per-interval resolution from the smallest gap between
    consecutive distinct timestamps in the data (for labeling avg/peak columns)."""
    if df.empty:
        return None
    ts = sorted(df["timestamp_ms"].unique())
    diffs = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    return min(diffs) if diffs else None


def _aggregate(df: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    # Collapse any series sharing the same group+timestamp before computing
    # per-interval stats, so multiple raw series don't inflate avg/peak.
    per_interval = df.groupby(group_cols + ["timestamp_ms"], dropna=False)["value"].sum().reset_index()
    return (
        per_interval.groupby(group_cols, dropna=False)["value"]
        .agg(total_messages_processed="sum", avg_per_interval="mean", peak_interval_value="max")
        .reset_index()
    )


def summarize_totals(df: pd.DataFrame, group_by: List[str]) -> pd.DataFrame:
    """
    Aggregates per-interval values into a total-messages-processed figure per
    group_by, for the whole reporting window. Also adds:
      - avg_per_interval / peak_interval_value: from the raw per-interval
        values already in df (no extra query needed).
      - a subtotal row per parent group (group_by[:-1]) when group_by has
        more than one dimension — e.g. one row per queue manager summing
        that manager's queues — marked via is_subtotal=True.
      - pct_of_total: each row's share of the grand total (queue-level rows
        and their queue-manager subtotal both sum consistently to 100%).
    """
    cols = group_by + [
        "total_messages_processed",
        "avg_per_interval",
        "peak_interval_value",
        "pct_of_total",
        "is_subtotal",
    ]
    if df.empty:
        return pd.DataFrame(columns=cols)

    detail = _aggregate(df, group_by)
    detail["is_subtotal"] = False

    if len(group_by) > 1:
        parent_cols = group_by[:-1]
        subtotal = _aggregate(df, parent_cols)
        subtotal["is_subtotal"] = True
        for col in group_by[len(parent_cols):]:
            subtotal[col] = "— subtotal —"
        combined = pd.concat([detail, subtotal], ignore_index=True)
        sort_cols = parent_cols + ["is_subtotal", "total_messages_processed"]
        ascending = [True] * len(parent_cols) + [True, False]
    else:
        combined = detail
        sort_cols = ["is_subtotal", "total_messages_processed"]
        ascending = [True, False]

    grand_total = detail["total_messages_processed"].sum()
    combined["pct_of_total"] = (
        (combined["total_messages_processed"] / grand_total * 100).round(2) if grand_total else 0.0
    )
    combined = combined.sort_values(sort_cols, ascending=ascending)

    return combined[cols].reset_index(drop=True)


def _bucket_timestamp(ts_ms: pd.Series, granularity: str) -> pd.Series:
    dt = pd.to_datetime(ts_ms, unit="ms", utc=True)
    if granularity == "monthly":
        return dt.dt.to_period("M").dt.to_timestamp()
    if granularity == "weekly":
        return dt.dt.to_period("W").dt.start_time
    freq = _FREQ_ALIASES.get(granularity, "D")
    return dt.dt.floor(freq)


def summarize_trend(df: pd.DataFrame, group_by: List[str], granularity: str = "daily") -> pd.DataFrame:
    """
    Buckets per-interval values into a period_start | group_by... |
    total_messages_processed breakdown at `granularity` resolution
    ("hourly"/"daily"/"weekly"/"monthly") — shows the trend across the
    reporting window instead of a single endpoint total.
    """
    cols = ["period_start"] + group_by + ["total_messages_processed"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    bucketed = df.copy()
    bucketed["period_start"] = _bucket_timestamp(bucketed["timestamp_ms"], granularity)
    trend = (
        bucketed.groupby(["period_start"] + group_by, dropna=False)["value"]
        .sum()
        .reset_index()
        .rename(columns={"value": "total_messages_processed"})
    )
    return trend.sort_values(["period_start"] + group_by)[cols].reset_index(drop=True)
