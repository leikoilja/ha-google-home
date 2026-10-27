"""Fixtures shared by the tests."""

from collections.abc import Iterator
from unittest.mock import Mock, patch

import pytest


@pytest.fixture(name="clock")
def fixture_clock() -> Iterator[Mock]:
    """Set the time the client reads, in seconds since setup fetched Google's list."""
    with patch(
        "custom_components.google_home.api.monotonic", return_value=0.0
    ) as monotonic:
        yield monotonic
