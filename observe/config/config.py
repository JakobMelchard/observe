import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Profile = Literal["full", "relay", "buffer"]

CANDIDATES = ("observe.toml", "pyproject.toml")

#: ``(toml section, key) -> ObserveConfig attribute``
FIELDS = {
    ("observe", "profile"): "profile",
    ("collector", "endpoint"): "endpoint",
    ("frontend", "feedback_label"): "feedback_label",
    ("frontend", "enrich_hook"): "enrich_hook",
    ("frontend", "register_sw"): "register_sw",
    ("otelcol", "config_out"): "otelcol_config_out",
}


@dataclass
class ObserveConfig:
    profile: Profile = "relay"
    endpoint: str = "/__observe__/otlp"
    feedback_label: str = "Feedback"
    enrich_hook: str = "__observe_enrich__"
    register_sw: bool = True
    otelcol_config_out: str | None = None


def load_config(path: str | Path | None = None) -> ObserveConfig:
    """Load config from a TOML file, or from the first candidate found in cwd."""
    cfg = ObserveConfig()
    found = Path(path) if path is not None else _discover()
    if found is None:
        return cfg

    raw = tomllib.loads(found.read_text())
    for (section, key), field in FIELDS.items():
        values = raw.get(section, {})
        if key in values:
            setattr(cfg, field, values[key])
    return cfg


def _discover() -> Path | None:
    return next((p for name in CANDIDATES if (p := Path.cwd() / name).exists()), None)
