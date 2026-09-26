# qbrixruntime

The shared half of every qbrix service's `server.py`: how a service process
starts, serves and stops.

Each service keeps its own servicers, settings and business logic. What lives
here is the part that is identical everywhere and easy to get subtly wrong.

```python
from qbrixruntime.grpc import add_health
from qbrixruntime.grpc import bind
from qbrixruntime.grpc import build_server
from qbrixruntime.grpc import enable_reflection
from qbrixruntime.grpc import serve_until_shutdown
from qbrixruntime.shutdown import shutdown_signal


async def serve(settings: MotorSettings) -> None:
    async with shutdown_signal() as shutdown:
        service = MotorService(settings)
        await service.start()

        server = build_server(settings)
        motor_pb2_grpc.add_MotorServiceServicer_to_server(
            MotorGRPCServicer(service), server
        )
        health = await add_health(server, "motor")
        enable_reflection(server, MOTOR_SERVICE_NAME)
        logger.info("starting motor grpc server on %s", bind(server, settings))

        await server.start()
        try:
            await serve_until_shutdown(
                server, shutdown, grace=settings.shutdown_grace_sec, health=health
            )
        finally:
            await service.stop()
```

## Contents

| Module | Provides |
| --- | --- |
| `shutdown.py` | `shutdown_signal()` — SIGTERM/SIGINT as an `asyncio.Event` |
| `grpc.py` | server construction, health, reflection, and the serve-until-shutdown loop |
| `config.py` | `GrpcSettings` — the grpc listen/tuning/grace fields every service shares |
| `task.py` | `drain()` — cancel helper tasks and absorb their cancellation |

## Why the ordering in `serve_until_shutdown` matters

Two constraints, both found the hard way, are encoded
there so no service has to rediscover them:

1. **The grpc server is stopped before its termination waiter is cancelled.**
   Cancelling `wait_for_termination()` while the server is still running
   propagates the cancellation into the serving task and kills teardown, which
   surfaces as an exit-1 `CancelledError` traceback rather than a clean stop.
2. **Signal handlers are installed before any library that manages its own.**
   uvicorn's `capture_signals()` restores whatever handler it displaced and then
   re-raises the signal; with no handler of ours it restores `SIG_DFL` and the
   re-raise kills the process mid-teardown.
