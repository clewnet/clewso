"""
Policy CRUD endpoints for Clew Engine.

Manages PolicyRule nodes in the graph database. Policies define
enforceable rules (banned_import, protected_write, unguarded_path)
that are checked during dry-run reviews and hook evaluations.
"""

import logging

from clewso_core.schema import PolicyRule
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from clew.server.adapters import GraphStore
from clew.server.dependencies import get_graph_store

router = APIRouter()
logger = logging.getLogger("clew.routes.policies")


class PolicyResponse(BaseModel):
    id: str
    type: str
    pattern: str
    severity: str
    message: str
    precept_id: str | None = None


class PolicyListResponse(BaseModel):
    policies: list[PolicyResponse]


@router.post("", response_model=PolicyResponse, status_code=201)
async def create_policy(
    policy: PolicyRule,
    graph_store: GraphStore = Depends(get_graph_store),
):
    """Create or update a policy rule."""
    try:
        policy_dict = policy.model_dump()
        await graph_store.create_policy(policy_dict)
        return PolicyResponse(**policy_dict)
    except Exception as e:
        logger.error(f"Failed to create policy: {e}")
        raise HTTPException(status_code=503, detail="Failed to create policy") from e


@router.get("", response_model=PolicyListResponse)
async def list_policies(
    graph_store: GraphStore = Depends(get_graph_store),
):
    """List all active policy rules."""
    try:
        policies = await graph_store.get_policies()
        return PolicyListResponse(
            policies=[PolicyResponse(**p) for p in policies],
        )
    except Exception as e:
        logger.error(f"Failed to list policies: {e}")
        raise HTTPException(status_code=503, detail="Failed to list policies") from e


@router.get("/export", response_model=list[PolicyResponse])
async def export_policies(
    graph_store: GraphStore = Depends(get_graph_store),
):
    """Export all active policies as a flat JSON array.

    Consumed by SessionStart hooks to write a local policy cache file.
    """
    try:
        policies = await graph_store.get_policies()
        return [PolicyResponse(**p) for p in policies]
    except Exception as e:
        logger.error(f"Failed to export policies: {e}")
        raise HTTPException(status_code=503, detail="Failed to export policies") from e


@router.delete("/{policy_id}")
async def delete_policy(
    policy_id: str,
    graph_store: GraphStore = Depends(get_graph_store),
):
    """Delete a policy rule by ID."""
    try:
        deleted = await graph_store.delete_policy(policy_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found")
        return {"deleted": True, "id": policy_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete policy: {e}")
        raise HTTPException(status_code=503, detail="Failed to delete policy") from e
