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
from .web_session import ContromeWebAuthError, ContromeWebSession

PERMISSIONS_ENDPOINT = "permissions"

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

        # The heating-output ("Regelschritt") sensor is scraped from the
        # logged-in web UI, which is not covered by the JSON API's Basic
        # Auth above. Controme accepts the same account for both, so this
        # reuses the API username/password rather than asking for separate
        # web-UI credentials.
        self._web_session = ContromeWebSession(base_url, username, password)
        self._web_auth_failed_logged = False

    async def async_close(self) -> None:
        """Release resources held by the coordinator."""
        await self._web_session.async_close()

    async def _async_merge_heating_output(self, data: list) -> None:
        """Fetch the heating-output percentage per room and merge it in.

        Best-effort: any failure here (wrong web credentials, UI unreachable,
        page layout changed) is logged and leaves ``heating_output`` as None
        for this cycle rather than failing the whole update - the temperature
        sensors must keep working regardless.
        """
        for floor in data:
            for room in floor.get("raeume", []):
                room_id = room.get("id")
                if room_id is None:
                    continue
                try:
                    room["heating_output"] = await self._web_session.async_get_regelschritt(
                        room_id
                    )
                except ContromeWebAuthError:
                    if not self._web_auth_failed_logged:
                        _LOGGER.warning(
                            "Controme web-UI login failed with the configured "
                            "user/password. Heating output sensors will be "
                            "unavailable until this is fixed"
                        )
                        self._web_auth_failed_logged = True
                    room["heating_output"] = None
                    continue
                except Exception as ex:  # noqa: BLE001
                    _LOGGER.debug(
                        "Failed to fetch heating output for room %s: %s", room_id, ex
                    )
                    room["heating_output"] = None
                    continue
                self._web_auth_failed_logged = False

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

                await self._async_merge_heating_output(data)

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
