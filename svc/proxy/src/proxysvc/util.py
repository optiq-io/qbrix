from __future__ import annotations

from datetime import datetime
from datetime import time as dt_time
from datetime import timezone

from pydantic import ValidationError

from proxysvc.core.error import BadPolicyParamsError
from proxysvc.core.error import ContextDimImmutableError
from proxysvc.core.error import ContextSchemaImmutableError
from qbrixcore.context_schema import ContextSchema
from qbrixcore.policy._meta import _get_policy_class  # noqa


def _parse_time(value: str | dt_time | None) -> dt_time | None:
    """parse a time string like '09:00' or '23:59' into datetime.time."""
    if value is None:
        return None
    if isinstance(value, dt_time):
        return value
    try:
        parts = value.strip().split(":")
        return dt_time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError) as e:
        raise ValueError(f"invalid time format '{value}': expected HH:MM") from e


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    """parse a date/datetime string into a timezone-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        value = value.strip()
        # date only: '2026-02-02'
        if len(value) == 10:
            return datetime.fromisoformat(value + "T00:00:00").replace(
                tzinfo=timezone.utc
            )
        # full iso datetime
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as e:
        raise ValueError(f"invalid datetime format '{value}': expected ISO 8601") from e


def _resolve_context_schema(policy_params: dict | None) -> dict:
    """canonicalize a declared context_schema and derive `dim` from it.

    returns a new dict; the schema is stored in the form ContextSchema
    serializes to, so a later comparison is not defeated by 0 vs 0.0 or by
    key order. policy_params without a schema are returned untouched, which
    is what keeps the dim-only escape hatch working.

    args:
        policy_params: user-supplied dict of policy parameters.

    returns:
        policy_params with a canonical context_schema and a derived dim.

    raises:
        BadPolicyParamsError: if the schema is malformed, or dim is supplied
            alongside it.
    """
    params = dict(policy_params or {})
    declared = params.get("context_schema")
    if declared is None:
        return params

    if "dim" in params:
        raise BadPolicyParamsError(
            "context_schema and dim cannot both be supplied: dim is derived "
            "from the schema"
        )

    try:
        schema = ContextSchema.model_validate(declared)
    except ValidationError as e:
        raise BadPolicyParamsError(f"invalid context_schema: {e}") from e

    params["context_schema"] = schema.model_dump()
    params["dim"] = schema.dim
    return params


def _assert_context_schema_unchanged(current: dict | None, incoming: dict) -> None:
    """reject a patch that would add, drop or alter a context schema.

    both sides are already canonical — the stored one was written by
    _resolve_context_schema, the incoming one passed through it on the way
    here — so a plain comparison is sound.

    raises:
        ContextSchemaImmutableError: if the schema differs.
    """
    stored = (current or {}).get("context_schema")
    supplied = incoming.get("context_schema")
    if stored == supplied:
        return

    if stored is not None and supplied is None:
        detail = (
            "policy_params is replaced wholesale, so omitting context_schema "
            "would drop it"
        )
    elif stored is None:
        detail = "this experiment was not created with a context schema"
    else:
        detail = "the declared properties differ from the stored ones"

    raise ContextSchemaImmutableError(
        f"context_schema is fixed when the experiment is created: {detail}. "
        f"create a new experiment to change it"
    )


def _assert_context_dim_unchanged(current: dict | None, incoming: dict) -> None:
    """reject a patch that would add, drop or alter an experiment's context width.

    the learned arrays are shaped by dim and live in redis under the params
    key, while the select edge reads dim from policy_params — so a width
    change splits the two: the edge starts demanding the new width and motor
    keeps multiplying by arrays of the old one. policy_params is
    initialisation config (see ExperimentService.reset_experiment), which is
    what makes the split survive a retrain rather than heal.

    call after _assert_context_schema_unchanged: for a schema-backed
    experiment dim is derived, so any real change is a schema change and is
    better reported as one.

    raises:
        ContextDimImmutableError: if the width differs.
    """
    stored = (current or {}).get("dim")
    supplied = incoming.get("dim")
    if stored == supplied:
        return

    raise ContextDimImmutableError(
        f"dim is fixed when the experiment is created: stored width is "
        f"{stored}, requested {supplied}. the learned parameters are shaped "
        f"by it, so create a new experiment to change it"
    )


def _inspect_params(policy: str, policy_params: dict | None) -> None:
    """validate policy_params against the policy's param_state_cls.

    try-construct: instantiate the policy's pydantic param_state_cls with the
    provided params. pydantic raises ValidationError if anything is missing,
    out of range, or the wrong type.

    args:
        policy: policy class name (e.g. "BetaTSPolicy", "DirichletTSPolicy").
        policy_params: user-supplied dict of policy parameters. None or {}
            is treated as no params, which is valid for policies that have
            no required user_params.

    raises:
        InvalidPolicyParamsError: if the policy is unknown or the params
            do not satisfy the schema. the message contains the underlying
            pydantic error so callers can surface it to the user.
    """
    try:
        policy_cls = _get_policy_class(policy)
    except ValueError as e:
        raise BadPolicyParamsError(f"unknown policy: {policy}") from e

    params = policy_params or {}

    # placeholder num_arms=1; no current policy validates against num_arms itself,
    # only array shapes derived from it (which default to None and are filled by
    # the param_state_cls's @model_validator).
    try:
        policy_cls.param_state_cls(num_arms=1, **params)
    except ValidationError as e:
        raise BadPolicyParamsError(f"invalid policy_params for {policy}: {e}") from e
    except TypeError as e:
        # e.g. unknown keyword argument when policy_params has extra fields
        raise BadPolicyParamsError(f"invalid policy_params for {policy}: {e}") from e
