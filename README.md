# Controme Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)

![Integration Example](https://github.com/ordo01/homeassistant-controme-integration/blob/main/Example.png)

Home Assistant integration for Controme heating systems. This integration allows you to control and monitor your Controme heating system through Home Assistant.

## Features

- Temperature control for each room
- Current temperature monitoring
- Humidity monitoring
- Return temperature sensors
- Total offset display
- Operation mode status
- Heating output in % per room
- Automatic updates every 60 seconds

## Installation

### HACS (Recommended)
1. Add this repository to HACS as a custom repository
2. Install the "Controme" integration
3. Restart Home Assistant

### Manual Installation
1. Copy the `custom_components/controme` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to Settings -> Devices & Services
2. Click "Add Integration"
3. Search for "Controme"
4. Enter your Controme API details:
   - API URL (e.g., http://192.168.1.100/)
   - Username
   - Password

   These same credentials are also used to read the heating output sensor from the
   Controme web UI (which has no separate JSON API) - the integration logs in and
   refreshes that session on its own.

## Entities Created

For each room, the integration creates:

### Climate Entity
- Controls room temperature
- Shows current and target temperature
- Shows current humidity
- Supports heating mode

### Sensors
- Current Temperature
- Target Temperature
- Humidity
- Return Temperature (if available)
- Total Offset
- Operation Mode
- Heating Output %

## Supported Languages
- English
- German (Deutsch)

## Requirements
- Home Assistant 2024.1.0 or newer
- Controme heating system with API access

## Support

If you have any issues or feature requests, please:
1. Check the [Issues](https://github.com/ordo01/homeassistant-controme-integration/issues) page
2. Create a new issue if your problem isn't already listed

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

[releases-shield]: https://img.shields.io/github/release/ordo01/homeassistant-controme-integration.svg
[releases]: https://github.com/flame4ever/homeassistant-controme-integration/releases
[license-shield]: https://img.shields.io/github/license/ordo01/homeassistant-controme-integration.svg
