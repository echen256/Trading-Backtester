"""Tests for the portable multi-view chart workspace."""
from __future__ import annotations

import base64
import json
import re

import pytest

from trading_data_pipeline.chart_workspace import WorkspaceView, render_chart_workspace_html


def test_workspace_embeds_views_and_selectors() -> None:
    views = [
        WorkspaceView("mu-d", "MU", "Daily", "macd", "Adaptive MACD", "<html>daily</html>"),
        WorkspaceView("mu-w", "MU", "Weekly", "shape", "MACD shape", "<html>weekly</html>"),
    ]

    html = render_chart_workspace_html(views, title="MU workspace")

    assert 'id="symbol"' in html
    assert 'id="timeframe"' in html
    assert 'id="study"' in html
    assert 'id="viewer"' in html
    assert "MU workspace" in html
    encoded = re.search(r'"htmlBase64":"([A-Za-z0-9+/=]+)"', html)
    assert encoded is not None
    assert base64.b64decode(encoded.group(1)).decode("utf-8") == "<html>daily</html>"


def test_workspace_rejects_empty_or_duplicate_views() -> None:
    with pytest.raises(ValueError, match="at least one view"):
        render_chart_workspace_html([])

    duplicate = WorkspaceView("same", "MU", "Daily", "one", "One", "<html></html>")
    with pytest.raises(ValueError, match="ids must be unique"):
        render_chart_workspace_html([duplicate, duplicate])

    same_combination = WorkspaceView("other", "mu", "Daily", "one", "Other", "<html></html>")
    with pytest.raises(ValueError, match="combinations must be unique"):
        render_chart_workspace_html([duplicate, same_combination])


def test_workspace_json_is_safe_inside_script() -> None:
    view = WorkspaceView("safe", "MU", "Daily", "study", "</script><script>bad()</script>", "<html></html>")
    html = render_chart_workspace_html([view])
    script_payload = html.split("const views = ", 1)[1].split(";", 1)[0]

    assert "</script>" not in script_payload
    assert json.loads(script_payload)[0]["studyLabel"] == "</script><script>bad()</script>"
