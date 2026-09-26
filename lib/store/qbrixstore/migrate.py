"""thin wrapper around the alembic cli so migrations run from the installed
package rather than depending on a working directory or an alembic.ini on disk.

the proxy image installs qbrixstore non-editable and copies only the venv, so
the migration scripts live inside the package; this resolves script_location
from the package path.

usage:
    python -m qbrixstore.migrate upgrade head
    python -m qbrixstore.migrate stamp head
    python -m qbrixstore.migrate current
"""

import sys
from pathlib import Path

from alembic.config import CommandLine, Config

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _make_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return cfg


def main(argv: list[str] | None = None) -> None:
    cli = CommandLine(prog="qbrixstore.migrate")
    options = cli.parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not hasattr(options, "cmd"):
        cli.parser.error("too few arguments")
    cli.run_cmd(_make_config(), options)


if __name__ == "__main__":
    main()
