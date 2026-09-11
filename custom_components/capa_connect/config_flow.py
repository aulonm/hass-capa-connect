"""Config, reauth and options flows for Capa Connect.

The config flow signs in with email/password once and stores only the rotating
refresh token. The options flow exposes the polling interval.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback

from .api import CapaApiError, CapaAuth, CapaAuthError, CapaClient
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)


class CapaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in once; store only the rotating refresh token, never the password."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CapaOptionsFlow:
        return CapaOptionsFlow()

    async def _login(
        self, email: str, password: str
    ) -> tuple[str | None, list[dict], str]:
        """Return (refresh_token, sites-or-empty, error_key).

        Uses a dedicated session: the multi-step B2C flow depends on the
        ``x-ms-cpim-*`` cookies from the authorize call being carried forward,
        and this keeps them out of HA's shared cookie jar.

        quote_cookie=False is required: those cookie values contain ``+ / . =``,
        which aiohttp would otherwise wrap in double quotes on the way back out.
        B2C sends them raw and rejects the quoted form as "Bad Request", so the
        SelfAsserted POST fails before any credential check.
        """
        jar = aiohttp.CookieJar(quote_cookie=False)
        async with aiohttp.ClientSession(cookie_jar=jar) as session:
            auth = CapaAuth(session)
            try:
                refresh_token = await auth.login(email, password)
                sites = await CapaClient(session, auth).get_sites()
            except CapaAuthError:
                return None, [], "invalid_auth"
            except (CapaApiError, aiohttp.ClientError):
                return None, [], "cannot_connect"
        return refresh_token, sites, ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            refresh_token, sites, error = await self._login(
                email, user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_configured()
                if len(sites) == 1:
                    title = sites[0].get("Name") or "Capa Connect"
                elif sites:
                    title = f"Capa Connect ({len(sites)} sites)"
                else:
                    title = "Capa Connect"
                return self.async_create_entry(
                    title=title,
                    data={"refresh_token": refresh_token, CONF_EMAIL: email},
                )
        schema = vol.Schema(
            {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            refresh_token, _sites, error = await self._login(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={"refresh_token": refresh_token}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"email": entry.data.get(CONF_EMAIL, "")},
        )


class CapaOptionsFlow(OptionsFlow):
    """Let the user tune how often the cloud is polled."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
