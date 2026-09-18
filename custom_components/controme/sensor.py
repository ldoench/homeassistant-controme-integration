"""Support for Controme sensors."""
import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfTemperature,
    PERCENTAGE,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device import link_to_hub
from .const import (
    DOMAIN, 
    CONF_API_URL, 
    CONF_HAUS_ID,
    VALUE_MAP,
    SENSOR_TYPE_OPERATION_MODE,
)

from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1

@dataclass
class ContromeSensorEntityDescription(SensorEntityDescription):
    """Describes Controme sensor entity."""

SENSOR_TYPES: tuple[ContromeSensorEntityDescription, ...] = (
    ContromeSensorEntityDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ContromeSensorEntityDescription(
        key="target",
        translation_key="target",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ContromeSensorEntityDescription(
        key="return",
        translation_key="return",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ContromeSensorEntityDescription(
        key="total_offset",
        translation_key="total_offset",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ContromeSensorEntityDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up the Controme sensor platform."""
    sensors = []
    coordinator = entry.runtime_data
    data = coordinator.data
    house_id = entry.data[CONF_HAUS_ID]

    # Create hub device
    hub_device_info = DeviceInfo(
        identifiers={(DOMAIN, house_id)},
        name="Controme Hub",
        manufacturer="Controme",
        model="Hub",
    )

    _LOGGER.debug("Setting up Controme sensors with data: %s", data)

    if not data:
        _LOGGER.error("No data received from coordinator")
        return

    # Process all floors and rooms
    for floor in data:
        floor_id = floor.get("id")
        floor_name = floor.get("etagenname", f"Floor {floor_id}")
        rooms = floor.get("raeume", [])
        _LOGGER.debug("Processing floor %s with rooms: %s", floor_id, rooms)
        
        if not rooms and ("temperatur" in floor or "solltemperatur" in floor):
            rooms = [floor]
            _LOGGER.debug("Using floor as room because no rooms found")
            
        for index, room in enumerate(rooms):
            room_id = room.get("id")
            if not room_id:
                room_id = f"{floor_id}_{index}"
            room_name = room.get("name", f"Room {room_id}")
            _LOGGER.debug("Processing room %s with data: %s", room_name, room)

            # Add room data
            room["floor_id"] = floor_id
            device_info = link_to_hub(
                DeviceInfo(
                    identifiers={(DOMAIN, f"{house_id}_{floor_id}_{room_id}")},
                    name=room_name,
                    manufacturer="Controme",
                    model="Room",
                ),
                coordinator.hub_device_id,
                house_id,
            )

            # Add basic sensors
            for sensor_type, data_key in VALUE_MAP.items():
                _LOGGER.debug("Checking for %s sensor (key: %s) in room data: %s", 
                            sensor_type, data_key, data_key in room)
                if data_key in room:
                    _LOGGER.debug("Adding %s sensor for room %s", sensor_type, room_name)
                    if sensor_type == "operation_mode":
                        sensor_class = ContromeOperationModeSensor
                    else:
                        sensor_class = ContromeSensor
                    sensors.append(
                        sensor_class(
                            coordinator,
                            entry,
                            room,
                            sensor_type,
                            device_info,
                        )
                    )
                    _LOGGER.debug("%s sensor added", sensor_type)

            # Process return temperature sensors
            for sensor in room.get("sensoren", []):
                if (sensor.get("raumtemperatursensor", "") == False):
                    _LOGGER.debug("Sensor value: %s (is_float: %s)", sensor.get("wert"), isinstance(sensor.get("wert"), float))
                    if (isinstance(sensor.get("wert"), float)):
                        _LOGGER.debug("Adding return sensor %s for room %s", 
                                sensor.get("name"), room_name)
                        sensors.append(
                            ContromeSensor(
                                coordinator,
                                entry,
                                room,
                                f"return_{sensor.get('name')}",
                                device_info,
                            )
                        )
                    _LOGGER.debug("Return sensor added")

    _LOGGER.debug("Created %d sensors in total", len(sensors))
    async_add_entities(sensors)

class ContromeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Controme Sensor."""

    _attr_has_entity_name = True

    def __init_sensor_description(self, sensor_type: str) -> None:
        """Initialize the sensor description based on type."""
        base_type = sensor_type.split("_")[0]
        self.entity_description = next(
            (desc for desc in SENSOR_TYPES if desc.key == sensor_type or desc.key == base_type),
            SENSOR_TYPES[0]
        )

    def __init__(self, coordinator, config_entry, room_data, sensor_type, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        _LOGGER.debug("Initializing sensor with type %s for room %s", 
                    sensor_type, room_data.get("name"))
        
        # Set basic attributes
        self._config_entry = config_entry
        self._device_info = device_info
        self._room_data = room_data
        self._sensor_type = sensor_type
        self._room_id = room_data.get("id")
        self._floor_id = room_data.get("floor_id")
        self._house_id = config_entry.data[CONF_HAUS_ID]
        self._base_url = config_entry.data[CONF_API_URL].rstrip('/')
        
        # Set unique ID
        self._attr_unique_id = f"{self._house_id}_{self._floor_id}_{self._room_id}_{sensor_type}"
        self.__init_sensor_description(sensor_type)

        if self._sensor_type.startswith("return_"):
            self._attr_name = self._sensor_type[len("return_"):]

        # Set initial values
        self._update_from_data(room_data)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._attr_native_value is not None

    @property
    def device_info(self):
        """Return device info for this sensor."""
        return self._device_info

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

    def _update_from_data(self, room_data):
        """Update sensor state from room data."""
        if self._sensor_type.startswith("return_"):
            for sensor in room_data.get("sensoren", []):
                sensor_id = "_".join(self._sensor_type.split("_")[1:])
                if sensor.get("name") == sensor_id:
                    value = sensor.get("wert")
                    if isinstance(value, str) and not value.replace('.', '', 1).isdigit():
                        self._attr_native_value = None
                    else:
                        self._attr_native_value = value
                    break
        else:
            value = room_data.get(VALUE_MAP.get(self._sensor_type))
            if self.entity_description.device_class in [
                SensorDeviceClass.TEMPERATURE, 
                SensorDeviceClass.HUMIDITY
            ]:
                if not value or (isinstance(value, str) and not value.replace('.', '', 1).isdigit()):
                    self._attr_native_value = None
                else:
                    try:
                        self._attr_native_value = float(value) if value is not None else None
                    except (ValueError, TypeError):
                        self._attr_native_value = None
            else:
                self._attr_native_value = value

class ContromeOperationModeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Controme Operation Mode Sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, config_entry, room_data, sensor_type, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._device_info = device_info
        self._room_data = room_data
        self._room_id = room_data.get("id")
        self._floor_id = room_data.get("floor_id")
        self._house_id = config_entry.data[CONF_HAUS_ID]
        
        # Set unique ID
        self._attr_unique_id = f"{self._house_id}_{self._floor_id}_{self._room_id}_operation_mode"

        # Set entity description
        self.entity_description = ContromeSensorEntityDescription(
            key="operation_mode",
            translation_key="operation_mode",
            device_class=None,
            state_class=None,
            native_unit_of_measurement=None,
            has_entity_name=True,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

        # Set initial value and availability
        self._update_from_data(room_data)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._attr_native_value is not None

    @property
    def device_info(self):
        """Return device info for this sensor."""
        return self._device_info

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        updated = False
        for floor in self.coordinator.data:
            if floor["id"] == self._floor_id:
                for room in floor.get("raeume", []):
                    if room["id"] == self._room_id:
                        self._update_from_data(room)
                        updated = True
                        break
                if updated:
                    break
        
        self.async_write_ha_state()
        
    def _update_from_data(self, room_data):
        """Update the sensor state from room data."""
        value = room_data.get(VALUE_MAP["operation_mode"])
        self._attr_native_value = value