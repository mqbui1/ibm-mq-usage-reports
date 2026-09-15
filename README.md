# IBM MQ Usage Report Generator

Pulls historical message-throughput data out of Splunk Observability Cloud and offers
two ways to view it, filling the gap that Splunk O11y has no native scheduled/exportable
report feature (it's dashboard-based):

1. **Scheduled report** (`generate_report.py`) — queries the **SignalFlow API** and
   generates Excel/PDF reports (per queue manager/queue) for a completed month, quarter,
   or year, with a fixed exportable total number for that period.
2. **Dashboard** (`create_dashboard.py`) — creates a Splunk O11y dashboard with a chart
   of the same metric, so the numbers can be explored self-serve using O11y's own
   time-range picker instead of a generated file. See "Dashboard option" below for what
   this can and can't show.

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

## Dashboard option

```bash
export SFX_API_TOKEN=<your-api-token>
python create_dashboard.py --config my-config.yaml
```

Creates a dashboard group (`dashboard.group_name`), a `TimeSeriesChart` running the same
SignalFlow program `generate_report.py` uses (`report_generator/dashboard.py` + the
Splunk O11y REST API: `POST /v2/dashboardgroup`, `/v2/chart`, `/v2/dashboard`), and a
dashboard (`dashboard.dashboard_name`) containing that chart. Prints the dashboard URL.
Re-running reuses the existing group by name rather than duplicating it.

**What this gives you vs. the script:** the dashboard shows a live *trend* (a bar per
interval, per queue manager/queue) that you can zoom with O11y's own time-range picker
(top right of the dashboard) to a rough month/quarter/year view — no code to run, no
file to generate. What it does **not** give you is a single hard "total messages
processed" number for an exact calendar period the way `generate_report.py` does —
reading a period total off a chart means summing bars visually, or using the chart's
own List/table rollup option in the O11y UI. If the customer needs an exact,
export-ready number (e.g. for a report they forward outside the platform), that's still
`generate_report.py`; if they just want to explore trends interactively, the dashboard
is the lighter-weight option. Both use the same underlying SignalFlow program, so
whichever direction is decided later doesn't require re-deriving the metric math.

## Metric type caveat: `ibm.mq.message.deq.count` is a GAUGE, not a counter

Confirmed against the OTel receiver's source
([`ibm-mq-metrics`](https://github.com/open-telemetry/opentelemetry-java-contrib/tree/main/ibm-mq-metrics)
in `open-telemetry/opentelemetry-java-contrib`):

- [`docs/metrics.md`](https://github.com/open-telemetry/opentelemetry-java-contrib/blob/main/ibm-mq-metrics/docs/metrics.md)
  documents `ibm.mq.message.deq.count` as Instrument Type **Gauge**, with attributes
  `ibm.mq.queue.manager` / `ibm.mq.queue.type` / `messaging.destination.name` — not
  `mq.qmgr`/`mq.queue`. Splunk O11y's Metric Finder shows the same (Type: GAUGE,
  Default rollup: AVERAGE_ROLLUP), consistent with this.
- [`ResetQStatsCmdCollector.java`](https://github.com/open-telemetry/opentelemetry-java-contrib/blob/main/ibm-mq-metrics/src/main/java/io/opentelemetry/ibm/mq/metricscollector/ResetQStatsCmdCollector.java)
  shows the receiver populates this value by issuing IBM MQ's **`RESET QSTATS`** PCF
  command (`MQCMD_RESET_Q_STATS`) and reading `MQIA_MSG_DEQ_COUNT` off the response.
  `RESET QSTATS` **zeroes the counter every time it's read** — so each datapoint is
  already "messages dequeued since the last reset" (a per-interval delta), not a
  running cumulative total since queue manager start. This is why it's typed Gauge and
  not Counter: applying `.delta()` on top of an already-per-interval value would
  compute the difference between consecutive interval counts (not the count itself)
  and badly undercount.

Because of this, `config.yaml` defaults to `metric.is_cumulative_counter: false` and
`build_program()` sums the raw gauge values directly (no `.delta()`). If you're on a
different/older collector version and Metric Finder shows this metric's Type as
**COUNTER** instead, set `is_cumulative_counter: true` — `build_program()` will then
apply `.delta()` before summing, and `summarize_totals()` drops negative deltas (logged
as a warning) to guard against counter resets from a collector/queue-manager restart,
at the cost of undercounting across any reset during the window.

**Operational risk specific to `RESET QSTATS`:** it resets a queue-level counter that
is shared across *any* client that queries it, not just this collector. If another
monitoring tool (BMC, a second OTel collector instance, manual MQSC) also issues
`RESET QSTATS`/`MQSC RESET QSTATS` against the same queue on the same queue manager,
the count gets split between whichever tool reads it first each interval — worth
confirming with the customer that this collector is the only thing resetting these
stats on z/OS.

Either way, **validate totals against a known-stable period before treating these
numbers as authoritative**, and flag this limitation if presenting the numbers
externally.

## Known limitations

- **Metric retention is a hard, plan-based ceiling — confirmed, not hypothetical.**
  Querying `GET /v2/organization` on a Splunk O11y org returns a `features` list
  including retention entitlement flags like `retentionHighRes96d` — a 96-day
  (~3.2 month) high-resolution retention cap on the org this was tested against.
  **This tool cannot report on history the platform never retained** — check the
  target org's actual retention entitlement (same API call, or ask the account
  team) before promising a `--period year` (or even `quarter`) report will return
  real data. If retention is shorter than the requested window, the fix is to start
  running this tool on a recurring schedule now to build an external archive
  going forward — it cannot backfill data that already aged out of the platform.
- Requires MQ queue statistics enabled on the queue manager (same requirement as BMC).
- `metric.group_by` dimension names in `config.yaml` (`ibm.mq.queue.manager` /
  `messaging.destination.name`) are per the current `open-telemetry/opentelemetry-java-contrib`
  ibm-mq-metrics receiver — confirm they match what's actually flowing into your org
  via Metric Finder before relying on the per-queue-manager/queue breakdown (older
  collector versions or custom pipelines may use different names); mismatches group
  rows under `"unknown"`.
- The dashboard chart's default time range (30 days) and layout are minimal — treat
  `create_dashboard.py`'s output as a starting point to adjust in the O11y UI, not a
  finished/curated dashboard.
- **SignalFlow historical jobs can hang if `stop` is too close to real time.** If a
  query's `stop_ms` lands within the last few minutes, the backend may not have fully
  materialized/finalized that window yet, and `computation.stream()` never emits
  completion — it just stalls indefinitely (confirmed by testing: identical query with
  `stop` 1 hour in the past returned in <1s; with `stop` 5 minutes in the past, it
  stalled every time regardless of resolution or `.sum(by=[...])` grouping). This does
  **not** affect `generate_report.py` — `periods.py:resolve_period()` always computes
  `stop` as the start of the *current* calendar period, which is inherently well in the
  past. It only bit an ad-hoc validation script that queried up to "now minus 5
  minutes." Worth knowing if you ever query near-real-time windows directly.
