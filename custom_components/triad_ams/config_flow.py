"""
Simple config flow for Triad AMS: select active inputs/outputs.

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

    def _device_counts(self, device_type: str | None) -> tuple[int, int]:
        """Return (input_count, output_count) for a given device type."""
        if device_type == "8x8":
            return 8, 8
        if device_type == "16x16":
            return 16, 16
        if device_type == "24x24":
            return 24, 24
        # Fallback to package-wide defaults if device type is unknown/missing.
        return INPUT_COUNT, OUTPUT_COUNT

    def __init__(self) -> None:
        """Initialize the flow state with host/port/name placeholders."""
        self._host: str | None = None
        self._port: int | None = None
        self._name: str | None = None
        self._device_type: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect host/port and continue to channel selection."""
        if user_input is not None:
            self._host = user_input["host"]
            self._port = user_input["port"]
            self._device_type = user_input.get("device_type", "8x8")
            self._name = (
                user_input.get("name") or f"Triad AMS {self._device_type} {self._host}"
            )
            # Use host:port:type as a stable unique_id to prevent duplicates,
            # while still allowing multiple distinct hubs.
            unique_id = f"{self._host}:{self._port}:{self._device_type}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return await self.async_step_channels()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional("name", default="Triad AMS"): str,
                    vol.Required("host"): str,
                    vol.Required("port", default=52000): int,
                    vol.Required("device_type", default="8x8"): selector(
                        {
                            "select": {
                                "options": [
                                    {"value": "8x8", "label": "8x8"},
                                    {"value": "16x16", "label": "16x16"},
                                    {"value": "24x24", "label": "24x24"},
                                ]
                            }
                        }
                    ),
                }
            ),
        )

    async def async_step_channels(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose which inputs/outputs are active and optional input links."""
        if user_input is not None:
            # Determine counts based on selected device type (fall back to defaults).
            input_count, output_count = self._device_counts(self._device_type)
            active_inputs = [
                i for i in range(1, input_count + 1) if user_input.get(f"input_{i}")
            ]
            active_outputs = [
                i for i in range(1, output_count + 1) if user_input.get(f"output_{i}")
            ]
            input_links = {
                str(i): user_input.get(f"link_input_{i}")
                for i in range(1, input_count + 1)
                if user_input.get(f"link_input_{i}")
            }
            return self.async_create_entry(
                title=self._name or f"Triad AMS {self._host}",
                data={
                    "host": self._host,
                    "port": self._port,
                    "device_type": self._device_type,
                },
                options={
                    "active_inputs": active_inputs,
                    "active_outputs": active_outputs,
                    "input_links": input_links,
                },
            )

        schema: dict[Any, Any] = {}
        # Determine counts for the UI based on the selected device type (or default)
        input_count, output_count = self._device_counts(self._device_type)
        # Outputs first
        for i in range(1, output_count + 1):
            schema[vol.Optional(f"output_{i}", default=False)] = bool
        # Then inputs, each followed by its optional link
        for i in range(1, input_count + 1):
            schema[vol.Optional(f"input_{i}", default=False)] = bool
            schema[vol.Optional(f"link_input_{i}")] = selector(
                {"entity": {"domain": "media_player"}}
            )
        return self.async_show_form(step_id="channels", data_schema=vol.Schema(schema))

    # No discovery implemented; omit SSDP/zeroconf handlers to avoid
    # hassfest discoverable flow requirements.

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler for Triad AMS."""
        return TriadAmsOptionsFlowHandler(config_entry)


class TriadAmsOptionsFlowHandler(config_entries.OptionsFlowWithConfigEntry):
    """Options flow mirroring the active-channel selector."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize with the provided config entry (new API)."""
        super().__init__(config_entry)

    def _device_counts(self, device_type: str | None) -> tuple[int, int]:
        """Return (input_count, output_count) for a given device type."""
        if device_type == "8x8":
            return 8, 8
        if device_type == "16x16":
            return 16, 16
        if device_type == "24x24":
            return 24, 24
        # Fallback to package-wide defaults if device type is unknown/missing.
        return INPUT_COUNT, OUTPUT_COUNT

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit active channels and optional per-input links."""
        if user_input is not None:
            # Update the entry title if the name changed
            new_title = user_input.get("name")
            if new_title and new_title != self.config_entry.title:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, title=new_title
                )
            # Use device_type from the stored config entry to determine counts
            device_type = self.config_entry.data.get("device_type")
            input_count, output_count = self._device_counts(device_type)
            active_inputs = [
                i for i in range(1, input_count + 1) if user_input.get(f"input_{i}")
            ]
            active_outputs = [
                i for i in range(1, output_count + 1) if user_input.get(f"output_{i}")
            ]
            input_links = {
                str(i): user_input.get(f"link_input_{i}")
                for i in range(1, input_count + 1)
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
        # Allow renaming the device (updates entry title)
        schema[vol.Optional("name", default=self.config_entry.title)] = str
        # Determine counts from stored device type
        device_type = self.config_entry.data.get("device_type")
        input_count, output_count = self._device_counts(device_type)
        # Outputs first
        for i in range(1, output_count + 1):
            schema[vol.Optional(f"output_{i}", default=i in active_outputs)] = bool
        # Then inputs with inline link selectors
        for i in range(1, input_count + 1):
            schema[vol.Optional(f"input_{i}", default=i in active_inputs)] = bool
            key = f"link_input_{i}"
            existing = input_links.get(str(i))
            if existing:
                schema[vol.Optional(key, default=existing)] = selector(
                    {"entity": {"domain": "media_player"}}
                )
            else:
                schema[vol.Optional(key)] = selector(
                    {"entity": {"domain": "media_player"}}
                )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))


async def _async_has_devices(_hass: HomeAssistant) -> bool:
    """Return if there are devices that can be discovered (not implemented)."""
    devices: list[Any] = []
    return len(devices) > 0
