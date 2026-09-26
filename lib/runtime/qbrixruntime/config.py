from __future__ import annotations

from pydantic_settings import BaseSettings


class GrpcSettings(BaseSettings):
    """listen address, server tuning and shutdown budget, shared by all services.

    services subclass this and set their own ``env_prefix``, so the same field
    reads ``MOTOR_GRPC_PORT`` for motor and ``TRACE_GRPC_PORT`` for trace.
    """

    grpc_host: str = "0.0.0.0"
    grpc_port: int = 50051
    grpc_server_thread_pool_size: int = 10
    grpc_server_min_recv_ping_interval_ms: int = 5000
    grpc_server_keepalive_permit_without_calls: bool = True

    # drain budget for one transport on shutdown. a pod's
    # terminationGracePeriodSeconds must exceed the sum of every drain the
    # service performs in sequence, plus any prestop delay.
    shutdown_grace_sec: int = 20
