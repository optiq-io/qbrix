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
    ],
    "viewer": [
        "experiment:read",
        "pool:read",
        "agent:read",
        "gate:read",
        "metric:read",
    ],
}


# endpoint to scope mapping for authorization
ENDPOINT_SCOPES = {
    # pools
    ("POST", "/api/v1/pools"): "pool:write",
    ("GET", "/api/v1/pools/*"): "pool:read",
    ("DELETE", "/api/v1/pools/*"): "pool:delete",
    # experiments
    ("POST", "/api/v1/experiments"): "experiment:write",
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
}


# plan limits - uses string keys for Postgres compatibility
PLAN_LIMITS = {
    "free": {
        "rate_limit_per_minute": 100,
        "max_api_keys": 1,
    },
    "pro": {
        "rate_limit_per_minute": 1000,
        "max_api_keys": 10,
    },
    "enterprise": {
        "rate_limit_per_minute": 10000,
        "max_api_keys": -1,
    },
}
