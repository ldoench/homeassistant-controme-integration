"""DataUpdateCoordinator for Controme integration."""

import asyncio
from datetime import timedelta
import logging
from typing import Any, Dict

import aiohttp
from aiohttp import ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

PERMISSIONS_ENDPOINT = "permissions"
OUTPUTS_ENDPOINT = "outs"
MARKER_ENDPOINT = "marker"
SCENES_ENDPOINT = "temperaturszenen"
PROGRAM_ENDPOINT = "heizprogramm"

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = ClientTimeout(total=10)


class ContromeDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching Controme data."""

    def __init__(
        self,
        hass: HomeAssistant,
        base_url: str,
        house_id: str,
        username: str,
        password: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
        )
        self._base_url = base_url
        self._house_id = house_id
        self._username = username
        self._password = password
        self.hub_device_id: str | None = None
        self.permissions: Dict[str, bool] = {
            "can_make_permanent_changes": True,
            "can_make_temporary_changes": True,
        }
        # House-level data from further read-only endpoints, refreshed with
        # every update. Each stays at its last value's shape (empty) when its
        # endpoint fails or the Controme module behind it is not active.
        self.markers: list[dict[str, Any]] = []
        self.scenes: list[dict[str, Any]] = []
        self.switch_points: list[dict[str, Any]] = []

    @staticmethod
    def _normalize_output(raw: Any) -> int | None:
        """Convert one raw ``/outs/`` value to a 0-100 % opening.

        ``/outs/`` returns what the Miniserver last sent to the gateway output
        (the same ``lastout_*`` cache entry the web UI's "Regelschritt" bar is
        drawn from), but unlike the web UI it does not scale it:

        - Relay gateways (firmware < 5.00, and the Ruecklaufregelung /
          Zweipunktregelung on any gateway) switch 0/1 - a thermal actuator is
          either powered or not, there is no intermediate position.
        - Analog 0-10 V gateways (firmware 5.x) report the opening as 0-99.

        So 1 means "on" and maps to 100 % (the web UI does the same for relay
        gateways, but shows a Ruecklaufregelung "on" on a 5.x gateway as 1 %,
        which is misleading). An analog output at exactly 1 % would be misread
        as fully open, which is acceptable: the API does not expose the gateway
        firmware to tell them apart, and 1 % is not a meaningful opening.
        """
        if raw is None:
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return 0
        if value == 1:
            return 100
        return min(value, 100)

    async def _async_merge_heating_output(
        self, session: aiohttp.ClientSession, auth: aiohttp.BasicAuth, data: list
    ) -> None:
        """Fetch the heating output per room from ``/outs/`` and merge it in.

        Best-effort: a failure here leaves ``heating_output`` as None for this
        cycle rather than failing the whole update - the temperature sensors
        must keep working regardless. A room with several gateway outputs
        reports their mean opening.
        """
        outs_data = await self._async_get_json(session, auth, OUTPUTS_ENDPOINT)
        outputs_by_room: Dict[int, list[int]] = {}
        for floor in outs_data if isinstance(outs_data, list) else []:
            for room in floor.get("raeume", []):
                values = [
                    value
                    for value in map(
                        self._normalize_output,
                        (room.get("ausgang") or {}).values(),
                    )
                    if value is not None
                ]
                if room.get("id") is not None and values:
                    outputs_by_room[room["id"]] = values

        for floor in data:
            for room in floor.get("raeume", []):
                values = outputs_by_room.get(room.get("id"))
                room["heating_output"] = (
                    round(sum(values) / len(values)) if values else None
                )

    async def _async_get_json(
        self, session: aiohttp.ClientSession, auth: aiohttp.BasicAuth, name: str
    ) -> Any:
        """GET one JSON API endpoint of this house, None on any failure."""
        endpoint = f"{self._base_url}/get/json/v1/{self._house_id}/{name}/"
        try:
            async with session.get(
                endpoint, auth=auth, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status != 200:
                    _LOGGER.debug("%s returned status %s", name, response.status)
                    return None
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as ex:
            _LOGGER.debug("Failed to fetch %s: %s", name, ex)
            return None

    async def _async_fetch_house_extras(
        self, session: aiohttp.ClientSession, auth: aiohttp.BasicAuth
    ) -> None:
        """Fetch sensor markers, temperature scenes and heating-program switches.

        Best-effort like the heating output: these feed optional entities
        only, so a failure must not fail the coordinator update.
        """
        markers, scenes, switch_points = await asyncio.gather(
            self._async_get_json(session, auth, MARKER_ENDPOINT),
            self._async_get_json(session, auth, SCENES_ENDPOINT),
            self._async_get_json(session, auth, PROGRAM_ENDPOINT),
        )
        self.markers = markers if isinstance(markers, list) else []
        # Without the corresponding Controme module these endpoints answer {}.
        self.scenes = scenes if isinstance(scenes, list) else []
        self.switch_points = switch_points if isinstance(switch_points, list) else []

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from Controme API."""
        last_exception: Exception | None = None
        endpoint = f"{self._base_url}/get/json/v1/{self._house_id}/temps/"
        permissions_endpoint = (
            f"{self._base_url}/get/json/v1/{self._house_id}/{PERMISSIONS_ENDPOINT}/"
        )

        for attempt in range(2):
            try:
                session = async_get_clientsession(self.hass)
                auth = aiohttp.BasicAuth(self._username, self._password)
                start_time = self.hass.loop.time()
                async with session.get(
                    endpoint, auth=auth, timeout=REQUEST_TIMEOUT
                ) as response:
                    if response.status == 401:
                        raise ConfigEntryAuthFailed(
                            "Authentication failed for Controme API"
                        )
                    if response.status != 200:
                        msg = f"Error fetching data: {response.status}"
                        if attempt == 0:
                            _LOGGER.warning("%s (attempt 1/2, retrying...)", msg)
                            await asyncio.sleep(2)
                            continue
                        raise UpdateFailed(msg)
                    data = await response.json()

                async with session.get(
                    permissions_endpoint, auth=auth, timeout=REQUEST_TIMEOUT
                ) as permissions_response:
                    if permissions_response.status == 401:
                        raise ConfigEntryAuthFailed(
                            "Authentication failed for Controme API"
                        )
                    if permissions_response.status == 200:
                        permissions_data = await permissions_response.json()
                        self.permissions = {
                            "can_make_permanent_changes": bool(
                                permissions_data.get("can_make_permanent_changes", True)
                            ),
                            "can_make_temporary_changes": bool(
                                permissions_data.get("can_make_temporary_changes", True)
                            ),
                        }
                    else:
                        _LOGGER.debug(
                            "Permissions endpoint returned status %s; continuing with defaults",
                            permissions_response.status,
                        )

                fetch_time = self.hass.loop.time() - start_time
                _LOGGER.debug(
                    "Finished fetching controme data in %.3f seconds (success: True)",
                    fetch_time,
                )

                if data and isinstance(data, list) and len(data) > 0:
                    _LOGGER.debug("Received data for %d floors", len(data))
                    first_floor = data[0]
                    if "raeume" in first_floor and first_floor["raeume"]:
                        sample_room = first_floor["raeume"][0]
                        safe_sample = {
                            k: v
                            for k, v in sample_room.items()
                            if k not in ["password", "token"]
                        }
                        _LOGGER.debug("Sample room data: %s", safe_sample)

                await asyncio.gather(
                    self._async_merge_heating_output(session, auth, data),
                    self._async_fetch_house_extras(session, auth),
                )

                return data
            except ConfigEntryAuthFailed:
                raise
            except UpdateFailed:
                raise
            except asyncio.TimeoutError:
                last_exception = asyncio.TimeoutError("Request timed out")
                _LOGGER.warning(
                    "Timeout fetching Controme data (attempt %d/2)", attempt + 1
                )
                if attempt == 0:
                    await asyncio.sleep(2)
            except Exception as ex:
                last_exception = ex
                _LOGGER.warning(
                    "Error communicating with API: %s (attempt %d/2)", ex, attempt + 1
                )
                if attempt == 0:
                    await asyncio.sleep(2)

        raise UpdateFailed(f"Error communicating with API: {last_exception}")
