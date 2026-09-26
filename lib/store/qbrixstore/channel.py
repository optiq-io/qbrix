"""pub/sub channel names shared across services.

these are topology, not transport: a publisher in one service and a subscriber
in another have to agree on the string, so it cannot live in either of them.
a constant rather than a per-service setting, because a publisher and a
subscriber configured independently would drift into silence rather than fail.
"""

# published by proxy on a tier change; subscribed by every service that caches
# tenant-derived entitlements.
TENANT_INVALIDATION_CHANNEL = "qbrix:invalidate:tenant"
