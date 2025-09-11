"""Simple config flow for Triad AMS: select active inputs/outputs.

This flow intentionally keeps the UI minimal: after providing host/port,
users choose which input and output channels are active via checkboxes.
Only active outputs create entities. Inputs are used for routing and, if
previous advanced options exist (e.g., input links), they are still
honored internally without being exposed in this basic UI.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import selector

from .const import DOMAIN, INPUT_COUNT, OUTPUT_COUNT


class TriadAmsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a simple config flow for Triad AMS."""

    VERSION = 1
    MINOR_VERSION = 3

    def __init__(self) -> None:
        """Initialize the flow state with host/port placeholders."""
        self._host: str | None = None
        self._port: int | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect host/port and continue to channel selection."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            self._host = user_input["host"]
            self._port = user_input["port"]
            return await self.async_step_channels()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("host"): str,
                    vol.Required("port", default=52000): int,
                }
            ),
        )

    async def async_step_channels(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose which inputs/outputs are active and optional input links."""
        if user_input is not None:
            active_inputs = [
                i for i in range(1, INPUT_COUNT + 1) if user_input.get(f"input_{i}")
            ]
            active_outputs = [
                i for i in range(1, OUTPUT_COUNT + 1) if user_input.get(f"output_{i}")
            ]
            input_links = {
                str(i): user_input.get(f"link_input_{i}")
                for i in range(1, INPUT_COUNT + 1)
                if user_input.get(f"link_input_{i}")
            }
            return self.async_create_entry(
                title=f"Triad AMS {self._host}",
                data={"host": self._host, "port": self._port},
                options={
                    "active_inputs": active_inputs,
                    "active_outputs": active_outputs,
                    "input_links": input_links,
                },
            )

        schema: dict[Any, Any] = {}
        for i in range(1, INPUT_COUNT + 1):
            schema[vol.Optional(f"input_{i}", default=False)] = bool
        for i in range(1, OUTPUT_COUNT + 1):
            schema[vol.Optional(f"output_{i}", default=False)] = bool
        for i in range(1, INPUT_COUNT + 1):
            schema[vol.Optional(f"link_input_{i}")] = selector({"entity": {"domain": "media_player"}})
        return self.async_show_form(step_id="channels", data_schema=vol.Schema(schema))

    async def async_step_ssdp(
        self, discovery_info: config_entries.SsdpServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Handle SSDP discovery (placeholder, not implemented)."""
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler for Triad AMS."""
        return TriadAmsOptionsFlowHandler(config_entry)


class TriadAmsOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow mirroring the active-channel selector."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Cache the entry for reading defaults and saving updates."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit active channels and optional per-input links."""
        if user_input is not None:
            active_inputs = [
                i for i in range(1, INPUT_COUNT + 1) if user_input.get(f"input_{i}")
            ]
            active_outputs = [
                i for i in range(1, OUTPUT_COUNT + 1) if user_input.get(f"output_{i}")
            ]
            input_links = {
                str(i): user_input.get(f"link_input_{i}")
                for i in range(1, INPUT_COUNT + 1)
                if user_input.get(f"link_input_{i}")
            }
            return self.async_create_entry(
                data={
                    "active_inputs": active_inputs,
                    "active_outputs": active_outputs,
                    "input_links": input_links,
                }
            )

        current = self.config_entry.options
        active_inputs = set(current.get("active_inputs", []))
        active_outputs = set(current.get("active_outputs", []))
        input_links = current.get("input_links", {})
        schema: dict[Any, Any] = {}
        for i in range(1, INPUT_COUNT + 1):
            schema[vol.Optional(f"input_{i}", default=i in active_inputs)] = bool
        for i in range(1, OUTPUT_COUNT + 1):
            schema[vol.Optional(f"output_{i}", default=i in active_outputs)] = bool
        for i in range(1, INPUT_COUNT + 1):
            key = f"link_input_{i}"
            existing = input_links.get(str(i))
            if existing:
                schema[vol.Optional(key, default=existing)] = selector({"entity": {"domain": "media_player"}})
            else:
                schema[vol.Optional(key)] = selector({"entity": {"domain": "media_player"}})
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))


async def _async_has_devices(hass: HomeAssistant) -> bool:
    """Return if there are devices that can be discovered (not implemented)."""
    devices: list[Any] = []
    return len(devices) > 0
