from qbrixstore.postgres.models import Experiment

from proxysvc.mod.gate.repository import FeatureGateRepository
from proxysvc.mod.pool.serialize import pool_to_dict


def experiment_to_dict(experiment: Experiment) -> dict:
    pool_dict = None
    if experiment.pool:
        pool_dict = pool_to_dict(experiment.pool)

    gate_config = None
    if experiment.feature_gate:
        gate_config = FeatureGateRepository.to_config(experiment.feature_gate)

    return {
        "id": experiment.id,
        "name": experiment.name,
        "pool_id": experiment.pool_id,
        "policy": experiment.policy,
        "policy_params": experiment.policy_params,
        "enabled": experiment.enabled,
        "created_at": (
            experiment.created_at.isoformat() if experiment.created_at else None
        ),
        "updated_at": (
            experiment.updated_at.isoformat() if experiment.updated_at else None
        ),
        "pool": pool_dict,
        "feature_gate": gate_config,
        "meta_experiment_id": experiment.meta_experiment_id,
    }
