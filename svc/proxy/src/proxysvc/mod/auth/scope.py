"""unified scope configuration for all protocols.

single source of truth for role scopes and protocol-specific
endpoint-to-scope mappings.
"""

# role scopes mapping - uses string keys for Postgres compatibility
ROLE_SCOPES = {
    "admin": [
        "system:admin",
        "user:read",
        "user:write",
        "user:delete",
        "experiment:read",
        "experiment:write",
        "experiment:delete",
        "pool:read",
        "pool:write",
        "pool:delete",
        "agent:read",
        "agent:write",
        "agent:delete",
        "gate:write",
        "gate:read",
        "metric:read",
        "insight:read",
        "insight:write",
        "trace:read",
        "runtime:read",
    ],
    "member": [
        "experiment:read",
        "experiment:write",
        "experiment:delete",
        "pool:read",
        "pool:write",
        "pool:delete",
        "agent:read",
        "agent:write",
        "agent:delete",
        "gate:write",
        "gate:read",
        "metric:read",
        "insight:read",
        "insight:write",
        "trace:read",
        "runtime:read",
    ],
    "viewer": [
        "experiment:read",
        "pool:read",
        "agent:read",
        "gate:read",
        "metric:read",
        "insight:read",
        "trace:read",
        "runtime:read",
    ],
}


# abuse-protection rate limit, decoupled from plan tier (selections are the
# billed metric, metered separately). -1 disables it.
ABUSE_RATE_LIMIT_PER_MINUTE = 6000

# invite emails a tenant may send per utc day, whatever its seats.
INVITES_PER_TENANT_PER_DAY = 25


# http endpoint to scope mapping for authorisation
ENDPOINT_SCOPES = {
    # pools
    ("POST", "/api/v1/pools"): "pool:write",
    ("GET", "/api/v1/pools/*"): "pool:read",
    ("DELETE", "/api/v1/pools/*"): "pool:delete",
    # experiments
    ("POST", "/api/v1/experiments"): "experiment:write",
    ("POST", "/api/v1/experiments/*"): "experiment:write",
    ("GET", "/api/v1/experiments/*"): "experiment:read",
    ("PATCH", "/api/v1/experiments/*"): "experiment:write",
    ("DELETE", "/api/v1/experiments/*"): "experiment:delete",
    # gates
    ("POST", "/api/v1/gates/*"): "gate:write",
    ("GET", "/api/v1/gates/*"): "gate:read",
    ("PUT", "/api/v1/gates/*"): "gate:write",
    ("DELETE", "/api/v1/gates/*"): "gate:write",
    # agent operations (selection/feedback)
    ("POST", "/api/v1/agent/feedback"): "agent:write",
    ("POST", "/api/v1/agent/select"): "agent:read",
    # metrics
    ("POST", "/api/v1/metric/*"): "metric:read",
    ("GET", "/api/v1/metric/*"): "metric:read",
    # insight
    ("POST", "/api/v1/insight/*"): "insight:read",
    ("GET", "/api/v1/insight/*"): "insight:read",
    # runtime
    ("GET", "/api/v1/runtime/*"): "runtime:read",
}


# grpc method to required scope mapping
RPC_SCOPES: dict[str, str] = {
    # pool management
    "/qbrix.proxy.ProxyService/CreatePool": "pool:write",
    "/qbrix.proxy.ProxyService/GetPool": "pool:read",
    "/qbrix.proxy.ProxyService/ListPools": "pool:read",
    "/qbrix.proxy.ProxyService/UpdatePool": "pool:write",
    "/qbrix.proxy.ProxyService/DeletePool": "pool:delete",
    # experiment management
    "/qbrix.proxy.ProxyService/CreateExperiment": "experiment:write",
    "/qbrix.proxy.ProxyService/GetExperiment": "experiment:read",
    "/qbrix.proxy.ProxyService/ListExperiments": "experiment:read",
    "/qbrix.proxy.ProxyService/ListPoolExperiments": "experiment:read",
    "/qbrix.proxy.ProxyService/UpdateExperiment": "experiment:write",
    "/qbrix.proxy.ProxyService/DeleteExperiment": "experiment:delete",
    # gate config management
    "/qbrix.proxy.ProxyService/CreateGateConfig": "gate:write",
    "/qbrix.proxy.ProxyService/GetGateConfig": "gate:read",
    "/qbrix.proxy.ProxyService/UpdateGateConfig": "gate:write",
    "/qbrix.proxy.ProxyService/DeleteGateConfig": "gate:write",
    # agent operations
    "/qbrix.proxy.ProxyService/Select": "agent:read",
    "/qbrix.proxy.ProxyService/Feedback": "agent:write",
}
