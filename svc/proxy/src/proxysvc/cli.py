import asyncio

import click

from proxysvc.config import ProxySettings
from proxysvc.server import serve


@click.command()
@click.option("--host", default="0.0.0.0", help="gRPC server host")
@click.option("--port", default=50050, type=int, help="gRPC server port")
def run(host: str, port: int) -> None:
    settings = ProxySettings(grpc_host=host, grpc_port=port)
    asyncio.run(serve(settings))


if __name__ == "__main__":
    run()
