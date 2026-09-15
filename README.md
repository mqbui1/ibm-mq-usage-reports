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

The pipeline is five steps, each in its own module:

1. **Resolve the reporting window** — `report_generator/periods.py:resolve_period()`
   takes `--period` (`month`/`quarter`/`year`) and an optional `--reference-date`
   (defaults to today) and computes the *previous complete* calendar period relative
   to that date, e.g. `--period month` run any day in October returns all of September
   (`2026-09-01T00:00:00Z` – `2026-10-01T00:00:00Z`). Returns `(start_ms, stop_ms, label)`
   as epoch-millisecond bounds plus a human label (`"2026-09"`, `"2026-Q3"`, `"2026"`)
   used in filenames/report titles.

2. **Build the SignalFlow program** — `report_generator/signalflow_query.py:build_program()`
   reads `metric.name`, `metric.group_by`, and `metric.filters` from the config and
   generates a program string, e.g. for the default config:
   ```
   data('ibm.mq.message.deq.count').delta().sum(by=['mq.qmgr', 'mq.queue']).publish()
   ```
   - `data(...)` selects the raw metric (optionally with a `filter(...)` clause per
     `metric.filters` entry, e.g. to scope to specific queue managers).
   - `.delta()` converts the cumulative counter into per-interval deltas (the count of
     messages dequeued *since the previous datapoint*, not the running total).
   - `.sum(by=[...])` collapses all time series sharing the same `mq.qmgr`/`mq.queue`
     dimensions into one series per group (in case a queue's metric is reported by
     multiple sources).

3. **Execute the query** — `SignalFlowQuery.run()` in the same file opens a
   `SignalFlowClient` (from
   [`signalflow-client-python`](https://github.com/signalfx/signalflow-client-python))
   against `https://stream.<realm>.signalfx.com`, calls `client.execute(program,
   start=start_ms, stop=stop_ms)`, and streams the result:
   - `MetadataMessage`s map each time series ID (`tsid`) to its dimensions (so we can
     recover `mq.qmgr`/`mq.queue` per series).
   - `DataMessage`s carry the actual `{tsid: value}` delta datapoints at each
     resolution interval.
   These are joined into a long-format `pandas.DataFrame`: one row per
   `(mq.qmgr, mq.queue, timestamp_ms, value)`.

4. **Aggregate into totals** — `report_generator/report.py:summarize_totals()` sums
   the `value` column per `group_by` group across the whole window to get
   "total messages processed in this period" per queue manager/queue. Any datapoint
   with `value < 0` (a counter reset — see caveat below) is dropped before summing and
   the count of dropped points is logged as a warning. Result is a small DataFrame:
   `mq.qmgr | mq.queue | total_messages_processed`, sorted descending.

5. **Export** — `report_generator/exporters/excel_exporter.py` and `pdf_exporter.py`
   render that totals DataFrame as a titled table to `.xlsx` (via `openpyxl`) and/or
   `.pdf` (via `reportlab`), written to `report.output_dir` as
   `<title>_<period-label>.xlsx`/`.pdf`.

`generate_report.py` wires these five steps together in order: resolve period → build
program → run query → summarize → export.

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
