"""Constants for the Synology Active Backup for Business integration."""
from __future__ import annotations

DOMAIN = "activebackup"

# Config entry keys (non-standard ones not in homeassistant.const)
CONF_SSL = "ssl"
CONF_VERIFY_SSL = "verify_ssl"
# Stored after a successful OTP login so future sessions can skip 2FA prompts
CONF_DEVICE_TOKEN = "device_token"

# Defaults
DEFAULT_PORT_SSL = 5001
DEFAULT_PORT_PLAIN = 5000
DEFAULT_SSL = True
DEFAULT_VERIFY_SSL = True

# How often to refresh task data (seconds)
SCAN_INTERVAL_SECONDS = 60

# Synology Active Backup task status codes -> human-readable strings.
# Source: empirical / community reverse-engineering; not officially documented.
TASK_STATUS: dict[int, str] = {
    0: "waiting",
    1: "running",
    2: "stopped",
    3: "interrupted",
}

# Synology Active Backup task result codes -> human-readable strings.
TASK_RESULT: dict[int, str] = {
    0: "success",
    1: "warning",
    2: "error",
    3: "unknown",
}

# API error codes that indicate an expired or invalid session
AUTH_ERROR_CODES: frozenset[int] = frozenset({105, 106, 107, 119})

# API error codes returned on a failed login attempt (wrong password / disabled)
LOGIN_ERROR_CODES: frozenset[int] = frozenset({400, 401, 402})

# DSM returns 403 when 2FA is enabled and no OTP/device-token was supplied
TWO_FACTOR_REQUIRED_CODE = 403

# DSM returns 404 when an OTP code was supplied but was wrong
INVALID_OTP_CODE = 404
