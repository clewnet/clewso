"""Shared fixtures for bench tests."""

import pytest
import respx


@pytest.fixture()
def respx_mock():
    """Provide a respx mock router for HTTP request mocking."""
    with respx.mock(assert_all_called=False) as router:
        yield router
