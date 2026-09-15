#!/usr/bin/env python3
"""
IBM MQ Usage Dashboard Creator

Creates a Splunk Observability Cloud dashboard (group + chart) that plots the
configured MQ throughput metric, as a self-serve alternative to the scheduled
Excel/PDF report in generate_report.py. Use the dashboard's built-in time
picker to view month/quarter/year trends; this does not export a fixed total.

Usage:
    python create_dashboard.py [--config config.yaml]

Environment variables:
    SFX_API_TOKEN   Splunk Observability Cloud API access token (metrics read
                     + dashboard write scope)
"""

import argparse
import logging

from report_generator.config import load_config
from report_generator.dashboard import create_dashboard
from report_generator.signalflow_query import build_program

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="IBM MQ Usage Dashboard Creator")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    args = parser.parse_args()

    config = load_config(args.config)
    program = build_program(config.metric)
    logger.info(f"Chart SignalFlow program: {program}")

    url = create_dashboard(config.splunk_observability, config.dashboard, program)
    logger.info(f"Done. Dashboard: {url}")


if __name__ == "__main__":
    main()
