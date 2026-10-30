"""The root package and both sinks are released as one version."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
PACKAGES = [ROOT / "pyproject.toml", *sorted(ROOT.glob("sinks/*/pyproject.toml"))]


def version(path: Path) -> str:
    v: str = tomllib.loads(path.read_text())["project"]["version"]
    return v


def test_every_package_has_the_manifest_version() -> None:
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())["."]
    assert {p.parent.name: version(p) for p in PACKAGES} == {
        p.parent.name: manifest for p in PACKAGES
    }


def test_release_please_bumps_every_sink() -> None:
    pkg = json.loads((ROOT / "release-please-config.json").read_text())["packages"]["."]
    assert pkg["release-type"] == "python"
    bumped = {e["path"] for e in pkg["extra-files"] if e.get("jsonpath") == "$.project.version"}
    assert bumped == {str(p.relative_to(ROOT)) for p in PACKAGES[1:]}
    assert {e["path"] for e in pkg["extra-files"]} >= {"uv.lock", "README.md"}


def test_lock_and_readme_have_the_manifest_version() -> None:
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())["."]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert [p["version"] for p in lock["package"] if p["name"] == "observe"] == [manifest]
    readme = (ROOT / "README.md").read_text()
    assert readme.count(f'tag = "v{manifest}"') == len(PACKAGES)
