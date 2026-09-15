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

**Status:** this tool was built by your Splunk account team to meet a specific reporting
need — a BMC-style historical "messages processed by queue" report — and is **not an
officially supported Splunk product feature**. Splunk Observability Cloud's own
dashboards are the supported way to view this data; this tool exists specifically to
produce a fixed, exportable total for a completed period, which dashboards don't provide
natively.

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
   data('ibm.mq.message.deq.count').sum(by=['ibm.mq.queue.manager', 'messaging.destination.name']).publish()
   ```
   - `data(...)` selects the raw metric (optionally with a `filter(...)` clause per
     `metric.filters` entry, e.g. to scope to specific queue managers).
   - `.delta()` is applied only if `metric.is_cumulative_counter: true` — the default
     metric is a GAUGE, not a counter (see caveat below), so it's skipped by default.
   - `.sum(by=[...])` collapses all time series sharing the same
     `ibm.mq.queue.manager`/`messaging.destination.name` dimensions into one series per
     group (in case a queue's metric is reported by multiple sources).

3. **Execute the query** — `SignalFlowQuery.run()` in the same file opens a
   `SignalFlowClient` (from
   [`signalflow-client-python`](https://github.com/signalfx/signalflow-client-python))
   against `https://stream.<realm>.signalfx.com`, calls `client.execute(program,
   start=start_ms, stop=stop_ms)`, and streams the result:
   - `MetadataMessage`s map each time series ID (`tsid`) to its dimensions (so we can
     recover `ibm.mq.queue.manager`/`messaging.destination.name` per series).
   - `DataMessage`s carry the actual `{tsid: value}` per-interval datapoints at each
     resolution interval.
   These are joined into a long-format `pandas.DataFrame`: one row per
   `(ibm.mq.queue.manager, messaging.destination.name, timestamp_ms, value)`.

4. **Aggregate** — `report_generator/report.py` turns that per-interval DataFrame into
   two views:
   - `clean_negative_deltas()` drops any datapoint with `value < 0` (a counter reset —
     see caveat below) once, up front, logging how many were dropped.
   - `summarize_totals()` produces the period-total table: `total_messages_processed`,
     `avg_per_interval` / `peak_interval_value` (straight from the per-interval values
     already fetched — no extra query needed), a `pct_of_total` share, and a bolded
     subtotal row per parent group (e.g. one row per queue manager summing its queues)
     when `group_by` has more than one dimension.
   - `summarize_trend()` produces a second table bucketed by `report.trend_granularity`
     (`hourly`/`daily`/`weekly`/`monthly`) — a trend across the window instead of one
     endpoint number, e.g. daily bars for a `--period month` report.

5. **Export** — `report_generator/exporters/excel_exporter.py` and `pdf_exporter.py`
   render the totals table (with a metadata header: period, metric name, realm,
   generation timestamp, inferred data resolution) plus the trend table as a second
   sheet (Excel) or page (PDF, landscape orientation so the wider table fits), written
   to `report.output_dir` as `<title>_<period-label>.xlsx`/`.pdf`. Column names are
   relabeled to friendlier headers (`report_generator/exporters/format_utils.py`) and
   numeric columns rounded for readability — the underlying totals/trend DataFrames
   used for the actual numbers are untouched.

`generate_report.py` wires these steps together in order: resolve period → build
program → run query → clean → summarize totals + trend → export.

### Report columns

| Column | Meaning |
|---|---|
| Queue Manager / Queue | `group_by` dimensions (`ibm.mq.queue.manager` / `messaging.destination.name`) |
| Total Messages | `total_messages_processed` — sum of all per-interval values across the whole period |
| Avg / Interval | mean per-interval value (label includes the inferred resolution, e.g. "~5 min") |
| Peak / Interval | max single per-interval value seen during the period |
| % of Total | this row's share of the grand total for the period |
| *(subtotal row)* | one bolded row per queue manager, summing that manager's queues |

The **Trend** sheet/page buckets the same data by `report.trend_granularity` instead of
collapsing it to one number — set this in `config.yaml` based on the period length, e.g.
`"daily"` for `--period month`, `"weekly"` for `--period quarter`, `"monthly"` for
`--period year` (keeps the trend table readable instead of ~365 daily rows).

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

## Recommended process for a full-year report

If you need a trailing 12 months of history (or any window longer than your org's
metric retention — see "Known limitations" below), **a single query today cannot
return a full year of real history** if your retention window is shorter than that —
check with your Splunk account team (or query `GET /v2/organization`'s `features`
list) to confirm your org's actual retention entitlement before planning around a
`--period year` report.

Recommended process:

1. **Confirm the retention window first**, so expectations are set accurately — a
   "last 12 months" report today can only cover whatever is still inside that window,
   not necessarily the full year.
2. **Start archiving monthly, going forward**: schedule `generate_report.py --period
   month` on a recurring monthly cron (see "Scheduling" above). A `--period
   quarter`/`--period year` report is just three/twelve of those monthly totals
   combined, so a single monthly cron job is enough — you don't need separate
   quarterly/yearly jobs. You can still run `--period quarter`/`--period year` on
   demand for whatever *is* still within your org's retention.
3. **Know what's actually being archived** — see "What gets archived" below. This is
   a computed summary, not a raw-data backup, which affects what you can and can't
   reconstruct from it later.
4. **Store the exported files outside this repository**: `reports/` is gitignored on
   purpose — generated `.xlsx`/`.pdf` files are report output, not source code, and
   shouldn't be committed here. Point the monthly cron job's output at wherever your
   organization already retains this kind of report today (shared drive, cloud
   storage bucket, ticketing system attachment), e.g. by writing to a dated subfolder
   and syncing it out as a step after `generate_report.py` runs.
5. After roughly 12 months of monthly archives have accumulated, a genuine
   trailing-12-month view becomes possible by combining those files. This is a real
   historical archive built forward from today — it cannot backfill data that has
   already aged out of the platform.

### What gets archived

Each monthly run produces a report file — not a copy of the raw underlying metric
data. Specifically:

- **Dimensions retained**: whichever fields `metric.group_by` is set to (by default:
  queue manager and queue name only — no host, queue type, or other attributes unless
  added to `group_by`).
- **Summary numbers retained**: total messages processed, average and peak per-interval
  values, percent of total, and a per-queue-manager subtotal — all computed for the
  full period at the time the report runs.
- **Trend numbers retained**: a rollup at whatever `report.trend_granularity` is set to
  (daily/weekly/monthly) — e.g. one row per day per queue, not one row per raw
  measurement interval.
- **Not retained, at all**: the individual raw per-interval datapoints/timestamps
  behind those numbers, or any SignalFlow-internal identifiers.

In practice, this means the archive is a **computed summary snapshot**, not a
full-fidelity backup. Once the underlying data ages out of your org's retention
window, you cannot go back and regenerate a report at finer granularity than whatever
the Trend table captured at the time — e.g. if it archived daily totals, hourly totals
for that month can never be reconstructed afterward.

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
own List/table rollup option in the O11y UI. If you need an exact, export-ready number
(e.g. for a report you forward outside the platform), that's still
`generate_report.py`; if you just want to explore trends interactively, the dashboard
is the lighter-weight option. Both use the same underlying SignalFlow program, so
whichever direction you choose later doesn't require re-deriving the metric math.

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
the count gets split between whichever tool reads it first each interval — confirm
within your organization that this collector is the only thing resetting these stats
on z/OS before relying on these totals.

Either way, **validate totals against a known-stable period before treating these
numbers as authoritative**, and flag this limitation if sharing the numbers outside
your team.

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
- **SignalFlow queries can stall if the window's end time is too close to real time**
  (confirmed by testing — a window ending 5 minutes ago repeatedly stalled, the same
  query with an end time 1 hour in the past returned in under a second). This does
  **not** affect normal use of `generate_report.py`: `resolve_period()` always
  computes the reporting window as a *complete* past calendar period, which is
  inherently well clear of real time. It only matters if you write a custom query
  against a very recent time window directly.
