"""
Policy CRUD endpoints for Clew Engine.

Manages PolicyRule nodes in the graph database. Policies define
enforceable rules (banned_import, protected_write, unguarded_path)
that are checked during dry-run reviews and hook evaluations.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from clewso_core.schema import PolicyRule
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from clew.server.adapters import GraphStore
from clew.server.dependencies import get_graph_store

router = APIRouter()
logger = logging.getLogger("clew.routes.policies")

T = TypeVar("T")


async def _handle_store_op(operation: str, fn: Callable[[], Awaitable[T]]) -> T:
    """Execute a graph-store operation with uniform error handling."""
    try:
        return await fn()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to {operation}: {e}")
        raise HTTPException(status_code=503, detail=f"Failed to {operation}") from e


class PolicyResponse(BaseModel):
    id: str
    type: str
    pattern: str
    severity: str
    message: str
    precept_id: str | None = None


class PolicyListResponse(BaseModel):
    policies: list[PolicyResponse]


def _policy_responses(policies: list[dict]) -> list["PolicyResponse"]:
    """Convert raw policy dicts to response models."""
    return [PolicyResponse(**p) for p in policies]


@router.post("", response_model=PolicyResponse, status_code=201)
async def create_policy(
    policy: PolicyRule,
    graph_store: GraphStore = Depends(get_graph_store),
):
    """Create or update a policy rule."""

    async def _create():
        policy_dict = policy.model_dump()
        await graph_store.create_policy(policy_dict)
        return PolicyResponse(**policy_dict)

    return await _handle_store_op("create policy", _create)


@router.get("", response_model=PolicyListResponse)
async def list_policies(
    graph_store: GraphStore = Depends(get_graph_store),
):
    """List all active policy rules."""

    async def _list():
        return PolicyListResponse(policies=_policy_responses(await graph_store.get_policies()))

    return await _handle_store_op("list policies", _list)


@router.get("/export", response_model=list[PolicyResponse])
async def export_policies(
    graph_store: GraphStore = Depends(get_graph_store),
):
    """Export all active policies as a flat JSON array.

    Consumed by SessionStart hooks to write a local policy cache file.
    """

    async def _export():
        return _policy_responses(await graph_store.get_policies())

    return await _handle_store_op("export policies", _export)


@router.delete("/{policy_id}")
async def delete_policy(
    policy_id: str,
    graph_store: GraphStore = Depends(get_graph_store),
):
    """Delete a policy rule by ID."""

    async def _delete():
        deleted = await graph_store.delete_policy(policy_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found")
        return {"deleted": True, "id": policy_id}

    return await _handle_store_op("delete policy", _delete)
