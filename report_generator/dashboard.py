import logging

import requests

from .config import DashboardConfig, SplunkObservabilityConfig

logger = logging.getLogger(__name__)


def _headers(sfx_config: SplunkObservabilityConfig) -> dict:
    return {"X-SF-TOKEN": sfx_config.api_token, "Content-Type": "application/json"}


def _find_group_id(sfx_config: SplunkObservabilityConfig, group_name: str):
    """Returns the id of an existing dashboard group with this name, or None."""
    resp = requests.get(
        f"{sfx_config.api_endpoint}/v2/dashboardgroup",
        headers=_headers(sfx_config),
        params={"name": group_name},
    )
    resp.raise_for_status()
    for group in resp.json().get("results", []):
        if group.get("name") == group_name:
            return group["id"]
    return None


def _create_group(sfx_config: SplunkObservabilityConfig, group_name: str) -> str:
    resp = requests.post(
        f"{sfx_config.api_endpoint}/v2/dashboardgroup",
        headers=_headers(sfx_config),
        json={"name": group_name},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _create_chart(sfx_config: SplunkObservabilityConfig, chart_name: str, program_text: str) -> str:
    resp = requests.post(
        f"{sfx_config.api_endpoint}/v2/chart",
        headers=_headers(sfx_config),
        json={
            "name": chart_name,
            "programText": program_text,
            "options": {
                "type": "TimeSeriesChart",
                "defaultPlotType": "ColumnChart",
                "time": {"type": "relative", "range": 2592000000},  # 30d default; use the dashboard time picker to change
            },
        },
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _create_dashboard(sfx_config: SplunkObservabilityConfig, dashboard_name: str, group_id: str, chart_id: str) -> dict:
    resp = requests.post(
        f"{sfx_config.api_endpoint}/v2/dashboard",
        headers=_headers(sfx_config),
        json={
            "name": dashboard_name,
            "groupId": group_id,
            "charts": [{"chartId": chart_id, "row": 0, "column": 0, "width": 12, "height": 4}],
        },
    )
    resp.raise_for_status()
    return resp.json()


def create_dashboard(sfx_config: SplunkObservabilityConfig, dashboard_config: DashboardConfig, program_text: str) -> str:
    """
    Creates (or reuses) a dashboard group, a single chart running `program_text`,
    and a dashboard containing that chart. Returns the dashboard's URL.

    Note: this chart shows a live trend (per-interval deltas or raw values,
    depending on build_program()'s is_cumulative_counter branch), not a fixed
    "total for the period" number — use the dashboard's built-in time-range
    picker (top right) to zoom to a month/quarter/year and read totals off the
    chart's legend/hover, or via the chart's own List/table rollup option in
    the UI. For a hard exportable total number, use generate_report.py instead.
    """
    group_id = _find_group_id(sfx_config, dashboard_config.group_name)
    if group_id is None:
        group_id = _create_group(sfx_config, dashboard_config.group_name)
        logger.info(f"Created dashboard group {dashboard_config.group_name!r} ({group_id})")
    else:
        logger.info(f"Reusing existing dashboard group {dashboard_config.group_name!r} ({group_id})")

    chart_id = _create_chart(sfx_config, dashboard_config.chart_name, program_text)
    logger.info(f"Created chart {dashboard_config.chart_name!r} ({chart_id})")

    dashboard = _create_dashboard(sfx_config, dashboard_config.dashboard_name, group_id, chart_id)
    url = f"https://app.{sfx_config.realm}.signalfx.com/#/dashboard/{dashboard['id']}"
    logger.info(f"Created dashboard {dashboard_config.dashboard_name!r}: {url}")
    return url
