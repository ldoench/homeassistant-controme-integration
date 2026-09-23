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

import asyncio
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


class _SessionExpired(Exception):
    """Internal signal that the session cookie is no longer valid."""


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
        # Guards _async_login so concurrent callers (multiple rooms fetched
        # in parallel) never race into logging in twice. Paired with
        # _session_generation below so that when several requests discover
        # the session expired at roughly the same time, only the first one
        # through the lock actually performs a new login - the rest see the
        # generation has already moved on and just retry with the fresh
        # cookie.
        self._login_lock = asyncio.Lock()
        self._session_generation = 0
        # Bounds how many room requests run at once. Controme boxes are
        # small embedded devices; fetching e.g. 20 rooms fully in parallel
        # would hit it with 20 simultaneous logged-in requests for no real
        # benefit over a handful at a time.
        self._request_semaphore = asyncio.Semaphore(4)

    async def async_close(self) -> None:
        """Close the underlying HTTP session."""
        await self._session.close()

    async def async_get_regelschritt(self, room_id: int) -> Optional[float]:
        """Return the current heating output (0-100%) for a room, or None."""
        await self._async_ensure_login()
        generation = self._session_generation

        async with self._request_semaphore:
            try:
                return await self._async_fetch_regelschritt(room_id)
            except _SessionExpired:
                pass

        # Only re-authenticate when the server actually told us the session
        # cookie is gone (redirect/401/403). A 200 response whose HTML just
        # didn't contain the expected value is a parse problem, not an auth
        # problem, and re-logging in on every poll for that would only
        # hammer the device for no benefit.
        _LOGGER.debug("Controme web session expired, re-authenticating and retrying")
        await self._async_relogin(after_generation=generation)
        async with self._request_semaphore:
            try:
                return await self._async_fetch_regelschritt(room_id)
            except _SessionExpired:
                return None

    async def _async_ensure_login(self) -> None:
        """Log in if no session exists yet."""
        if self._authenticated:
            return
        async with self._login_lock:
            if not self._authenticated:  # still true after acquiring the lock?
                await self._async_login()
                self._session_generation += 1

    async def _async_relogin(self, after_generation: int) -> None:
        """Force a fresh login, unless someone else already refreshed it.

        ``after_generation`` is the generation this caller observed before
        its own request failed. If the generation has already moved on by
        the time we get the lock, another concurrent room fetch hit the
        same expired session and already logged back in - so there is
        nothing left to do here.
        """
        async with self._login_lock:
            if self._session_generation != after_generation:
                return
            self._authenticated = False
            await self._async_login()
            self._session_generation += 1

    async def _async_fetch_regelschritt(self, room_id: int) -> Optional[float]:
        url = f"{self._base_url}{ROOM_FRAGMENT_PATH.format(room_id=room_id)}"
        async with self._session.get(
            url, timeout=REQUEST_TIMEOUT, allow_redirects=False
        ) as response:
            if response.status in (301, 302, 401, 403):
                # Redirected to the login page, or rejected outright: the
                # session cookie is no longer valid.
                raise _SessionExpired
            if response.status != 200:
                _LOGGER.debug(
                    "Unexpected status %s fetching heating output for room %s",
                    response.status,
                    room_id,
                )
                return None
            html = await response.text()

        match = _BEAM_RE.search(html)
        if not match:
            _LOGGER.debug(
                "Could not find heating-output value in room %s page "
                "(Controme web UI layout may have changed)",
                room_id,
            )
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
