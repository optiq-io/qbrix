from __future__ import annotations

# the selection/feedback surface, mounted by the agent router under /api/v1.
# it is the only prefix that takes hot-path traffic from a customer's own
# frontend, which is why both the abuse rate limiter and the permissive cors
# policy key off it.
AGENT_PATH_PREFIX = "/api/v1/agent/"
