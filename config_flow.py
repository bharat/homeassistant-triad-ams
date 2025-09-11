"""Config flow for Triad AMS integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, INPUT_COUNT, OUTPUT_COUNT


def _input_output_schema(
    inputs: list[str] | None = None, outputs: list[str] | None = None
) -> vol.Schema:
    """Return schema for input/output names."""
    inputs = inputs or [f"Input {i + 1}" for i in range(INPUT_COUNT)]
    outputs = outputs or [f"Output {i + 1}" for i in range(OUTPUT_COUNT)]
    schema_dict = {}
    for i in range(INPUT_COUNT):
        schema_dict[vol.Required(f"input_{i + 1}", default=inputs[i])] = str
    for i in range(OUTPUT_COUNT):
        schema_dict[vol.Required(f"output_{i + 1}", default=outputs[i])] = str
    return vol.Schema(schema_dict)


class TriadAmsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Triad AMS."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the Triad AMS config flow."""
        self._host: str | None = None
        self._port: int | None = None
        self._input_names: list[str] = []
        self._output_names: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Always allow manual entry of host and port."""
        errors = {}
        if user_input is not None:
            self._host = user_input["host"]
            self._port = user_input["port"]
            # TODO: Optionally test connection here
            return await self.async_step_names()

        # Always show the manual entry form, regardless of discovery
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("host"): str,
                    vol.Required("port", default=52000): int,
                }
            ),
            errors=errors,
        )

    async def async_step_names(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure friendly names for inputs and outputs."""
        errors = {}
        if user_input is not None:
            self._input_names = [
                user_input[f"input_{i + 1}"] for i in range(INPUT_COUNT)
            ]
            self._output_names = [
                user_input[f"output_{i + 1}"] for i in range(OUTPUT_COUNT)
            ]
            return self.async_create_entry(
                title=f"Triad AMS {self._host}",
                data={"host": self._host, "port": self._port},
                options={
                    "inputs": self._input_names,
                    "outputs": self._output_names,
                },
            )

        return self.async_show_form(
            step_id="names",
            data_schema=_input_output_schema(),
            errors=errors,
        )

    async def async_step_ssdp(
        self, discovery_info: config_entries.SsdpServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Handle SSDP discovery (placeholder, not implemented)."""
        # Always allow fallback to manual entry
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler for Triad AMS."""
        return TriadAmsOptionsFlowHandler(config_entry)


class TriadAmsOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Triad AMS."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow handler for Triad AMS."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage input/output names in options."""
        if user_input is not None:
            inputs = [user_input[f"input_{i + 1}"] for i in range(INPUT_COUNT)]
            outputs = [user_input[f"output_{i + 1}"] for i in range(OUTPUT_COUNT)]
            return self.async_create_entry(
                data={
                    "inputs": inputs,
                    "outputs": outputs,
                }
            )
        # Use current names as defaults
        current_inputs = self.config_entry.options.get(
            "inputs", [f"Input {i + 1}" for i in range(INPUT_COUNT)]
        )
        current_outputs = self.config_entry.options.get(
            "outputs", [f"Output {i + 1}" for i in range(OUTPUT_COUNT)]
        )
        return self.async_show_form(
            step_id="init",
            data_schema=_input_output_schema(current_inputs, current_outputs),
        )


async def _async_has_devices(hass: HomeAssistant) -> bool:
    """Return if there are devices that can be discovered."""
    # TODO: Replace the following import and discovery logic with the actual dependency used for Triad AMS device discovery.
    # from some_module import discover_devices
    # devices = await hass.async_add_executor_job(discover_devices)
    devices = []  # Placeholder: No discovery implemented yet
    return len(devices) > 0
