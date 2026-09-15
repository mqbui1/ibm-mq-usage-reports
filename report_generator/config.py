import os
import re
from dataclasses import dataclass, field
from typing import Dict, List

import yaml


def _resolve_env_vars(value):
    """Replace ${VAR_NAME} patterns with environment variable values."""
    if isinstance(value, str):
        return re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), value)
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(i) for i in value]
    return value


@dataclass
class SplunkObservabilityConfig:
    realm: str
    api_token: str

    @property
    def stream_endpoint(self) -> str:
        return f"https://stream.{self.realm}.signalfx.com"


@dataclass
class MetricConfig:
    name: str
    group_by: List[str] = field(default_factory=list)
    filters: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class ReportConfig:
    output_dir: str = "./reports"
    formats: List[str] = field(default_factory=lambda: ["xlsx", "pdf"])
    title: str = "IBM MQ Message Throughput Report"


@dataclass
class Config:
    splunk_observability: SplunkObservabilityConfig
    metric: MetricConfig
    report: ReportConfig


def load_config(path: str = "config.yaml") -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)

    raw = _resolve_env_vars(raw)
    sfx_raw = raw["splunk_observability"]
    metric_raw = raw.get("metric", {})
    report_raw = raw.get("report", {})

    splunk_observability = SplunkObservabilityConfig(
        realm=sfx_raw["realm"],
        api_token=os.environ.get("SFX_API_TOKEN", sfx_raw.get("api_token", "")),
    )

    metric = MetricConfig(
        name=metric_raw["name"],
        group_by=metric_raw.get("group_by", []),
        filters=metric_raw.get("filters", {}),
    )

    report = ReportConfig(
        output_dir=report_raw.get("output_dir", "./reports"),
        formats=report_raw.get("formats", ["xlsx", "pdf"]),
        title=report_raw.get("title", "IBM MQ Message Throughput Report"),
    )

    return Config(
        splunk_observability=splunk_observability,
        metric=metric,
        report=report,
    )
