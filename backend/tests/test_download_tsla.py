"""Integration test that fetches the earliest 30 trading days of TSLA data from Polygon."""
from datetime import datetime
from pathlib import Path
import os

import pytest
from dotenv import load_dotenv
from polygon import RESTClient


@pytest.fixture(scope="module")
def polygon_client():
    """Return an authenticated Polygon REST client or skip if no API key is configured."""
    backend_root = Path(__file__).resolve().parents[1]
    env_path = backend_root / ".env"
    load_dotenv(env_path)

    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        pytest.skip("POLYGON_API_KEY is missing. Add it to backend/.env to run integration tests.")

    return RESTClient(api_key)


def test_tsla_first_30_days(polygon_client):
    """Ensure we can pull the first 30 daily bars for TSLA starting from the earliest available date."""
    aggs = polygon_client.get_aggs(
        "TSLA",
        multiplier=1,
        timespan="day",
        # Polygon rejects dates before the Unix epoch, so clamp to 1970.
        from_="1970-01-01",
        to=datetime.utcnow(),
        sort="asc",
        limit=30,
    )

    assert aggs, "Polygon returned no data for TSLA."
    assert len(aggs) == 30, f"Expected 30 rows, received {len(aggs)}."

    first_ts = datetime.fromtimestamp(aggs[0].timestamp / 1000)
    last_ts = datetime.fromtimestamp(aggs[-1].timestamp / 1000)

    # Sanity checks that the window is in chronological order and about 30 days wide.
    assert first_ts <= last_ts, "Aggregation data is not sorted ascending by timestamp."
    assert (last_ts - first_ts).days >= 28, "Window appears shorter than 30 trading days."
