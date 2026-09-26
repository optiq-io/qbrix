from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from fastapi import Query
from fastapi import status
from pydantic import BaseModel

from qbrixcore.policy import POLICIES
from qbrixcore.policy import RewardType

router = APIRouter(prefix="/policies", tags=["policies"])


class PolicyParamResponse(BaseModel):
    name: str
    type: str
    required: bool
    default: Optional[Any]
    description: str
    constraints: dict[str, float]


class PolicyResponse(BaseModel):
    name: str
    category: str
    reward_types: list[str]
    description: str
    user_params: list[PolicyParamResponse]


class PoliciesListResponse(BaseModel):
    policies: list[PolicyResponse]


def _policy_description(policy_cls) -> str:
    """extract first line of the policy class docstring."""
    doc = policy_cls.__doc__ or ""
    return doc.strip().splitlines()[0].strip() if doc.strip() else ""


def _to_policy_response(policy_cls) -> PolicyResponse:
    user_params = [
        PolicyParamResponse(
            name=p.name,
            type=p.type,
            required=p.required,
            default=p.default,
            description=p.description,
            constraints=p.constraints,
        )
        for p in policy_cls.user_params()
    ]
    return PolicyResponse(
        name=policy_cls.name,
        category=policy_cls.category,
        reward_types=[rt.value for rt in policy_cls.reward_types],
        description=_policy_description(policy_cls),
        user_params=user_params,
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=PoliciesListResponse,
)
async def list_policies(
    reward_type: Optional[RewardType] = Query(
        default=None,
        description="filter policies by supported reward type (binary | bounded | continuous)",
    ),
) -> PoliciesListResponse:
    """list all available bandit policies with their configurable parameters.

    optionally filter by reward type to show only policies compatible with
    the reward signal your experiment produces.
    """
    matching = [
        p for p in POLICIES if reward_type is None or reward_type in p.reward_types
    ]
    return PoliciesListResponse(
        policies=[_to_policy_response(p) for p in matching],
    )
