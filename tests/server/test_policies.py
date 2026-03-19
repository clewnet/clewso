"""Tests for policy CRUD endpoints."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from clew.server.dependencies import get_graph_store
from clew.server.main import app


@pytest.fixture
def mock_graph_store():
    store = AsyncMock()
    store.get_policies = AsyncMock(return_value=[])
    store.create_policy = AsyncMock(return_value="test-policy")
    store.delete_policy = AsyncMock(return_value=True)
    return store


@pytest.fixture
def client(mock_graph_store):
    app.dependency_overrides[get_graph_store] = lambda: mock_graph_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_policy(client, mock_graph_store):
    payload = {
        "id": "no-subprocess",
        "type": "banned_import",
        "pattern": "subprocess",
        "severity": "block",
        "message": "Do not use subprocess directly",
    }
    response = client.post("/v1/policies", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] == "no-subprocess"
    assert data["type"] == "banned_import"
    assert data["severity"] == "block"
    mock_graph_store.create_policy.assert_called_once()


def test_create_policy_with_precept_id(client, mock_graph_store):
    payload = {
        "id": "protect-auth",
        "type": "protected_write",
        "pattern": "src/auth/*",
        "severity": "warn",
        "message": "Auth changes need review",
        "precept_id": "precept-auth-guard",
    }
    response = client.post("/v1/policies", json=payload)
    assert response.status_code == 201
    assert response.json()["precept_id"] == "precept-auth-guard"


def test_create_policy_validation_rejects_invalid_type(client):
    payload = {
        "id": "bad",
        "type": "invalid_type",
        "pattern": "foo",
        "severity": "block",
        "message": "test",
    }
    response = client.post("/v1/policies", json=payload)
    assert response.status_code == 422


def test_create_policy_validation_rejects_invalid_severity(client):
    payload = {
        "id": "bad",
        "type": "banned_import",
        "pattern": "foo",
        "severity": "critical",
        "message": "test",
    }
    response = client.post("/v1/policies", json=payload)
    assert response.status_code == 422


def test_list_policies_empty(client, mock_graph_store):
    response = client.get("/v1/policies")
    assert response.status_code == 200
    data = response.json()
    assert data["policies"] == []


def test_list_policies_returns_all(client, mock_graph_store):
    mock_graph_store.get_policies.return_value = [
        {
            "id": "no-subprocess",
            "type": "banned_import",
            "pattern": "subprocess",
            "severity": "block",
            "message": "No subprocess",
            "precept_id": None,
        },
        {
            "id": "protect-auth",
            "type": "protected_write",
            "pattern": "src/auth/*",
            "severity": "warn",
            "message": "Auth changes need review",
            "precept_id": None,
        },
    ]
    response = client.get("/v1/policies")
    assert response.status_code == 200
    data = response.json()
    assert len(data["policies"]) == 2
    assert data["policies"][0]["id"] == "no-subprocess"
    assert data["policies"][1]["id"] == "protect-auth"


def test_delete_policy(client, mock_graph_store):
    response = client.delete("/v1/policies/no-subprocess")
    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] is True
    assert data["id"] == "no-subprocess"
    mock_graph_store.delete_policy.assert_called_once_with("no-subprocess")


def test_delete_policy_not_found(client, mock_graph_store):
    mock_graph_store.delete_policy.return_value = False
    response = client.delete("/v1/policies/nonexistent")
    assert response.status_code == 404


def test_export_policies_empty(client, mock_graph_store):
    response = client.get("/v1/policies/export")
    assert response.status_code == 200
    assert response.json() == []


def test_export_policies_returns_flat_array(client, mock_graph_store):
    mock_graph_store.get_policies.return_value = [
        {
            "id": "no-subprocess",
            "type": "banned_import",
            "pattern": "subprocess",
            "severity": "block",
            "message": "No subprocess",
            "precept_id": None,
        },
    ]
    response = client.get("/v1/policies/export")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == "no-subprocess"
