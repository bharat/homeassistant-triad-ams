"""Coordinator for Triad AMS integration."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .helper import TriadAmsClient

_LOGGER = logging.getLogger(__name__)


class TriadAmsCoordinator(DataUpdateCoordinator):
    """Data update coordinator for Triad AMS."""

    def __init__(
        self, hass: HomeAssistant, client: TriadAmsClient, config_entry: ConfigEntry
    ) -> None:
        """Initialize the Triad AMS coordinator.

        Args:
            hass: The Home Assistant instance.
            client: The Triad AMS client for device communication.
            config_entry: The config entry for this integration.
        """
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=10),
            config_entry=config_entry,
        )
        self.client = client

    async def _async_update_data(self):
        """Fetch the latest data from the Triad AMS device."""
        try:
            return await self.client.async_get_state()
        except OSError as err:
            raise UpdateFailed(f"Error updating Triad AMS data: {err}") from err
