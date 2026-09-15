#!/usr/bin/env python3
"""
IBM MQ Usage Report Generator

Pulls a cumulative counter metric (default: ibm.mq.message.deq.count) from
Splunk Observability Cloud via the SignalFlow API for a completed calendar
period, and generates an Excel/PDF report of total messages processed per
queue manager / queue.

Usage:
    python generate_report.py --period month [--config config.yaml] [--reference-date YYYY-MM-DD]

Environment variables:
    SFX_API_TOKEN   Splunk Observability Cloud API access token (metrics read scope)
"""

import argparse
import logging
import os
from datetime import datetime

from report_generator.config import load_config
from report_generator.exporters.excel_exporter import export_excel
from report_generator.exporters.pdf_exporter import export_pdf
from report_generator.periods import resolve_period
from report_generator.report import summarize_totals
from report_generator.signalflow_query import SignalFlowQuery, build_program

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="IBM MQ Usage Report Generator")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    parser.add_argument("--period", choices=["month", "quarter", "year"], required=True)
    parser.add_argument("--reference-date", help="YYYY-MM-DD; defaults to today. Report covers the previous complete period relative to this date.")
    args = parser.parse_args()

    config = load_config(args.config)
    reference = datetime.strptime(args.reference_date, "%Y-%m-%d") if args.reference_date else None
    start_ms, stop_ms, label = resolve_period(args.period, reference)
    logger.info(f"Reporting period: {label} ({start_ms} - {stop_ms})")

    program = build_program(config.metric)
    query = SignalFlowQuery(config.splunk_observability)
    try:
        raw_df = query.run(program, start_ms, stop_ms, config.metric.group_by)
    finally:
        query.close()

    totals_df = summarize_totals(raw_df, config.metric.group_by)

    os.makedirs(config.report.output_dir, exist_ok=True)
    base_name = f"{config.report.title.lower().replace(' ', '_')}_{label}"

    if "xlsx" in config.report.formats:
        xlsx_path = os.path.join(config.report.output_dir, f"{base_name}.xlsx")
        export_excel(totals_df, xlsx_path, config.report.title, label)
        logger.info(f"Wrote {xlsx_path}")

    if "pdf" in config.report.formats:
        pdf_path = os.path.join(config.report.output_dir, f"{base_name}.pdf")
        export_pdf(totals_df, pdf_path, config.report.title, label)
        logger.info(f"Wrote {pdf_path}")


if __name__ == "__main__":
    main()
