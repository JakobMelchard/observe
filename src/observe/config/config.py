import tomllib
from dataclasses import dataclass
from pathlib import Path

CANDIDATES = ("observe.toml", "pyproject.toml")

#: ``(toml section, key) -> ObserveConfig attribute``
FIELDS = {
    ("collector", "endpoint"): "endpoint",
    ("collector", "max_body_bytes"): "max_body_bytes",
    ("collector", "same_site"): "same_site",
    ("collector", "feedback_per_minute"): "feedback_per_minute",
    ("collector", "otlp_per_minute"): "otlp_per_minute",
    ("frontend", "feedback_label"): "feedback_label",
    ("frontend", "enrich_hook"): "enrich_hook",
    ("frontend", "register_sw"): "register_sw",
    ("frontend", "button"): "button",
}


@dataclass
class ObserveConfig:
    endpoint: str = "/__observe__/otlp"
    #: Limits on the POST endpoints. 0 lifts a limit.
    max_body_bytes: int = 1_048_576
    #: Refuse POSTs a browser marks as coming from another site.
    same_site: bool = True
    #: Accepted POSTs per client address, counted per process.
    feedback_per_minute: int = 10
    otlp_per_minute: int = 300
    feedback_label: str = "Feedback"
    enrich_hook: str = "__observe_enrich__"
    register_sw: bool = True
    #: Render the floating trigger. A site with its own button calls window.__observe__.open().
    button: bool = True


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
