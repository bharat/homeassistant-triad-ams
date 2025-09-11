"""Config flow for Triad AMS integration with flexible IO configuration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import selector

from .const import DOMAIN, INPUT_COUNT, OUTPUT_COUNT


def _channel_selector(max_ch: int) -> Any:
    return selector({"select": {"options": [str(i) for i in range(1, max_ch + 1)]}})


class TriadAmsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Triad AMS."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._host: str | None = None
        self._port: int | None = None
        self._inputs: dict[int, dict[str, Any]] = {}
        self._outputs: dict[int, dict[str, Any]] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Always allow manual entry of host and port.

        Enforce single instance to avoid collisions in unique IDs.
        """
        errors = {}
        # Single instance guard
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            self._host = user_input["host"]
            self._port = user_input["port"]
            return await self.async_step_config_menu()

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

    async def async_step_config_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            action = user_input["action"]
            if action == "add_input":
                return await self.async_step_add_input()
            if action == "add_output":
                return await self.async_step_add_output()
            if action == "finish":
                inputs_opt = {
                    str(ch): {"name": data["name"], "link": data.get("link")}
                    for ch, data in self._inputs.items()
                }
                outputs_opt = {
                    str(ch): {"name": data["name"]} for ch, data in self._outputs.items()
                }
                return self.async_create_entry(
                    title=f"Triad AMS {self._host}",
                    data={"host": self._host, "port": self._port},
                    options={
                        "inputs_config": inputs_opt,
                        "outputs_config": outputs_opt,
                    },
                )

        return self.async_show_form(
            step_id="config_menu",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "action",
                        default="finish" if self._inputs or self._outputs else "add_input",
                    ): selector(
                        {
                            "select": {
                                "options": [
                                    {"value": "add_input", "label": "Add input"},
                                    {"value": "add_output", "label": "Add output"},
                                    {"value": "finish", "label": "Finish"},
                                ]
                            }
                        }
                    )
                }
            ),
        )

    async def async_step_add_input(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            ch = int(user_input["channel"])
            name = user_input["name"]
            link = user_input.get("link")
            self._inputs[ch] = {"name": name, "link": link}
            return await self.async_step_config_menu()
        default_channel = next((str(i) for i in range(1, INPUT_COUNT + 1) if i not in self._inputs), "1")
        default_name = f"Input {default_channel}"
        return self.async_show_form(
            step_id="add_input",
            data_schema=vol.Schema(
                {
                    vol.Required("channel", default=default_channel): _channel_selector(
                        INPUT_COUNT
                    ),
                    vol.Required("name", default=default_name): str,
                    vol.Optional("link"): selector({"entity": {"domain": "media_player"}}),
                }
            ),
        )

    async def async_step_add_output(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            ch = int(user_input["channel"])
            name = user_input["name"]
            self._outputs[ch] = {"name": name}
            return await self.async_step_config_menu()
        default_channel = next((str(i) for i in range(1, OUTPUT_COUNT + 1) if i not in self._outputs), "1")
        default_name = f"Output {default_channel}"
        return self.async_show_form(
            step_id="add_output",
            data_schema=vol.Schema(
                {
                    vol.Required("channel", default=default_channel): _channel_selector(
                        OUTPUT_COUNT
                    ),
                    vol.Required("name", default=default_name): str,
                }
            ),
        )

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
    """Handle options for Triad AMS: add inputs/outputs and save."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
        self._inputs = {
            int(k): v for k, v in config_entry.options.get("inputs_config", {}).items()
        }
        self._outputs = {
            int(k): v for k, v in config_entry.options.get("outputs_config", {}).items()
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            action = user_input["action"]
            if action == "add_input":
                return await self.async_step_add_input()
            if action == "add_output":
                return await self.async_step_add_output()
            if action == "save":
                return self.async_create_entry(
                    data={
                        "inputs_config": {str(k): v for k, v in self._inputs.items()},
                        "outputs_config": {str(k): v for k, v in self._outputs.items()},
                    }
                )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="save"): selector(
                        {
                            "select": {
                                "options": [
                                    {"value": "add_input", "label": "Add input"},
                                    {"value": "add_output", "label": "Add output"},
                                    {"value": "save", "label": "Save"},
                                ]
                            }
                        }
                    )
                }
            ),
        )

    async def async_step_add_input(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            ch = int(user_input["channel"])
            name = user_input["name"]
            link = user_input.get("link")
            self._inputs[ch] = {"name": name, "link": link}
            return await self.async_step_init()
        default_channel = next((str(i) for i in range(1, INPUT_COUNT + 1) if i not in self._inputs), "1")
        default_name = f"Input {default_channel}"
        return self.async_show_form(
            step_id="add_input",
            data_schema=vol.Schema(
                {
                    vol.Required("channel", default=default_channel): _channel_selector(
                        INPUT_COUNT
                    ),
                    vol.Required("name", default=default_name): str,
                    vol.Optional("link"): selector({"entity": {"domain": "media_player"}}),
                }
            ),
        )

    async def async_step_add_output(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            ch = int(user_input["channel"])
            name = user_input["name"]
            self._outputs[ch] = {"name": name}
            return await self.async_step_init()
        default_channel = next((str(i) for i in range(1, OUTPUT_COUNT + 1) if i not in self._outputs), "1")
        default_name = f"Output {default_channel}"
        return self.async_show_form(
            step_id="add_output",
            data_schema=vol.Schema(
                {
                    vol.Required("channel", default=default_channel): _channel_selector(
                        OUTPUT_COUNT
                    ),
                    vol.Required("name", default=default_name): str,
                }
            ),
        )


async def _async_has_devices(hass: HomeAssistant) -> bool:
    devices = []
    return len(devices) > 0
