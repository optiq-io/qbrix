import asyncio

import click

from motorsvc.config import MotorSettings
from motorsvc.server import serve


@click.command()
@click.option("--host", default="0.0.0.0", help="gRPC server host")
@click.option("--port", default=50051, type=int, help="gRPC server port")
def run(host: str, port: int) -> None:
    settings = MotorSettings(grpc_host=host, grpc_port=port)
    asyncio.run(serve(settings))


if __name__ == "__main__":
    run()
