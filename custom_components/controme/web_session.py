"""Session-cookie based access to the Controme web UI.

The public JSON API (``/get/json/v1/<haus>/temps/``) does not expose the
current heating output ("Regelschritt") per room - that value only lives in
the logged-in web UI, in an AJAX fragment used by the room cards. There is no
token/API-key auth for this; the UI uses a plain Django session cookie
obtained via a normal email/password login form. Controme accepts the same
account for this as for the JSON API's Basic Auth, so this reuses the
existing API user/password rather than asking for separate credentials.

This module logs in and keeps the resulting session cookie alive,
transparently re-authenticating when it expires.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import aiohttp
from aiohttp import ClientTimeout

_LOGGER = logging.getLogger(__name__)

LOGIN_PATH = "/accounts/m_login/"
ROOM_FRAGMENT_PATH = "/m_raum_temp_html/{room_id}/"

REQUEST_TIMEOUT = ClientTimeout(total=10)

_CSRF_RE = re.compile(r"name=['\"]csrfmiddlewaretoken['\"] value=['\"]([^'\"]+)['\"]")
_BEAM_RE = re.compile(r'class="beam-width-value"\s+value="([\d.]+)"')


class ContromeWebAuthError(Exception):
    """Raised when the web-UI login fails (wrong credentials)."""


class ContromeWebSession:
    """Manages a logged-in session against the Controme web UI."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        # Dedicated session/cookie jar: this must NOT be Home Assistant's
        # shared aiohttp session, since we rely on the Django session cookie
        # sticking around between requests without leaking into other
        # integrations' requests. `unsafe=True` is required because Controme
        # is normally reached by bare LAN IP - aiohttp's cookie jar silently
        # drops cookies for IP hosts otherwise.
        self._session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True)
        )
        self._authenticated = False

    async def async_close(self) -> None:
        """Close the underlying HTTP session."""
        await self._session.close()

    async def async_get_regelschritt(self, room_id: int) -> Optional[float]:
        """Return the current heating output (0-100%) for a room, or None."""
        if not self._authenticated:
            await self._async_login()

        value = await self._async_fetch_regelschritt(room_id)
        if value is not None:
            return value

        # Session likely expired - log in once more and retry.
        _LOGGER.debug("Regelschritt fetch failed, re-authenticating and retrying")
        self._authenticated = False
        await self._async_login()
        return await self._async_fetch_regelschritt(room_id)

    async def _async_fetch_regelschritt(self, room_id: int) -> Optional[float]:
        url = f"{self._base_url}{ROOM_FRAGMENT_PATH.format(room_id=room_id)}"
        async with self._session.get(
            url, timeout=REQUEST_TIMEOUT, allow_redirects=False
        ) as response:
            if response.status != 200:
                # A 302 back to the login page means the session expired.
                return None
            html = await response.text()

        match = _BEAM_RE.search(html)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    async def _async_login(self) -> None:
        """Log in via the Django session-cookie login form."""
        login_url = f"{self._base_url}{LOGIN_PATH}"

        async with self._session.get(login_url, timeout=REQUEST_TIMEOUT) as response:
            html = await response.text()

        csrf_match = _CSRF_RE.search(html)
        if not csrf_match:
            raise ContromeWebAuthError("Could not find CSRF token on login page")
        csrf_token = csrf_match.group(1)

        async with self._session.post(
            login_url,
            data={
                "csrfmiddlewaretoken": csrf_token,
                "mail": self._username,
                "pw": self._password,
            },
            headers={"Referer": login_url},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        ) as response:
            location = response.headers.get("Location", "")
            if response.status != 302 or LOGIN_PATH in location:
                raise ContromeWebAuthError(
                    "Controme web login failed - check user/password"
                )

        self._authenticated = True
        _LOGGER.debug("Controme web-UI login succeeded")
