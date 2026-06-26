from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Profile = Literal["full", "relay", "buffer"]


@dataclass
class ObserveConfig:
    profile: Profile = "relay"
    endpoint: str = "/__observe__/otlp"
    feedback_label: str = "Feedback"
    enrich_hook: str = "__observe_enrich__"
    register_sw: bool = True
    otelcol_config_out: str | None = None


def load_config(path: str | Path | None = None) -> ObserveConfig:
    import tomllib

    cfg = ObserveConfig()
    if path is None:
        for candidate in (Path.cwd() / "observe.toml", Path.cwd() / "pyproject.toml"):
            if candidate.exists():
                path = candidate
                break
        else:
            return cfg

    raw = tomllib.loads(Path(path).read_text())
    if "observe" in raw:
        section = raw["observe"]
        if "profile" in section:
            cfg.profile = section["profile"]
    if "collector" in raw:
        if "endpoint" in raw["collector"]:
            cfg.endpoint = raw["collector"]["endpoint"]
    if "frontend" in raw:
        front = raw["frontend"]
        if "feedback_label" in front:
            cfg.feedback_label = front["feedback_label"]
        if "enrich_hook" in front:
            cfg.enrich_hook = front["enrich_hook"]
        if "register_sw" in front:
            cfg.register_sw = front["register_sw"]
    if "otelcol" in raw:
        if "config_out" in raw["otelcol"]:
            cfg.otelcol_config_out = raw["otelcol"]["config_out"]

    return cfg
