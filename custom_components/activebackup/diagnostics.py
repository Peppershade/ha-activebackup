"""Diagnostics support for Synology Active Backup for Business."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import ActiveBackupConfigEntry

# Methods to probe on APIs that exist but returned "wrong method" (error 103).
_LOG_METHODS = [
    "list", "get", "query", "search",
    "list_log", "get_log", "list_backup", "get_backup",
    "list_activity", "get_activity",
]
_OVERVIEW_METHODS = [
    "list", "get", "status", "summary",
    "get_status", "get_summary", "get_overview",
    "get_all", "get_task_status",
]
_TASK_EXTRA_METHODS = [
    "get_result", "get_status", "list_result",
    "list_status", "status", "result",
    "get_log", "list_log",
]


async def _probe(client, api: str, method: str, extra: dict | None = None) -> dict[str, Any]:
    """Fire one API call and return a compact summary."""
    try:
        params: dict[str, Any] = {
            "api": api,
            "version": "1",
            "method": method,
            "_sid": client._sid,
            **(extra or {}),
        }
        r = await client._get("entry.cgi", params)
        success = r.get("success", False)
        error_code = r.get("error", {}).get("code") if not success else None
        data = r.get("data")
        return {
            "success": success,
            "error_code": error_code,
            "data_keys": list(data.keys()) if isinstance(data, dict) else (
                f"list[{len(data)}]" if isinstance(data, list) else type(data).__name__
            ),
            "first_item": (
                data.get("list", data.get("items", data.get("logs", [None])))[0]
                if isinstance(data, dict) else (data[0] if isinstance(data, list) and data else None)
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ActiveBackupConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    client = coordinator.client

    # --- API namespace discovery via query.cgi and entry.cgi ---
    api_info: dict[str, Any] = {}
    for path in ("query.cgi", "entry.cgi"):
        try:
            r = await client._get(path, {
                "api": "SYNO.API.Info",
                "version": "1",
                "method": "query",
                "query": "SYNO.ActiveBackup",
            })
            if r.get("success") and r.get("data"):
                api_info[path] = r["data"]
                break
            api_info[path] = {"success": r.get("success"), "error": r.get("error")}
        except Exception as exc:  # noqa: BLE001
            api_info[path] = {"error": str(exc)}

    # --- Probe methods on the three APIs of interest ---
    log_probes: dict[str, Any] = {}
    for method in _LOG_METHODS:
        result = await _probe(client, "SYNO.ActiveBackup.Log", method,
                              {"offset": 0, "limit": 2})
        log_probes[method] = result
        if result.get("success"):
            break  # stop at first success

    overview_probes: dict[str, Any] = {}
    for method in _OVERVIEW_METHODS:
        result = await _probe(client, "SYNO.ActiveBackup.Overview", method)
        overview_probes[method] = result
        if result.get("success"):
            break

    task_extra_probes: dict[str, Any] = {}
    for method in _TASK_EXTRA_METHODS:
        result = await _probe(client, "SYNO.ActiveBackup.Task", method,
                              {"offset": 0, "limit": 2})
        task_extra_probes[method] = result
        if result.get("success"):
            break

    return {
        "coordinator_last_update_success": coordinator.last_update_success,
        "task_count": len(coordinator.data) if coordinator.data else 0,
        "api_info": api_info,
        "log_method_probes": log_probes,
        "overview_method_probes": overview_probes,
        "task_extra_method_probes": task_extra_probes,
    }
