from __future__ import annotations

# the selection/feedback surface, mounted by the agent router under /api/v1.
# it is the only prefix that takes hot-path traffic from a customer's own
# frontend, which is why both the abuse rate limiter and the permissive cors
# policy key off it.
AGENT_PATH_PREFIX = "/api/v1/agent/"

# select(loop, context), the next request path. it takes the same traffic as
# the agent prefix, so the same limiter and cors policy cover it.
SELECT_PATH = "/api/v1/select"
