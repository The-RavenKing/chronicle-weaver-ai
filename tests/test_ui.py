"""Light integration tests for the UI shell endpoints (Milestone: UI Shell v0)."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from chronicle_weaver_ai.api import app


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


def test_root_returns_html(client: TestClient) -> None:
    """GET / must return 200 with an HTML content-type."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_root_html_contains_key_elements(client: TestClient) -> None:
    """The HTML shell must contain the player input, submit button, and title."""
    resp = client.get("/")
    html = resp.text
    assert "player-input" in html
    assert "submit-btn" in html
    assert "Chronicle Weaver" in html


def test_static_app_js_served(client: TestClient) -> None:
    """GET /static/app.js must return 200 with a non-empty JavaScript body."""
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    assert len(resp.content) > 0
    assert b"submitAction" in resp.content


def test_static_index_html_served(client: TestClient) -> None:
    """GET /static/index.html must return 200 with HTML content."""
    resp = client.get("/static/index.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_static_missing_file_returns_404(client: TestClient) -> None:
    """GET /static/nonexistent.js must return 404."""
    resp = client.get("/static/nonexistent.js")
    assert resp.status_code == 404
