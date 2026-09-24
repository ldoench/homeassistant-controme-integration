"""The Controme integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.exceptions import ConfigEntryNotReady
from .coordinator import ContromeDataUpdateCoordinator
from .const import (
    DOMAIN,
    CONF_HAUS_ID,
    CONF_API_URL,
    CONF_USER,
    CONF_PASSWORD,
    CONF_DURATION_OPTION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.CLIMATE]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Controme component."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Controme from a config entry."""
    coordinator = ContromeDataUpdateCoordinator(
        hass,
        entry.data[CONF_API_URL],
        entry.data[CONF_HAUS_ID],
        entry.data[CONF_USER],
        entry.data[CONF_PASSWORD],
    )
    
    await coordinator.async_config_entry_first_refresh()

    if not coordinator.data or not isinstance(coordinator.data, list):
        raise ConfigEntryNotReady(
            f"Unexpected data format from Controme API: {type(coordinator.data)}"
        )

    entry.runtime_data = coordinator

    # Register the main Controme hub device
    device_registry = dr.async_get(hass)
    hub_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.data[CONF_HAUS_ID])},
        manufacturer="Controme",
        name=f"Controme Home {entry.data[CONF_HAUS_ID]}",
        model="Thermostat API",
    )
    coordinator.hub_device_id = hub_device.id

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_cleanup_stale_devices(hass, entry, coordinator.data)

    return True

def _async_cleanup_stale_devices(
    hass: HomeAssistant, entry: ConfigEntry, data: list
) -> None:
    """Remove device registry entries for rooms that no longer exist."""
    dev_reg = dr.async_get(hass)
    hub_id = entry.data[CONF_HAUS_ID]

    current_ids = set()
    for floor in data:
        floor_id = floor.get("id")
        for room in floor.get("raeume", []):
            room_id = room.get("id")
            if room_id:
                current_ids.add(f"{hub_id}_{floor_id}_{room_id}")

    for device_entry in list(dev_reg.devices.values()):
        if entry.entry_id not in device_entry.config_entries:
            continue
        for domain, identifier in device_entry.identifiers:
            if domain != DOMAIN:
                continue
            if identifier == hub_id:
                continue
            if identifier not in current_ids:
                dev_reg.async_remove_device(device_entry.id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry."""
    if entry.version == 1:
        if CONF_DURATION_OPTION not in entry.options:
            hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, CONF_DURATION_OPTION: "default"},
            )
    return True