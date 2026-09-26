from __future__ import annotations

import sys

import click


@click.command()
@click.option(
    "--web",
    is_flag=True,
    default=False,
    help="start with web interface (default: headless)",
)
@click.option(
    "--host",
    "-h",
    default="localhost",
    help="proxy service host",
)
@click.option(
    "--port",
    "-p",
    default=8080,
    type=int,
    help="proxy service HTTP port",
)
@click.option(
    "--scheme",
    type=click.Choice(["http", "https"]),
    default="http",
    help="proxy service URL scheme",
)
@click.option(
    "--users",
    "-u",
    default=10,
    type=int,
    help="number of concurrent users",
)
@click.option(
    "--spawn-rate",
    "-r",
    default=1,
    type=float,
    help="users to spawn per second",
)
@click.option(
    "--run-time",
    "-t",
    default=None,
    type=str,
    help="run time (e.g., 60s, 5m, 1h). required for headless mode",
)
@click.option(
    "--web-host",
    default="localhost",
    help="web interface host",
)
@click.option(
    "--web-port",
    default=8089,
    type=int,
    help="web interface port",
)
@click.option(
    "--num-experiments",
    "-n",
    default=1,
    type=int,
    help="number of experiments to create",
)
@click.option(
    "--num-arms",
    default=5,
    type=int,
    help="number of arms per pool",
)
@click.option(
    "--no-auto",
    is_flag=True,
    default=False,
    help="disable auto (meta-bandit) mode; use random manual policies instead",
)
def run(
    web: bool,
    host: str,
    port: int,
    scheme: str,
    users: int,
    spawn_rate: float,
    run_time: str | None,
    web_host: str,
    web_port: int,
    num_experiments: int,
    num_arms: int,
    no_auto: bool,
) -> None:
    """
    run qbrix load tests using locust.

    experiments use auto (meta-bandit) mode by default.
    pass --no-auto to use random manual policies instead.

    examples:

        # 1 auto experiment, headless 60s
        make loadtest

        # 5 auto experiments with web ui
        uv run python -m loadtest.cli -n 5 --web

        # 3 manual experiments, random policies
        uv run python -m loadtest.cli -n 3 --no-auto -u 30 -r 5 -t 60s
    """
    import os

    os.environ["LOADTEST_PROXY_HOST"] = host
    os.environ["LOADTEST_PROXY_PORT"] = str(port)
    os.environ["LOADTEST_PROXY_SCHEME"] = scheme
    os.environ["LOADTEST_NUM_EXPERIMENTS"] = str(num_experiments)
    os.environ["LOADTEST_NUM_ARMS"] = str(num_arms)
    os.environ["LOADTEST_AUTO"] = str(not no_auto).lower()

    locust_args = ["locust", "-f", "loadtest/plan.py"]

    if web:
        locust_args.extend(["--web-host", web_host, "--web-port", str(web_port)])
        click.echo(
            f"starting locust web interface at http://{web_host}:{web_port}"
        )  # noqa
    else:
        if not run_time:
            click.echo("error: --run-time is required for headless mode", err=True)
            click.echo(
                "use --web for interactive mode or specify -t/--run-time", err=True
            )
            sys.exit(1)

        locust_args.extend(
            [
                "--headless",
                "-u",
                str(users),
                "-r",
                str(spawn_rate),
                "-t",
                run_time,
            ]
        )

    mode = "auto (meta-bandit)" if not no_auto else "manual (random policies)"
    click.echo(f"mode: {mode}")
    click.echo(f"experiments: {num_experiments}, arms: {num_arms}")
    click.echo(f"target: {scheme}://{host}:{port}")
    if not web:
        click.echo(f"users: {users}, spawn rate: {spawn_rate}/s, duration: {run_time}")

    sys.argv = locust_args
    from locust.main import main as locust_main

    locust_main()


if __name__ == "__main__":
    run()
