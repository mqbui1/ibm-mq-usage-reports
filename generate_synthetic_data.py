#!/usr/bin/env python3
"""
IBM MQ Synthetic Data Generator — DEV/TEST ONLY

Sends fake ibm.mq.message.deq.count gauge datapoints to Splunk Observability
Cloud so generate_report.py / create_dashboard.py can be exercised end-to-end
without a real IBM MQ collector. Every datapoint is tagged
data.source=ibm-mq-usage-reports-synthetic so it can be identified/filtered —
there is no way to delete it afterwards via the ingest API.

Only run this against a sandbox/non-production org, never a customer's org.

Usage:
    python generate_synthetic_data.py [--config config.yaml] [--hours-back 6]
        [--interval-minutes 5] [--queue-managers MQU1,MQU2] [--queues-per-qmgr 3]

Environment variables:
    SFX_API_TOKEN   Splunk Observability Cloud API access token (metrics
                     ingest scope)
"""

import argparse
import logging

from report_generator.config import load_config
from report_generator.synthetic_data import generate_datapoints, send_datapoints

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="IBM MQ Synthetic Data Generator (dev/test only)")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    parser.add_argument("--hours-back", type=int, default=6, help="How far back to backfill datapoints")
    parser.add_argument("--interval-minutes", type=int, default=5, help="Spacing between synthetic datapoints")
    parser.add_argument("--queue-managers", default="MQU1,MQU2", help="Comma-separated synthetic queue manager names")
    parser.add_argument("--queues-per-qmgr", type=int, default=3, help="Number of synthetic queues per queue manager")
    args = parser.parse_args()

    config = load_config(args.config)
    queue_managers = [q.strip() for q in args.queue_managers.split(",") if q.strip()]

    datapoints = generate_datapoints(
        metric_name=config.metric.name,
        queue_managers=queue_managers,
        queues_per_qmgr=args.queues_per_qmgr,
        hours_back=args.hours_back,
        interval_minutes=args.interval_minutes,
    )
    logger.info(f"Generated {len(datapoints)} synthetic datapoints for {queue_managers}")

    sent = send_datapoints(config.splunk_observability, datapoints)
    logger.info(f"Done. Sent {sent} datapoints. Tag: data.source=ibm-mq-usage-reports-synthetic")


if __name__ == "__main__":
    main()
