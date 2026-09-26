"""services that never touch clickhouse must not load its driver.

motor, cortex and the meter import qbrixstore for redis and postgres only, and
their images are built without the clickhouse extra.
"""

import subprocess
import sys


def test_redis_and_postgres_do_not_load_the_clickhouse_driver():
    probe = (
        "import sys\n"
        "import qbrixstore\n"
        "import qbrixstore.redis.client, qbrixstore.redis.streams\n"
        "import qbrixstore.postgres.session\n"
        "assert 'clickhouse_connect' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
