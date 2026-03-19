"""
Tests for the /health endpoint.
"""

import pytest


@pytest.mark.asyncio
async def test_health_returns_ok(client):
    """Health check returns status ok with version."""
    resp = await client.get("/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
