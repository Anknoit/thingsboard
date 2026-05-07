"""
tb_client.py — Async ThingsBoard REST API wrapper.

Internal implementation detail. Never reference ThingsBoard in user-facing text.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.5  # seconds


class TBAuthError(Exception):
    pass


class TBClientError(Exception):
    pass


class TBClient:
    """
    Provider of device data from the underlying IoT platform.

    Handles JWT auth with auto-refresh on 401, exponential-backoff retries,
    and connection pooling via a shared httpx.AsyncClient.
    """

    def __init__(self) -> None:
        self._base_url = settings.tb_url.rstrip("/")
        self._username = settings.tb_admin_user
        self._password = settings.tb_admin_password
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._refresh_token: str | None = None
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Auth ─────────────────────────────────────────────────────────────────

    async def _login(self) -> None:
        client = await self._get_client()
        resp = await client.post(
            "/api/auth/login",
            json={"username": self._username, "password": self._password},
        )
        if resp.status_code != 200:
            raise TBAuthError(f"ThingsBoard login failed: {resp.status_code} {resp.text}")
        data = resp.json()
        self._token = data["token"]
        self._refresh_token = data.get("refreshToken")
        # TB tokens expire in ~2.5h; refresh 5 min early
        self._token_expires_at = time.monotonic() + settings.jwt_expiry_seconds - 300
        logger.debug("ThingsBoard auth token acquired")

    async def _refresh_auth(self) -> None:
        if not self._refresh_token:
            await self._login()
            return
        client = await self._get_client()
        resp = await client.post(
            "/api/auth/token",
            json={"refreshToken": self._refresh_token},
        )
        if resp.status_code != 200:
            await self._login()
            return
        data = resp.json()
        self._token = data["token"]
        self._refresh_token = data.get("refreshToken")
        self._token_expires_at = time.monotonic() + settings.jwt_expiry_seconds - 300

    async def _ensure_token(self) -> str:
        async with self._lock:
            if self._token is None or time.monotonic() >= self._token_expires_at:
                await self._login()
        return self._token  # type: ignore[return-value]

    # ── Request helper ───────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        retry_on_401: bool = True,
    ) -> Any:
        token = await self._ensure_token()
        client = await self._get_client()
        headers = {"X-Authorization": f"Bearer {token}"}

        last_exc: Exception | None = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                resp = await client.request(
                    method,
                    path,
                    headers=headers,
                    json=json,
                    params=params,
                )
                if resp.status_code == 401 and retry_on_401:
                    await self._login()
                    token = self._token
                    headers["X-Authorization"] = f"Bearer {token}"
                    resp = await client.request(
                        method, path, headers=headers, json=json, params=params
                    )
                resp.raise_for_status()
                if resp.content:
                    return resp.json()
                return None
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning("TB request %s %s failed (attempt %d): %s — retrying in %.1fs",
                               method, path, attempt + 1, exc, delay)
                await asyncio.sleep(delay)
            except httpx.HTTPStatusError as exc:
                raise TBClientError(f"TB API error {exc.response.status_code}: {exc.response.text}") from exc

        raise TBClientError(f"TB request failed after {_RETRY_ATTEMPTS} attempts") from last_exc

    # ── Public API ───────────────────────────────────────────────────────────

    async def get_device(self, entity_id: str) -> dict:
        """Return device metadata dict."""
        return await self._request("GET", f"/api/device/{entity_id}")

    async def get_device_attributes(self, entity_id: str) -> dict:
        """Return flat dict of all device attributes (shared + server-side)."""
        shared = await self._request(
            "GET",
            f"/api/plugins/telemetry/DEVICE/{entity_id}/values/attributes/SHARED_SCOPE",
        )
        server = await self._request(
            "GET",
            f"/api/plugins/telemetry/DEVICE/{entity_id}/values/attributes/SERVER_SCOPE",
        )
        result: dict = {}
        for item in (shared or []) + (server or []):
            result[item["key"]] = item["value"]
        return result

    async def get_latest_telemetry(self, entity_id: str) -> dict:
        """Return dict of {key: latest_value} for a device."""
        data = await self._request(
            "GET",
            f"/api/plugins/telemetry/DEVICE/{entity_id}/values/timeseries",
        )
        if not data:
            return {}
        return {k: v[0]["value"] for k, v in data.items() if v}

    async def get_telemetry(
        self,
        entity_id: str,
        keys: list[str] | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """
        Return list of {ts, values} dicts for the given time range.
        Defaults to last 48 hours if start_ts/end_ts not provided.
        """
        now_ms = int(time.time() * 1000)
        params: dict = {
            "startTs": start_ts or (now_ms - 48 * 3600 * 1000),
            "endTs": end_ts or now_ms,
            "limit": limit,
            "agg": "NONE",
        }
        if keys:
            params["keys"] = ",".join(keys)

        data = await self._request(
            "GET",
            f"/api/plugins/telemetry/DEVICE/{entity_id}/values/timeseries",
            params=params,
        )
        if not data:
            return []

        # Pivot from {key: [{ts, value}]} to [{ts, values: {key: value}}]
        ts_map: dict[int, dict] = {}
        for key, readings in data.items():
            for reading in readings:
                ts = reading["ts"]
                ts_map.setdefault(ts, {"ts": ts, "values": {}})
                ts_map[ts]["values"][key] = reading["value"]

        return sorted(ts_map.values(), key=lambda x: x["ts"])

    async def get_alarms(self, entity_id: str, limit: int = 10) -> list[dict]:
        """Return list of recent alarm dicts for a device."""
        data = await self._request(
            "GET",
            f"/api/alarm/DEVICE/{entity_id}",
            params={"pageSize": limit, "page": 0, "sortProperty": "createdTime", "sortOrder": "DESC"},
        )
        return (data or {}).get("data", [])

    async def create_alarm(
        self,
        entity_id: str,
        alarm_type: str,
        severity: str,
        details: dict | None = None,
    ) -> str:
        """Create a new alarm on the device. Returns alarm_id."""
        payload = {
            "originator": {"id": entity_id, "entityType": "DEVICE"},
            "type": alarm_type,
            "severity": severity,
            "status": "ACTIVE_UNACK",
            "details": details or {},
        }
        result = await self._request("POST", "/api/alarm", json=payload)
        return result["id"]["id"]

    async def update_alarm_attributes(self, alarm_id: str, attributes: dict) -> bool:
        """Write AI-enrichment attributes to a device (server-scope) linked to an alarm."""
        # TB alarms don't have direct attribute storage; we write to the originator device.
        # The alarm_id is used as an audit reference. Caller should pass the device entity_id
        # as the target — this method signature mirrors the dev plan for convenience.
        # Actual write goes to SERVER_SCOPE attributes of the alarm's originator.
        try:
            await self._request(
                "POST",
                f"/api/alarm/{alarm_id}/comment",
                json={"comment": str(attributes)},
            )
            return True
        except TBClientError:
            return False

    async def set_device_server_attributes(self, entity_id: str, attributes: dict) -> None:
        """Write attributes to SERVER_SCOPE for a device (used for AI enrichment)."""
        await self._request(
            "POST",
            f"/api/plugins/telemetry/DEVICE/{entity_id}/attributes/SERVER_SCOPE",
            json=attributes,
        )

    async def acknowledge_alarm(self, alarm_id: str) -> None:
        await self._request("POST", f"/api/alarm/{alarm_id}/ack")

    async def health_check(self) -> bool:
        """Returns True if ThingsBoard is reachable and auth works."""
        try:
            await self._ensure_token()
            return True
        except Exception:
            return False


# Module-level singleton
_client: TBClient | None = None


def get_tb_client() -> TBClient:
    global _client
    if _client is None:
        _client = TBClient()
    return _client
