"""Constants for the Controme integration."""

from typing import Final
from homeassistant.const import Platform

# Integration domain
DOMAIN: Final = "controme"

# Configuration keys used in the web configuration
CONF_API_URL: Final = "api_url"
CONF_HAUS_ID: Final = "haus_id"
CONF_USER: Final = "user"
CONF_PASSWORD: Final = "password"

# Duration configuration
CONF_USE_DEFAULT_DURATION: Final = "use_default_duration"
CONF_DURATION_MINUTES: Final = "duration_minutes"
CONF_DURATION_OPTION: Final = "duration"

# Platforms are now defined in __init__.py

# New constants
SENSOR_TYPE_CURRENT = "current"
SENSOR_TYPE_TARGET = "target"
SENSOR_TYPE_HUMIDITY = "humidity"
SENSOR_TYPE_RETURN = "return"
SENSOR_TYPE_TOTAL_OFFSET = "total_offset"
SENSOR_TYPE_OPERATION_MODE = "operation_mode"
SENSOR_TYPE_HEATING_OUTPUT = "heating_output"

# Map sensor types to API data keys
VALUE_MAP = {
    SENSOR_TYPE_CURRENT: "temperatur",
    SENSOR_TYPE_TARGET: "solltemperatur",
    SENSOR_TYPE_HUMIDITY: "luftfeuchte",
    SENSOR_TYPE_TOTAL_OFFSET: "total_offset",
    SENSOR_TYPE_OPERATION_MODE: "betriebsart",
    SENSOR_TYPE_HEATING_OUTPUT: "heating_output",
}