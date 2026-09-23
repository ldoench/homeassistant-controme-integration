# Changelog

## Unreleased

### Enhancements
- **Heating output sensor**: New sensor per room showing the current heating output (0-100%),
  which is not exposed by the public JSON API - only the logged-in Controme web UI has it. Reuses
  the existing API username/password to log in and re-authenticates automatically when the
  session expires, no manual session-cookie copying needed.

## 1.2.0 (2027-07-31)

### Enhancements
- **Rewrite of the integration**: Rewrite of the integration to make it more robust and compliant with homeassistant integration developer guidelines.
- **House ID configurable**: Make house id configurable.
- **Added translations**: Added missing translations.
- **Duration for temperature change configurable**: Added configuration option for duration of temporary temperature changes.

## 1.1.3 (2026-01-06)

### Enhancements
- **Make return sensor creation more robust**: Changed dependency for creating return sensor on translation to evaluation of flag "raumtemperatursensor".
- **Temperature changes now temporary**: Changed the behavior of the target temperature setting to perform a temporary change with the default duration for a temporary change configured through the controme web UI.

### Bug Fixes
- **Removed hard coded house id**: Now the hard coded house id is removed in all places.

## 1.1.2 (2025-03-19)

### Enhancements
- **Improved API Efficiency**: Removed redundant API calls by optimizing the data update process through the coordinator
- **Immediate Updates**: Climate entities now trigger an immediate data refresh after temperature changes for consistent state across all entities
- **Better Logging**: Added detailed data logging in the coordinator for improved debugging capabilities

### Bug Fixes
- **Error Handling**: Fixed error "could not convert string to float" for non-numeric sensor values like "kein Sensor vorhanden"
- **Sensor Availability**: Non-numeric values for temperature/humidity sensors now correctly mark the entity as unavailable instead of failing
- **Mode Sensor Improvements**: Made the operation mode sensor more robust with better data handling

### Under the Hood
- **Code Optimization**: Streamlined the entity update process to minimize server requests
- **Better Error Reporting**: More detailed error information in logs
- **Coordinator Improvements**: Enhanced the DataUpdateCoordinator with better timing metrics
