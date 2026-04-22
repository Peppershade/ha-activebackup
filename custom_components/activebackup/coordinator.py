"""API client and data coordinator for Synology Active Backup for Business."""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    AUTH_ERROR_CODES,
    CONF_DEVICE_TOKEN,
    CONF_SSL,
    CONF_VERIFY_SSL,
    DOMAIN,
    INVALID_OTP_CODE,
    LOGIN_ERROR_CODES,
    SCAN_INTERVAL_SECONDS,
    TWO_FACTOR_REQUIRED_CODE,
)

_LOGGER = logging.getLogger(__name__)

type ActiveBackupConfigEntry = ConfigEntry["ActiveBackupCoordinator"]


class ActiveBackupAuthError(Exception):
    """Raised when Synology DSM rejects credentials or the session is dead."""


class ActiveBackupTwoFactorRequired(Exception):
    """Raised when the account has 2FA enabled and no OTP/device-token was sent."""


class ActiveBackupOtpError(Exception):
    """Raised when an OTP code was supplied but rejected by the NAS."""


class ActiveBackupApiError(Exception):
    """Raised on any non-auth API failure."""


class ActiveBackupClient:
    """Low-level async HTTP client for the Synology Active Backup API."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        username: str,
        password: str,
        ssl: bool,
        verify_ssl: bool,
        device_token: str | None = None,
    ) -> None:
        self._hass = hass
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._sid: str | None = None
        self._device_token: str | None = device_token

        scheme = "https" if ssl else "http"
        self._base_url = f"{scheme}://{host}:{port}/webapi"

    def _session(self):
        return async_get_clientsession(self._hass, verify_ssl=self._verify_ssl)

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._session().get(
                f"{self._base_url}/{path}",
                params=params,
            )
        except Exception as err:
            raise ActiveBackupApiError(f"Connection to NAS failed: {err}") from err

        try:
            return await resp.json(content_type=None)
        except Exception as err:
            raise ActiveBackupApiError(
                f"NAS returned non-JSON response (HTTP {resp.status}): {err}"
            ) from err

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def authenticate(self, otp_code: str | None = None) -> str | None:
        """Obtain a new session ID from the DSM auth endpoint."""
        params: dict[str, Any] = {
            "api": "SYNO.API.Auth",
            "version": "6",
            "method": "login",
            "account": self._username,
            "passwd": self._password,
            "session": "ActiveBackup",
            "format": "sid",
        }
        if otp_code:
            params["otp_code"] = otp_code
            params["enable_device_token"] = "yes"
        elif self._device_token:
            params["device_id"] = self._device_token

        data = await self._get("auth.cgi", params)

        if not data.get("success"):
            code = data.get("error", {}).get("code", 0)
            if code == TWO_FACTOR_REQUIRED_CODE:
                raise ActiveBackupTwoFactorRequired()
            if code == INVALID_OTP_CODE:
                raise ActiveBackupOtpError("The OTP code was not accepted by the NAS.")
            if code in LOGIN_ERROR_CODES:
                raise ActiveBackupAuthError(
                    f"Login failed (DSM error code {code}). "
                    "Check username and password."
                )
            raise ActiveBackupApiError(f"Unexpected login error (code {code})")

        self._sid = data["data"]["sid"]
        _LOGGER.debug("Authenticated with Synology DSM at %s", self._base_url)

        issued_token: str | None = (
            data["data"].get("did") or data["data"].get("device_id")
        )
        if issued_token:
            self._device_token = issued_token

        return issued_token

    # ------------------------------------------------------------------
    # Task data
    # ------------------------------------------------------------------

    async def async_get_tasks(self) -> list[dict[str, Any]]:
        """Return tasks with last_result and live progress via compound API.

        The UI uses SYNO.Entry.Request (a compound/batch wrapper) with
        load_result=true and load_devices=true.  This is the only way to
        get last_result (backup history) and progress (live run status)
        in a single call.
        """
        if self._sid is None:
            raise ActiveBackupAuthError("Not authenticated")

        compound = json.dumps([
            {
                "api": "SYNO.ActiveBackup.Task",
                "method": "list",
                "version": 1,
                "load_result": True,
                "load_devices": True,
            }
        ])

        data = await self._get(
            "entry.cgi",
            {
                "api": "SYNO.Entry.Request",
                "method": "request",
                "version": "1",
                "stop_when_error": "false",
                "mode": "parallel",
                "compound": compound,
                "_sid": self._sid,
            },
        )

        if not data.get("success"):
            code = data.get("error", {}).get("code", 0)
            if code in AUTH_ERROR_CODES:
                self._sid = None
                raise ActiveBackupAuthError(
                    f"Session rejected by DSM (code {code})"
                )
            raise ActiveBackupApiError(f"Compound request failed (code {code})")

        # Response shape: {"data": {"result": [{"data": {"tasks": [...]}}]}}
        results: list[dict] = data.get("data", {}).get("result", [])
        if not results or not results[0].get("success"):
            inner_code = results[0].get("error", {}).get("code", 0) if results else 0
            # Auth errors can surface here instead of at the outer level
            if inner_code in AUTH_ERROR_CODES:
                self._sid = None
                raise ActiveBackupAuthError(
                    f"Session expired (compound inner code {inner_code})"
                )
            raise ActiveBackupApiError(
                f"Task list inner request failed (code {inner_code})"
            )

        task_payload: dict = results[0].get("data", {})
        return task_payload.get("tasks", [])

    async def logout(self) -> None:
        """Invalidate the current DSM session (best-effort)."""
        if not self._sid:
            return
        try:
            await self._get(
                "auth.cgi",
                {
                    "api": "SYNO.API.Auth",
                    "version": "1",
                    "method": "logout",
                    "session": "ActiveBackup",
                    "_sid": self._sid,
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Logout request failed (session may already be gone)")
        finally:
            self._sid = None


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class ActiveBackupCoordinator(DataUpdateCoordinator[dict[int, dict[str, Any]]]):
    """Polls the NAS every SCAN_INTERVAL_SECONDS and stores parsed task data."""

    config_entry: ActiveBackupConfigEntry

    def __init__(self, hass: HomeAssistant, client: ActiveBackupClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.client = client

    async def _async_update_data(self) -> dict[int, dict[str, Any]]:
        try:
            raw_tasks = await self.client.async_get_tasks()
        except (ActiveBackupAuthError, ActiveBackupApiError) as first_err:
            # Re-authenticate on any API failure. Session expiry can surface as
            # either ActiveBackupAuthError (outer-level) or ActiveBackupApiError
            # (inner compound result), so we treat both the same way.
            _LOGGER.debug("API call failed (%s), attempting re-auth", first_err)
            try:
                await self.client.authenticate()
            except ActiveBackupTwoFactorRequired as err:
                raise ConfigEntryAuthFailed(
                    "Re-authentication requires 2FA — please re-authenticate via the UI."
                ) from err
            except ActiveBackupAuthError as err:
                raise ConfigEntryAuthFailed(
                    "Could not re-authenticate with the Synology NAS."
                ) from err
            except Exception as err:
                raise UpdateFailed(f"Re-authentication failed: {err}") from err
            try:
                raw_tasks = await self.client.async_get_tasks()
            except Exception as err:
                raise UpdateFailed(f"Failed after re-auth: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error fetching tasks: {err}") from err

        parsed = {t["task_id"]: t for t in (_parse_task(r) for r in raw_tasks)}

        # Poll every 3 s while any backup is running; drop back to normal otherwise.
        any_running = any(t.get("status_str") == "running" for t in parsed.values())
        self.update_interval = timedelta(seconds=3 if any_running else SCAN_INTERVAL_SECONDS)

        return parsed


# ---------------------------------------------------------------------------
# Task parser
# ---------------------------------------------------------------------------

def _parse_task(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw task dict (with last_result + progress) into clean values."""
    task: dict[str, Any] = dict(raw)

    task["task_id"] = int(raw.get("task_id") or raw.get("id") or 0)

    # Device info from nested devices list
    devices: list[dict] = raw.get("devices") or []
    first_dev = devices[0] if devices else {}
    task["host_name"] = first_dev.get("host_name", "")
    task["os_name"] = first_dev.get("os_name", "")
    task["agent_status"] = first_dev.get("agent_status", "unknown")

    # Next scheduled run — the only useful timestamp from the task-level data
    raw_next = raw.get("next_trigger_time", -1)
    task["next_bkp_time"] = None if (raw_next is None or int(raw_next) < 0) else int(raw_next)

    # ---- Last completed backup (from last_result) ----
    lr: dict[str, Any] = raw.get("last_result") or {}
    if lr:
        time_end = lr.get("time_end")
        time_start = lr.get("time_start")

        task["last_bkp_time"] = int(time_end) if time_end and int(time_end) > 0 else None
        task["duration"] = (
            int(time_end) - int(time_start)
            if time_end and time_start and int(time_end) > 0 and int(time_start) > 0
            else None
        )
        # Note: Synology API has a typo — "transfered_bytes" (one 'r')
        task["transferred_size"] = lr.get("transfered_bytes")

        # Derive result from counts + completion status
        if lr.get("error_count", 0) > 0:
            task["result_str"] = "error"
        elif lr.get("warning_count", 0) > 0:
            task["result_str"] = "warning"
        elif lr.get("status") == 2:
            task["result_str"] = "success"
        else:
            task["result_str"] = "unknown"
    else:
        task["last_bkp_time"] = None
        task["duration"] = None
        task["transferred_size"] = None
        task["result_str"] = "unknown"

    # ---- Current run progress (only present while a backup is running) ----
    progress: dict[str, Any] = raw.get("progress") or {}
    if progress and progress.get("running_task_status") == 1:
        task["status_str"] = "running"
        # percentage is 0.0–1.0; convert to 0–100
        task["progress_pct"] = round(float(progress.get("percentage", 0)) * 100, 1)
        task["live_transferred"] = progress.get("transfered_bytes")
        task["total_bytes"] = progress.get("total_bytes")
    else:
        task["status_str"] = "idle"
        task["progress_pct"] = 0
        task["live_transferred"] = None
        task["total_bytes"] = None

    return task


def client_from_entry(hass: HomeAssistant, entry: ActiveBackupConfigEntry) -> ActiveBackupClient:
    return ActiveBackupClient(
        hass=hass,
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        ssl=entry.data[CONF_SSL],
        verify_ssl=entry.data[CONF_VERIFY_SSL],
        device_token=entry.data.get(CONF_DEVICE_TOKEN),
    )
