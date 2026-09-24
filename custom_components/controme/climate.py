"""Support for Controme climate devices."""

import logging
from typing import Any
from datetime import timedelta

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from aiohttp import ClientTimeout
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
)

from .device import link_to_hub
from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_HAUS_ID,
    CONF_USER,
    CONF_PASSWORD,
    CONF_DURATION_OPTION,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)
REQUEST_TIMEOUT = ClientTimeout(total=10)  # 10 Sekunden Timeout
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Set up the Controme climate platform."""
    climate_devices = []
    coordinator = entry.runtime_data
    data = coordinator.data
    house_id = entry.data[CONF_HAUS_ID]

    # Process all floors and rooms
    for floor in data:
        floor_id = floor.get("id")
        floor_name = floor.get("etagenname", f"Floor {floor_id}")
        rooms = floor.get("raeume", [])

        if not rooms and ("temperatur" in floor or "solltemperatur" in floor):
            rooms = [floor]

        for index, room in enumerate(rooms):
            room_id = room.get("id")
            if not room_id:
                room_id = f"{floor_id}_{index}"
            room_name = room.get("name", f"Room {room_id}")
            room["floor_id"] = floor_id

            device_info = link_to_hub(
                DeviceInfo(
                    identifiers={(DOMAIN, f"{house_id}_{floor_id}_{room_id}")},
                    name=room_name,
                    manufacturer="Controme",
                    model="Thermostat API",
                ),
                coordinator.hub_device_id,
                house_id,
            )

            climate_devices.append(
                ContromeClimate(
                    coordinator,
                    entry,
                    room,
                    device_info,
                )
            )

    async_add_entities(climate_devices)


class ContromeClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a Controme Climate device."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "controme"

    def __init__(self, coordinator, config_entry, room_data, device_info):
        """Initialize the climate device."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._base_url = config_entry.data[CONF_API_URL].rstrip("/")
        self._device_info = device_info
        self._room_data = room_data
        self._room_id = room_data.get("id")
        self._floor_id = room_data.get("floor_id")
        self._house_id = config_entry.data[CONF_HAUS_ID]
        self._user = config_entry.data[CONF_USER]
        self._password = config_entry.data[CONF_PASSWORD]
        self._attr_unique_id = f"{config_entry.data[CONF_HAUS_ID]}_{self._floor_id}_{self._room_id}_climate"
        self._update_from_data(room_data)

        # Set supported features
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

        # Set temperature settings
        self._attr_target_temperature_step = 0.5
        self._attr_min_temp = 5
        self._attr_max_temp = 30
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS

        # Set HVAC modes (removed, now a property)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._attr_current_temperature is not None

    @property
    def _permissions(self) -> dict[str, bool]:
        """Return the latest permission flags from the coordinator."""
        coordinator = getattr(self, "coordinator", None)
        if coordinator is None:
            return {}
        return getattr(coordinator, "permissions", {})

    def _can_change_temperature(self) -> bool:
        """Return if temperature changes are permitted."""
        permissions = self._permissions
        return permissions.get("can_make_temporary_changes", True) or permissions.get(
            "can_make_permanent_changes", True
        )

    def _update_from_data(self, data):
        """Update attrs from data."""
        self._attr_current_temperature = data.get("temperatur")
        self._attr_target_temperature = data.get("solltemperatur")
        betriebsart = (data.get("betriebsart") or "").lower()
        if betriebsart == "heating":
            self._attr_hvac_mode = HVACMode.HEAT
        elif betriebsart == "cooling":
            self._attr_hvac_mode = HVACMode.COOL
        else:
            self._attr_hvac_mode = HVACMode.OFF

        # "betriebsart" is the plant's operating mode (heating season) and
        # stays "heating" all winter, so on its own HA would always show
        # "Heating". Whether the room is actually heating right now comes
        # from the scraped Regelschritt (valve output 0-100 %).
        heating_output = data.get("heating_output")
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_action = HVACAction.OFF
        elif heating_output is None:
            self._attr_hvac_action = None
        elif heating_output > 0:
            self._attr_hvac_action = (
                HVACAction.COOLING
                if self._attr_hvac_mode == HVACMode.COOL
                else HVACAction.HEATING
            )
        else:
            self._attr_hvac_action = HVACAction.IDLE

        # Handle humidity values - set to 0 if no value is available
        humidity = data.get("luftfeuchte")
        if humidity in ("kein aktueller Wert vorhanden", "kein Sensor vorhanden"):
            _LOGGER.debug("No valid humidity sensor, setting to 0")
            self._attr_current_humidity = 0.0
        else:
            _LOGGER.debug("Raw humidity value: %s", humidity)
            self._attr_current_humidity = humidity

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        for floor in self.coordinator.data:
            if floor["id"] == self._floor_id:
                for room in floor.get("raeume", []):
                    if room["id"] == self._room_id:
                        self._update_from_data(room)
                        break
        self.async_write_ha_state()

    @property
    def device_info(self):
        """Return device info."""
        return self._device_info

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        if not self._can_change_temperature():
            _LOGGER.warning(
                "Temperature changes are not permitted for this Controme account"
            )
            return

        session = async_get_clientsession(self.hass)
        # Remove trailing slash from base_url if present
        base_url = self._base_url.rstrip("/")
        endpoint = f"{base_url}/set/json/v1/{self._house_id}/ziel/{self._room_id}/"
        duration = self._config_entry.options.get(CONF_DURATION_OPTION, "default")
        data = {
            "user": self._user,
            "password": self._password,
            "ziel": str(float(temperature)),
            "duration": duration,
        }

        try:
            # Log request details for debugging
            _LOGGER.debug(
                "Setting temperature: URL=%s, Data=%s",
                endpoint,
                {**data, "password": "***"},
            )

            async with session.post(
                endpoint,
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            ) as response:
                response_text = await response.text()
                if response.status != 200:
                    if response.status == 403:
                        _LOGGER.error(
                            "Authentication failed when setting temperature. Check your credentials."
                        )
                        _LOGGER.debug(
                            "Auth failed: URL=%s, User=%s, Response=%s",
                            endpoint,
                            self._user,
                            response_text,
                        )
                    else:
                        _LOGGER.error(
                            "Error setting temperature: status=%s, response=%s",
                            response.status,
                            response_text,
                        )
                    return
                else:
                    _LOGGER.debug("Successfully set temperature: %s", response_text)

                    # Set local value immediately for responsive UI
                    self._attr_target_temperature = temperature
                    self.async_write_ha_state()

                    # Request an immediate data refresh to update all entities
                    _LOGGER.debug(
                        "Requesting immediate data refresh after temperature change"
                    )
                    await self.coordinator.async_refresh()

        except Exception as ex:
            _LOGGER.exception("Exception during setting temperature: %s", ex)
            return

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if not self._can_change_temperature():
            _LOGGER.warning(
                "HVAC mode changes are not permitted for this Controme account"
            )
            return

        if hvac_mode == HVACMode.COOL:
            api_value = "cooling"
        elif hvac_mode == HVACMode.OFF:
            api_value = "off"
        else:
            api_value = "heating"

        session = async_get_clientsession(self.hass)
        endpoint = (
            f"{self._base_url}/set/json/v1/{self._house_id}/rooms/{self._room_id}/"
        )
        data = {
            "user": self._user,
            "password": self._password,
            "action": "betriebsart",
            "value": api_value,
        }

        try:
            async with session.post(endpoint, data=data) as response:
                if response.status != 200:
                    _LOGGER.error("Failed to set hvac mode: status=%s", response.status)
                    return
        except Exception as ex:
            _LOGGER.exception("Exception during setting hvac mode: %s", ex)
            return

        await self.coordinator.async_refresh()

    @property
    def hvac_modes(self):
        """Return the list of available hvac modes."""
        return [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]
