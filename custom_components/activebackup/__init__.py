"""Synology Active Backup for Business integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .coordinator import (
    ActiveBackupApiError,
    ActiveBackupAuthError,
    ActiveBackupClient,
    ActiveBackupCoordinator,
    ActiveBackupConfigEntry,
    client_from_entry,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ActiveBackupConfigEntry) -> bool:
    """Set up Active Backup from a config entry."""
    client = client_from_entry(hass, entry)

    try:
        await client.authenticate()
    except ActiveBackupAuthError as err:
        raise ConfigEntryAuthFailed(
            "Could not authenticate with the Synology NAS. "
            "Check your username and password."
        ) from err
    except ActiveBackupApiError as err:
        raise ConfigEntryNotReady(str(err)) from err
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Unexpected error connecting to the Synology NAS: {err}"
        ) from err

    coordinator = ActiveBackupCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ActiveBackupConfigEntry) -> bool:
    """Unload a config entry and clean up the DSM session."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.client.logout()
    return unload_ok
