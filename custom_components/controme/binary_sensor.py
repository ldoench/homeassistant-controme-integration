"""Support for Controme binary sensors."""
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HAUS_ID, DOMAIN
from .device import link_to_hub

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1

# Controme colours each device by the age of its last transmission
# (lightgreen/green/yellow); red means it has not been heard from for too long.
MARKER_DISCONNECTED = "red"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up the Controme binary sensor platform."""
    coordinator = entry.runtime_data
    house_id = entry.data[CONF_HAUS_ID]
    hub_device = DeviceInfo(identifiers={(DOMAIN, house_id)})

    # Sensors that are assigned to a room belong on that room's device and
    # take its description (e.g. "Hülsenfühler Bad") as their name; the rest
    # (gateways, unassigned radio sensors) go on the hub.
    room_sensors = {}
    for floor in coordinator.data:
        for room in floor.get("raeume", []):
            device_info = link_to_hub(
                DeviceInfo(
                    identifiers={(DOMAIN, f"{house_id}_{floor.get('id')}_{room.get('id')}")},
                    name=room.get("name"),
                    manufacturer="Controme",
                    model="Room",
                ),
                coordinator.hub_device_id,
                house_id,
            )
            for sensor in room.get("sensoren", []):
                room_sensors[sensor.get("name")] = (
                    device_info,
                    sensor.get("beschreibung") or sensor.get("name"),
                )

    entities = []
    for controller in coordinator.markers:
        gateway = controller.get("name")
        entities.append(
            ContromeConnectivitySensor(coordinator, house_id, gateway, None, gateway, hub_device)
        )
        for sensor in controller.get("sensoren", {}):
            device_info, label = room_sensors.get(sensor, (hub_device, sensor))
            entities.append(
                ContromeConnectivitySensor(coordinator, house_id, gateway, sensor, label, device_info)
            )

    async_add_entities(entities)


class ContromeConnectivitySensor(CoordinatorEntity, BinarySensorEntity):
    """Whether Controme still receives data from a gateway or sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, house_id, gateway, sensor, label, device_info):
        """Initialize the sensor; ``sensor`` is None for the gateway itself."""
        super().__init__(coordinator)
        self._gateway = gateway
        self._sensor = sensor
        self._attr_unique_id = f"{house_id}_connectivity_{gateway}_{sensor or 'gateway'}"
        self._attr_translation_placeholders = {"device": label}
        self._attr_device_info = device_info
        self._update_from_coordinator()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._marker is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_from_coordinator()
        self.async_write_ha_state()

    def _update_from_coordinator(self) -> None:
        controller = next(
            (c for c in self.coordinator.markers if c.get("name") == self._gateway),
            None,
        )
        if controller is None:
            self._marker = None
        elif self._sensor is None:
            self._marker = controller.get("marker")
        else:
            self._marker = controller.get("sensoren", {}).get(self._sensor)

        self._attr_is_on = (
            None if self._marker is None else self._marker != MARKER_DISCONNECTED
        )
        self._attr_extra_state_attributes = {
            "marker": self._marker,
            "gateway": self._gateway,
            "sensor": self._sensor,
        }
