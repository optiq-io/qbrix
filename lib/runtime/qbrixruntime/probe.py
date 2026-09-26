"""container health probe: `python -m qbrixruntime.probe <host:port>`.

exits 0 when the grpc server at the target reports SERVING on its overall
health entry, the same entry kubernetes `grpc:` probes read, and 1 otherwise.
"""

from __future__ import annotations

import sys

from typing import Sequence

import grpc
from grpc_health.v1 import health_pb2
from grpc_health.v1 import health_pb2_grpc

TIMEOUT_SEC = 5.0


def check(target: str, timeout: float = TIMEOUT_SEC) -> bool:
    with grpc.insecure_channel(target) as channel:
        try:
            response = health_pb2_grpc.HealthStub(channel).Check(
                health_pb2.HealthCheckRequest(service=""), timeout=timeout
            )
        except grpc.RpcError:
            return False
    return response.status == health_pb2.HealthCheckResponse.SERVING


def main(argv: Sequence[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1:
        print("usage: python -m qbrixruntime.probe <host:port>", file=sys.stderr)
        return 2
    return 0 if check(args[0]) else 1


if __name__ == "__main__":
    sys.exit(main())
