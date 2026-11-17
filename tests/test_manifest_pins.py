"""Test that the manifest requires the library versions the tests ran against."""

from importlib.metadata import version as package_version
import json
from pathlib import Path

from packaging.requirements import Requirement
import pytest

MANIFEST = Path(__file__).parents[1] / "custom_components/google_home/manifest.json"


@pytest.mark.parametrize("package", ["ghome-local-api", "glocaltokens"])
def test_manifest_pins_installed_library(package: str) -> None:
    """Installing master gets the library version that uv.lock gave these tests."""
    requirements = [
        Requirement(requirement)
        for requirement in json.loads(MANIFEST.read_text())["requirements"]
    ]
    pins = [str(r.specifier) for r in requirements if r.name == package]

    assert pins == [f"=={package_version(package)}"]
