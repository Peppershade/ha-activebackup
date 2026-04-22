"""Config flow for Synology Active Backup for Business."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_TOKEN,
    CONF_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_PORT_SSL,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .coordinator import (
    ActiveBackupAuthError,
    ActiveBackupClient,
    ActiveBackupOtpError,
    ActiveBackupTwoFactorRequired,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT_SSL): vol.Coerce(int),
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SSL, default=DEFAULT_SSL): bool,
        vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)

STEP_OTP_SCHEMA = vol.Schema(
    {
        vol.Required("otp_code"): str,
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)


class ActiveBackupConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Synology Active Backup for Business."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        # Credentials gathered in step 1; held while we wait for OTP in step 2.
        self._pending_data: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Step 1: credentials
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect host, port, username, password, and SSL options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client = _make_client(self.hass, user_input)
            try:
                await client.authenticate()
            except ActiveBackupTwoFactorRequired:
                # Account has 2FA: stash credentials and show the OTP form.
                self._pending_data = user_input
                return await self.async_step_two_factor()
            except ActiveBackupAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during connection test")
                errors["base"] = "cannot_connect"
            else:
                await client.logout()
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_HOST],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2 (conditional): OTP
    # ------------------------------------------------------------------

    async def async_step_two_factor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect a TOTP code and complete authentication."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client = _make_client(self.hass, self._pending_data)
            try:
                device_token = await client.authenticate(
                    otp_code=user_input["otp_code"]
                )
            except ActiveBackupOtpError:
                errors["base"] = "invalid_otp"
            except ActiveBackupAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during OTP verification")
                errors["base"] = "cannot_connect"
            else:
                await client.logout()
                entry_data = dict(self._pending_data)
                if device_token:
                    entry_data[CONF_DEVICE_TOKEN] = device_token
                await self.async_set_unique_id(
                    f"{entry_data[CONF_HOST]}:{entry_data[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=entry_data[CONF_HOST],
                    data=entry_data,
                )

        return self.async_show_form(
            step_id="two_factor",
            data_schema=STEP_OTP_SCHEMA,
            errors=errors,
            description_placeholders={
                "host": self._pending_data.get(CONF_HOST, "")
            },
        )

    # ------------------------------------------------------------------
    # Re-authentication flow (triggered automatically by ConfigEntryAuthFailed)
    # ------------------------------------------------------------------

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Initiate re-authentication after an auth failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for a new password and validate it."""
        errors: dict[str, str] = {}
        reauth_entry: ConfigEntry = self._get_reauth_entry()

        if user_input is not None:
            # Build updated data with the new password and without any stale
            # device token (that's what caused the auth failure).
            updated_data = {
                **reauth_entry.data,
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            updated_data.pop(CONF_DEVICE_TOKEN, None)

            client = _make_client(self.hass, updated_data)
            try:
                await client.authenticate()
            except ActiveBackupTwoFactorRequired:
                self._pending_data = updated_data
                return await self.async_step_reauth_two_factor()
            except ActiveBackupAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during re-authentication")
                errors["base"] = "cannot_connect"
            else:
                await client.logout()
                self.hass.config_entries.async_update_entry(
                    reauth_entry, data=updated_data
                )
                await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"host": reauth_entry.data[CONF_HOST]},
        )

    async def async_step_reauth_two_factor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect OTP during re-authentication."""
        errors: dict[str, str] = {}
        reauth_entry: ConfigEntry = self._get_reauth_entry()

        if user_input is not None:
            client = _make_client(self.hass, self._pending_data)
            try:
                device_token = await client.authenticate(
                    otp_code=user_input["otp_code"]
                )
            except ActiveBackupOtpError:
                errors["base"] = "invalid_otp"
            except ActiveBackupAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during OTP re-authentication")
                errors["base"] = "cannot_connect"
            else:
                await client.logout()
                final_data = dict(self._pending_data)
                if device_token:
                    final_data[CONF_DEVICE_TOKEN] = device_token
                self.hass.config_entries.async_update_entry(
                    reauth_entry, data=final_data
                )
                await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_two_factor",
            data_schema=STEP_OTP_SCHEMA,
            errors=errors,
            description_placeholders={"host": reauth_entry.data[CONF_HOST]},
        )


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _make_client(hass: HomeAssistant, data: dict[str, Any]) -> ActiveBackupClient:
    """Build a client from a data dict (config entry or flow user_input)."""
    return ActiveBackupClient(
        hass=hass,
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        ssl=data[CONF_SSL],
        verify_ssl=data[CONF_VERIFY_SSL],
        device_token=data.get(CONF_DEVICE_TOKEN),
    )
