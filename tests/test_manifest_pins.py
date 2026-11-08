"""Test that the manifest requires the local API library the tests ran against."""

from importlib.metadata import version as package_version
import json
from pathlib import Path

from packaging.requirements import Requirement

MANIFEST = Path(__file__).parents[1] / "custom_components/google_home/manifest.json"


def test_manifest_pins_installed_local_api_library() -> None:
    """Installing master gets the library version that uv.lock gave these tests."""
    requirements = [
        Requirement(requirement)
        for requirement in json.loads(MANIFEST.read_text())["requirements"]
    ]
    pins = [str(r.specifier) for r in requirements if r.name == "ghome-local-api"]

    assert pins == [f"=={package_version('ghome-local-api')}"]
