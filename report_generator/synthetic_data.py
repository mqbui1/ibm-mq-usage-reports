import logging
import random
import time
from typing import List

import requests

from .config import SplunkObservabilityConfig

logger = logging.getLogger(__name__)

# Tag every synthetic datapoint with this so it can be filtered/identified/ignored
# later — this tool does not (and cannot, via the ingest API) delete datapoints
# once sent.
SYNTHETIC_TAG_KEY = "data.source"
SYNTHETIC_TAG_VALUE = "ibm-mq-usage-reports-synthetic"


def generate_datapoints(
    metric_name: str,
    queue_managers: List[str],
    queues_per_qmgr: int,
    hours_back: int,
    interval_minutes: int,
) -> List[dict]:
    """
    Builds synthetic gauge datapoints shaped like what the OTel ibm-mq-metrics
    receiver would send for ibm.mq.message.deq.count: one value per interval,
    representing "messages dequeued since the last RESET QSTATS" (i.e. already
    a per-interval count — see README "Metric type caveat"), NOT a running total.
    """
    now_ms = int(time.time() * 1000)
    interval_ms = interval_minutes * 60 * 1000
    steps = int((hours_back * 60) // interval_minutes)

    datapoints = []
    for qmgr in queue_managers:
        for q in range(1, queues_per_qmgr + 1):
            queue_name = f"TEST.QUEUE.{q}"
            base_rate = random.randint(50, 400)
            for step in range(steps, -1, -1):
                ts = now_ms - step * interval_ms
                value = max(0, int(random.gauss(base_rate, base_rate * 0.2)))
                datapoints.append(
                    {
                        "metric": metric_name,
                        "value": value,
                        "timestamp": ts,
                        "dimensions": {
                            "ibm.mq.queue.manager": qmgr,
                            "messaging.destination.name": queue_name,
                            "ibm.mq.queue.type": "local-normal",
                            SYNTHETIC_TAG_KEY: SYNTHETIC_TAG_VALUE,
                        },
                    }
                )
    return datapoints


def send_datapoints(sfx_config: SplunkObservabilityConfig, datapoints: List[dict], batch_size: int = 500) -> int:
    """
    Sends gauge datapoints to the SignalFx ingest API in batches.

    Note: the ingest API is built for near-real-time telemetry, not historical
    backfill — datapoints with timestamps too far in the past may be silently
    dropped or rejected depending on your org's ingest window. If a large
    --hours-back doesn't show up in the UI, retry with a smaller value.
    """
    headers = {"X-SF-TOKEN": sfx_config.ingest_token or sfx_config.api_token, "Content-Type": "application/json"}
    sent = 0
    for i in range(0, len(datapoints), batch_size):
        batch = datapoints[i : i + batch_size]
        resp = requests.post(
            f"{sfx_config.ingest_endpoint}/v2/datapoint",
            headers=headers,
            json={"gauge": batch},
        )
        resp.raise_for_status()
        sent += len(batch)
        logger.info(f"Sent {sent}/{len(datapoints)} datapoints")
    return sent
