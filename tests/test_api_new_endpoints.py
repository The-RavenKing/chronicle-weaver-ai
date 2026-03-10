"""Tests for new API endpoints: clock advance, persona patch, lore conflicts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chronicle_weaver_ai.api import _CAMPAIGN_DIR, app
from chronicle_weaver_ai.campaign import CampaignState, save_campaign
from chronicle_weaver_ai.models import GmPersona, PlayerPersona, WorldClock


@pytest.fixture()
def client():  # type: ignore[return]
    with TestClient(app) as c:
        yield c


def _make_campaign(tmp_path: Path, campaign_id: str) -> Path:
    """Create a minimal campaign JSON in the campaigns/ directory and return its path."""
    _CAMPAIGN_DIR.mkdir(exist_ok=True)
    camp = CampaignState(
        campaign_id=campaign_id,
        campaign_name="Test Campaign",
        actors={},
        lorebook_refs=[],
        scenes={},
        session_log_refs=[],
        world_clock=WorldClock(day=1, hour=8, minute=0),
        gm_persona=GmPersona(
            gm_style="balanced", narrative_voice="third_person", detail_level="medium"
        ),
        player_persona=PlayerPersona(
            character_name="Aria", class_flavor="brave fighter", pronouns="she/her"
        ),
    )
    path = _CAMPAIGN_DIR / f"{campaign_id}.json"
    save_campaign(camp, path)
    return path


# ── PATCH /campaign/{id}/clock ────────────────────────────────────────────────


def test_patch_clock_advances_minutes(client: TestClient, tmp_path: Path) -> None:
    path = _make_campaign(tmp_path, "_test_clock")
    resp = client.patch("/campaign/_test_clock/clock", json={"minutes": 60})
    assert resp.status_code == 200
    body = resp.json()
    assert body["campaign_id"] == "_test_clock"
    assert body["hour"] == 9
    assert body["minute"] == 0
    assert "morning" in body["clock"]
    path.unlink(missing_ok=True)


def test_patch_clock_404_unknown_campaign(client: TestClient) -> None:
    resp = client.patch("/campaign/nonexistent_xyz/clock", json={"minutes": 30})
    assert resp.status_code == 404


def test_patch_clock_400_invalid_id(client: TestClient) -> None:
    resp = client.patch("/campaign/../etc/clock", json={"minutes": 30})
    assert resp.status_code in (400, 404, 422)


def test_patch_clock_crosses_day_boundary(client: TestClient, tmp_path: Path) -> None:
    _CAMPAIGN_DIR.mkdir(exist_ok=True)
    camp = CampaignState(
        campaign_id="_test_clock_day",
        campaign_name="Test",
        actors={},
        lorebook_refs=[],
        scenes={},
        session_log_refs=[],
        world_clock=WorldClock(day=1, hour=23, minute=30),
    )
    path = _CAMPAIGN_DIR / "_test_clock_day.json"
    save_campaign(camp, path)
    resp = client.patch("/campaign/_test_clock_day/clock", json={"minutes": 60})
    assert resp.status_code == 200
    body = resp.json()
    assert body["day"] == 2
    assert body["hour"] == 0
    assert body["minute"] == 30
    path.unlink(missing_ok=True)


# ── PATCH /campaign/{id}/persona ─────────────────────────────────────────────


def test_patch_persona_updates_gm_style(client: TestClient, tmp_path: Path) -> None:
    path = _make_campaign(tmp_path, "_test_persona")
    resp = client.patch("/campaign/_test_persona/persona", json={"gm_style": "gritty"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["gm_persona"]["gm_style"] == "gritty"
    # Unchanged fields should be preserved
    assert body["gm_persona"]["narrative_voice"] == "third_person"
    path.unlink(missing_ok=True)


def test_patch_persona_updates_player(client: TestClient, tmp_path: Path) -> None:
    path = _make_campaign(tmp_path, "_test_persona2")
    resp = client.patch(
        "/campaign/_test_persona2/persona",
        json={"character_name": "Zephyr", "pronouns": "they/them"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["player_persona"]["character_name"] == "Zephyr"
    assert body["player_persona"]["pronouns"] == "they/them"
    # class_flavor preserved
    assert body["player_persona"]["class_flavor"] == "brave fighter"
    path.unlink(missing_ok=True)


def test_patch_persona_404_unknown(client: TestClient) -> None:
    resp = client.patch(
        "/campaign/no_such_campaign/persona", json={"gm_style": "heroic"}
    )
    assert resp.status_code == 404


# ── POST /lore/check-conflicts ────────────────────────────────────────────────


def test_lore_check_conflicts_empty_returns_zero(
    client: TestClient, tmp_path: Path
) -> None:
    queue = tmp_path / "queue.jsonl"
    lorebook = tmp_path / "lorebook.json"
    queue.write_text("", encoding="utf-8")
    lorebook.write_text(
        json.dumps({"entities": [], "facts": [], "relations": []}), encoding="utf-8"
    )
    resp = client.post(
        "/lore/check-conflicts",
        json={"queue_path": str(queue), "lorebook_path": str(lorebook)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["conflict_count"] == 0
    assert body["conflicts"] == []


def test_lore_check_conflicts_missing_queue(client: TestClient, tmp_path: Path) -> None:
    lorebook = tmp_path / "lorebook.json"
    lorebook.write_text(
        json.dumps({"entities": [], "facts": [], "relations": []}), encoding="utf-8"
    )
    resp = client.post(
        "/lore/check-conflicts",
        json={
            "queue_path": str(tmp_path / "nope.jsonl"),
            "lorebook_path": str(lorebook),
        },
    )
    assert resp.status_code == 404


def test_lore_check_conflicts_missing_lorebook(
    client: TestClient, tmp_path: Path
) -> None:
    queue = tmp_path / "queue.jsonl"
    queue.write_text("", encoding="utf-8")
    resp = client.post(
        "/lore/check-conflicts",
        json={"queue_path": str(queue), "lorebook_path": str(tmp_path / "nope.json")},
    )
    assert resp.status_code == 404
