"""Contract, ingestion, catalog, aggregation, and artifact integration tests."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from trading_analysis.dashboard import DatasetCatalog, DatasetImporter, ImportOptions, StudyArtifactWriter
from trading_analysis.dashboard.api import load_bars_payload
from trading_analysis.dashboard.artifacts import annotation_v1_to_chart_v2
from trading_analysis.dashboard.tpo import load_tpo_payload
from trading_analysis.options_premium.dashboard import publish_premium_payload


def _crypto_frame(count: int = 240) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=count, freq="5min", tz="UTC")
    return pd.DataFrame({
        "open_time_utc": timestamps,
        "open": [100 + index * 0.1 for index in range(count)],
        "high": [101 + index * 0.1 for index in range(count)],
        "low": [99 + index * 0.1 for index in range(count)],
        "close": [100.5 + index * 0.1 for index in range(count)],
        "volume": [10 + index for index in range(count)],
    })


def _annotations() -> dict[str, object]:
    return {
        "schema_version": "trading-chart-annotations/v1",
        "groups": [{"id": "signals", "label": "Signals", "visible": True}],
        "panels": [],
        "points": [{
            "id": "entry", "group": "signals", "time": "2026-01-01T00:10:00Z",
            "pane": "price", "value": 100.7, "label": "Entry", "role": "entry",
        }],
        "links": [],
        "spans": [],
    }


def test_import_catalog_aggregate_and_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "BTCUSDT_5m.csv.gz"
    _crypto_frame().to_csv(source, index=False, compression="gzip")
    monkeypatch.setenv("TRADING_DASHBOARD_DATA_ROOTS", str(tmp_path))
    catalog = DatasetCatalog(tmp_path / "artifacts")
    metadata = DatasetImporter(catalog).import_file(
        source,
        ImportOptions(
            symbol="BTCUSDT", asset_class="crypto", venue="binance", provider="binance",
            base_asset="BTC", quote_asset="USDT", interval_seconds=300,
        ),
    )

    assert metadata["quality"]["row_count"] == 240
    assert metadata["quality"]["missing_intervals"] == 0
    assert Path(metadata["storage"]["path"]).exists()
    assert catalog.get_dataset(metadata["id"])["symbol"] == "BTCUSDT"

    native = load_bars_payload(catalog, metadata["id"], max_bars=500)
    aggregated = load_bars_payload(catalog, metadata["id"], max_bars=100)
    assert native["count"] == 240
    assert native["aggregated"] is False
    assert aggregated["aggregated"] is True
    assert aggregated["count"] <= 100
    assert aggregated["bars"]["open"][0] == pytest.approx(100)
    assert aggregated["bars"]["high"][0] >= max(native["bars"]["high"][:3])

    writer = StudyArtifactWriter(catalog)
    manifest = writer.build_manifest(
        study_id="test-signals", study_name="Test signals", version="1.0",
        views=[{"id": "overview", "label": "Overview", "dataset_id": metadata["id"], "chart": _annotations()}],
        metrics=[{"label": "Signals", "value": 1}],
    )
    path = writer.publish(manifest, resource_files={"notes.json": {"ok": True}})
    assert path.exists()
    assert json.loads(path.read_text())["views"][0]["chart"]["schema_version"] == "trading-chart-study/v2"
    assert (path.parent / "resources" / "notes.json").exists()
    assert catalog.list_studies()[0]["study_id"] == "test-signals"


def test_annotation_adapter_rejects_unknown_group() -> None:
    document = _annotations()
    document["points"][0]["group"] = "missing"  # type: ignore[index]
    with pytest.raises(ValueError, match="unknown group"):
        annotation_v1_to_chart_v2(document)


def test_report_study_infers_preview_and_copies_resources(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    rows = tmp_path / "events.csv"
    notes = tmp_path / "methodology.md"
    summary.write_text('{"event_count": 3, "nested": {"win_rate": 0.67}}\n', encoding="utf-8")
    rows.write_text("symbol,return\nAAPL,0.02\nMSFT,-0.01\n", encoding="utf-8")
    notes.write_text("# Method\n\nA reproducible test study.\n", encoding="utf-8")

    catalog = DatasetCatalog(tmp_path / "artifacts")
    path = StudyArtifactWriter(catalog).publish_report_study(
        study_id="report-test",
        study_name="Report test",
        version="1.0",
        generator="tests",
        files={"summary": summary, "events": rows, "methodology": notes},
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["views"] == []
    assert {metric["label"] for metric in manifest["metrics"]} >= {"event count", "nested · win rate"}
    assert manifest["tables"][0]["rows"][0]["symbol"] == "AAPL"
    assert manifest["methodology"].startswith("# Method")
    assert (path.parent / manifest["resources"]["summary"]["path"]).exists()


def test_options_payload_publishes_strict_dashboard_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRADING_ANALYSIS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    payload = {
        "ticker": "AAPL",
        "start_date": "2026-01-02",
        "end_date": "2026-01-05",
        "filters": {"selected": True},
        "liquidity": {"contract_count": 1, "plotted_count": 1},
        "contracts": [{
            "symbol": "O:AAPL260220C00200000", "option_type": "call",
            "strike": math.nan, "expiration": "2026-02-20",
            "last_volume": 12, "open_interest": 100,
        }],
        "underlying": [
            {"date": "2026-01-02", "o": 200, "h": 203, "l": 199, "c": 202, "v": 1000},
            {"date": "2026-01-05", "o": 202, "h": 204, "l": 201, "c": 203, "v": 1200},
        ],
        "premiums": {
            "O:AAPL260220C00200000": {
                "close": [{"date": "2026-01-02", "value": 8.5}],
                "high": [{"date": "2026-01-02", "value": 9.0}],
            },
        },
    }

    path = Path(publish_premium_payload(payload))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    resource = json.loads((path.parent / "resources" / "payload.json").read_text(encoding="utf-8"))

    assert manifest["study"]["id"] == "options-premium-vs-underlying"
    assert len(manifest["views"][0]["chart"]["panels"][0]["series"]) == 2
    assert resource["contracts"][0]["strike"] is None


def test_dynamic_tpo_uses_native_crypto_session_without_lookahead(tmp_path: Path) -> None:
    catalog = DatasetCatalog(tmp_path / "artifacts")
    metadata = DatasetImporter(catalog).import_rows(
        _crypto_frame(),
        source_label="test://BTCUSDT/5m",
        options=ImportOptions(
            symbol="BTCUSDT", asset_class="crypto", venue="test",
            provider="test", interval_seconds=300,
        ),
    )

    payload = load_tpo_payload(catalog, metadata["id"], at="2026-01-01T10:00:00Z")

    assert payload["available"] is True
    assert payload["session_date"] == "2026-01-01"
    assert payload["session_label"] == "00:00–24:00 UTC"
    assert payload["bar_count"] == 121
    assert payload["profile_through"] == "2026-01-01T10:00:00Z"
    assert payload["total_tpos"] > 0
    assert any(level["is_poc"] for level in payload["levels"])
    assert payload["val"] <= payload["poc"] <= payload["vah"]


def test_dynamic_tpo_uses_equity_rth_and_rejects_daily_data(tmp_path: Path) -> None:
    catalog = DatasetCatalog(tmp_path / "artifacts")
    timestamps = pd.date_range("2026-01-05T14:30:00Z", periods=78, freq="5min")
    frame = pd.DataFrame({
        "timestamp": timestamps,
        "open": [100 + index / 10 for index in range(78)],
        "high": [101 + index / 10 for index in range(78)],
        "low": [99 + index / 10 for index in range(78)],
        "close": [100.5 + index / 10 for index in range(78)],
        "volume": [1000] * 78,
    })
    intraday = DatasetImporter(catalog).import_rows(
        frame,
        source_label="test://AAPL/5m",
        options=ImportOptions(
            symbol="AAPL", asset_class="stock", venue="test",
            provider="test", interval_seconds=300, calendar="XNYS",
        ),
    )
    daily = DatasetImporter(catalog).import_rows(
        frame.iloc[[0, -1]].assign(timestamp=pd.to_datetime(["2026-01-05", "2026-01-06"], utc=True)),
        source_label="test://AAPL/1d",
        options=ImportOptions(
            symbol="AAPL", asset_class="stock", venue="test",
            provider="test", interval_seconds=86400, calendar="XNYS",
        ),
    )

    partial = load_tpo_payload(catalog, intraday["id"], at="2026-01-05T15:05:00Z")
    complete = load_tpo_payload(catalog, intraday["id"], at="2026-01-05T20:59:00Z")
    unavailable = load_tpo_payload(catalog, daily["id"], at="2026-01-05T20:00:00Z")

    assert partial["available"] is True
    assert partial["session_label"] == "09:30–16:00 America/New_York"
    assert partial["session_start"] == "2026-01-05T14:30:00Z"
    assert partial["bar_count"] == 8
    assert partial["complete"] is False
    assert complete["bar_count"] == 78
    assert complete["complete"] is True
    assert unavailable["available"] is False
    assert "30 minutes or finer" in unavailable["reason"]
