from __future__ import annotations

WINDOW_SEC = 60

# per-minute limits per bucket.
LOGIN_IP_PER_MIN = 10
LOGIN_EMAIL_PER_MIN = 10
REGISTER_IP_PER_MIN = 5
REFRESH_IP_PER_MIN = 30
FORGOT_IP_PER_MIN = 10
FORGOT_EMAIL_PER_MIN = 3
RESET_IP_PER_MIN = 10
VERIFY_EMAIL_IP_PER_MIN = 10
RESEND_VERIFICATION_IP_PER_MIN = 10
RESEND_VERIFICATION_EMAIL_PER_MIN = 3
OAUTH_REGISTER_IP_PER_MIN = 5
OAUTH_IP_PER_MIN = 30

# path → (bucket scope, per-minute ip limit) for the ip dimension, enforced in
# the auth middleware. paths are the full mounted paths (auth router is mounted
# under /api).
IP_BUCKETS: dict[str, tuple[str, int]] = {
    "/api/auth/login": ("login", LOGIN_IP_PER_MIN),
    "/api/auth/register": ("register", REGISTER_IP_PER_MIN),
    "/api/auth/refresh": ("refresh", REFRESH_IP_PER_MIN),
    "/api/auth/forgot-password": ("forgot", FORGOT_IP_PER_MIN),
    "/api/auth/reset-password": ("reset", RESET_IP_PER_MIN),
    "/api/auth/verify-email": ("verify_email", VERIFY_EMAIL_IP_PER_MIN),
    "/api/auth/resend-verification": (
        "resend_verification",
        RESEND_VERIFICATION_IP_PER_MIN,
    ),
    "/oauth/register": ("oauth_register", OAUTH_REGISTER_IP_PER_MIN),
    "/oauth/authorize": ("oauth_authorize", OAUTH_IP_PER_MIN),
    "/oauth/token": ("oauth_token", OAUTH_IP_PER_MIN),
    "/oauth/revoke": ("oauth_revoke", OAUTH_IP_PER_MIN),
}
