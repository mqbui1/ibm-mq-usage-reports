import logging
from typing import List

import pandas as pd
from signalfx.signalflow import SignalFlowClient, messages

from .config import MetricConfig, SplunkObservabilityConfig

logger = logging.getLogger(__name__)


def build_program(metric: MetricConfig) -> str:
    """
    Builds a SignalFlow program that converts the cumulative counter metric
    into per-interval deltas, grouped by the configured dimensions.

    NOTE: this assumes metric.name is a monotonically increasing counter
    (e.g. ibm.mq.message.deq.count, per Antoine — requires MQ queue
    statistics to be enabled). delta() will emit a large negative value
    across a counter reset (collector restart, queue manager bounce).
    summarize_totals() in report.py drops negative deltas rather than
    summing them, but that means totals can undercount across a reset —
    validate against a known-good period before trusting these numbers.
    """
    filter_clauses = []
    for dim, values in metric.filters.items():
        if not values:
            continue
        quoted = ", ".join(f"'{v}'" for v in values)
        filter_clauses.append(f"filter('{dim}', {quoted})")

    data_call = f"data('{metric.name}'"
    if filter_clauses:
        data_call += f", filter={' and '.join(filter_clauses)}"
    data_call += ")"

    group_by_list = "[" + ", ".join(f"'{g}'" for g in metric.group_by) + "]"
    return f"{data_call}.delta().sum(by={group_by_list}).publish()"


class SignalFlowQuery:
    def __init__(self, sfx_config: SplunkObservabilityConfig):
        self._client = SignalFlowClient(
            token=sfx_config.api_token,
            endpoint=sfx_config.stream_endpoint,
        )

    def run(self, program: str, start_ms: int, stop_ms: int, group_by: List[str]) -> pd.DataFrame:
        """
        Executes `program` over [start_ms, stop_ms) and returns a long-format
        DataFrame with one row per (group_by dimensions..., timestamp, value).
        """
        logger.info(f"Executing SignalFlow program: {program}")
        computation = self._client.execute(program, start=start_ms, stop=stop_ms)

        metadata = {}
        rows = []
        for msg in computation.stream():
            if isinstance(msg, messages.MetadataMessage):
                metadata[msg.tsid] = msg.properties
            elif isinstance(msg, messages.DataMessage):
                for tsid, value in msg.data.items():
                    rows.append(
                        {
                            "tsid": tsid,
                            "timestamp_ms": msg.logical_timestamp_ms,
                            "value": value,
                        }
                    )

        df = pd.DataFrame(rows)
        if df.empty:
            logger.warning("SignalFlow query returned no data for the requested window")
            return pd.DataFrame(columns=group_by + ["timestamp_ms", "value"])

        for dim in group_by:
            df[dim] = df["tsid"].map(lambda tsid: metadata.get(tsid, {}).get(dim, "unknown"))

        return df.drop(columns=["tsid"])

    def close(self):
        self._client.close()
