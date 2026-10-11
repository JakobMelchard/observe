"""The root package and both sinks are released as one version."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
PACKAGES = [ROOT / "pyproject.toml", *sorted(ROOT.glob("sinks/*/pyproject.toml"))]


def version(path):
    return tomllib.loads(path.read_text())["project"]["version"]


def test_every_package_has_the_manifest_version():
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())["."]
    assert {p.parent.name: version(p) for p in PACKAGES} == {
        p.parent.name: manifest for p in PACKAGES
    }


def test_release_please_bumps_every_sink():
    pkg = json.loads((ROOT / "release-please-config.json").read_text())["packages"]["."]
    assert pkg["release-type"] == "python"
    bumped = {e["path"] for e in pkg["extra-files"] if e["jsonpath"] == "$.project.version"}
    assert bumped == {str(p.relative_to(ROOT)) for p in PACKAGES[1:]}
