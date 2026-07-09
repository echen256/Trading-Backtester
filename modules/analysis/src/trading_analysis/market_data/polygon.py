"""Low-level Polygon aggregates HTTP client."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

from .env import get_polygon_api_key

POLYGON_API_BASE_URL = "https://api.polygon.io/v2/aggs/ticker"


class PolygonHttpError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body

    @property
    def is_unauthorized(self) -> bool:
        return self.status_code == 403 or "NOT_AUTHORIZED" in self.body


def fetch_aggs(
    ticker: str,
    *,
    multiplier: int,
    timespan: str,
    start_date: date,
    end_date: date,
    api_key: str | None = None,
    adjusted: bool = True,
    limit: int = 50000,
    timeout: float = 60.0,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """
    Fetch Polygon aggregate bars for `ticker` over [start_date, end_date].

    Retries on 429 / transient network errors. Raises PolygonHttpError on
    non-retryable HTTP failures (including 403 NOT_AUTHORIZED).
    """
    key = api_key or get_polygon_api_key()
    if not key:
        raise RuntimeError(
            "POLYGON_API_KEY is not set. Expected it in the environment or Trading-Backtester/.env."
        )

    encoded_ticker = urllib.parse.quote(ticker, safe="")
    query = urllib.parse.urlencode(
        {
            "apiKey": key,
            "limit": limit,
            "adjusted": "true" if adjusted else "false",
            "sort": "asc",
        }
    )
    url: str | None = (
        f"{POLYGON_API_BASE_URL}/{encoded_ticker}/range/{multiplier}/{timespan}/"
        f"{start_date.isoformat()}/{end_date.isoformat()}?{query}"
    )

    all_results: list[dict[str, Any]] = []
    while url:
        payload = _request_json(url, key=key, timeout=timeout, max_retries=max_retries)
        results = payload.get("results")
        if isinstance(results, list):
            all_results.extend(results)

        next_url = payload.get("next_url")
        if isinstance(next_url, str) and next_url:
            sep = "&" if "?" in next_url else "?"
            url = f"{next_url}{sep}apiKey={urllib.parse.quote(key)}"
        else:
            url = None

    return all_results


def _request_json(
    url: str,
    *,
    key: str,
    timeout: float,
    max_retries: int,
) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise PolygonHttpError("Polygon returned a non-object JSON payload")
            return payload
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                last_error = exc
                continue
            raise PolygonHttpError(
                f"Polygon request failed ({exc.code}): {details}",
                status_code=exc.code,
                body=details,
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                last_error = exc
                continue
            raise PolygonHttpError(f"Could not reach Polygon: {exc}") from exc
        except TimeoutError as exc:
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                last_error = exc
                continue
            raise PolygonHttpError(f"Polygon request timed out: {exc}") from exc
    raise PolygonHttpError(f"Polygon request failed after retries: {last_error}")
