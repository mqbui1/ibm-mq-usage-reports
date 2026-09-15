# IBM MQ Usage Report Generator

Pulls historical message-throughput data out of Splunk Observability Cloud via the
**SignalFlow API** and generates Excel/PDF reports (per queue manager/queue) for a
completed month, quarter, or year — filling the gap that Splunk O11y has no native
scheduled/exportable report feature (it's dashboard-based).

**Status: field-built, account-specific tool — not an officially supported Splunk/Cisco
integration.** Built to answer a specific TIAA ask (BMC-style historical "messages
processed by queue" reporting) after confirming with product (Antoine) that Splunk O11y
doesn't have a native reporting feature equivalent to BMC's.

## How it works

1. Queries the cumulative counter metric `ibm.mq.message.deq.count` (per Antoine —
   requires MQ **queue statistics** to be enabled; same prerequisite BMC has) using the
   [`signalflow-client-python`](https://github.com/signalfx/signalflow-client-python)
   library.
2. Converts the raw cumulative counter into per-interval deltas (`.delta()`), grouped by
   `mq.qmgr`/`mq.queue`, then sums the deltas over the full reporting window to get
   "total messages processed in this period."
3. Exports the result as `.xlsx` and/or `.pdf`.

## Setup

```bash
pip install -r requirements.txt
cp config.yaml my-config.yaml
# Edit my-config.yaml: realm, metric filters, output settings
```

## Running

```bash
export SFX_API_TOKEN=<your-api-token>

# Report for the previous complete calendar month
python generate_report.py --period month --config my-config.yaml

# Previous complete quarter / year
python generate_report.py --period quarter --config my-config.yaml
python generate_report.py --period year --config my-config.yaml

# Anchor the "previous complete period" calculation to a specific date (for backfilling)
python generate_report.py --period month --reference-date 2026-09-01 --config my-config.yaml
```

Reports are written to `report.output_dir` (default `./reports/`) as
`<title>_<period-label>.xlsx` / `.pdf`.

## Scheduling

Run as a monthly/quarterly cron job to build up a report archive, e.g.:

```cron
# Run on the 2nd of each month, generating last month's report
0 6 2 * * cd /path/to/ibm-mq-usage-reports && SFX_API_TOKEN=... python generate_report.py --period month >> /var/log/mq-report.log 2>&1
```

## Important caveat: counter resets

`ibm.mq.message.deq.count` is a monotonically increasing counter. If the collector or
queue manager restarts during the reporting window, the counter resets and `.delta()`
will emit a large negative value at that point. This tool **drops negative deltas**
rather than summing them (logged as a warning), which avoids an incorrect deep-negative
total but means the true count is undercounted across any reset that occurred during
the window. Validate totals against a known-stable period before treating these numbers
as authoritative, and flag this limitation if presenting the numbers externally.

## Known limitations

- No historical backfill guarantee beyond whatever Splunk O11y's metric retention
  covers for your org's plan — verify this before promising a full year of history.
- Requires MQ queue statistics enabled on the queue manager (same requirement as BMC).
- SignalFlow query is fixed at delta+sum; if a non-counter (gauge) metric is configured
  instead, `build_program()` in `report_generator/signalflow_query.py` will produce a
  nonsensical result — this tool is built specifically for cumulative counter metrics.
