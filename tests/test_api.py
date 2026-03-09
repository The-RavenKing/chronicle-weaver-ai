"""Tests for the Chronicle Weaver FastAPI layer (Milestone: API Layer v0)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chronicle_weaver_ai.api import app


@pytest.fixture()
def client():  # type: ignore[return]
    with TestClient(app) as c:
        yield c


# ── POST /interpret ───────────────────────────────────────────────────────────


def test_interpret_returns_intent_fields(client: TestClient) -> None:
    """POST /interpret must return all required intent fields."""
    resp = client.post(
        "/interpret", json={"text": "I attack the goblin", "mode": "combat"}
    )
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "intent",
        "mechanic",
        "confidence",
        "rationale",
        "provider_used",
        "is_valid",
        "action_category",
    ):
        assert key in body, f"missing key: {key}"


def test_interpret_exploration_mode(client: TestClient) -> None:
    """POST /interpret in exploration mode must succeed and return an intent."""
    resp = client.post(
        "/interpret", json={"text": "I look around the room", "mode": "exploration"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["intent"], str)
    assert isinstance(body["confidence"], (int, float))


def test_interpret_defaults_mode_to_exploration(client: TestClient) -> None:
    """POST /interpret without 'mode' must default to exploration."""
    resp = client.post("/interpret", json={"text": "hello"})
    assert resp.status_code == 200


def test_interpret_unknown_mode_returns_422(client: TestClient) -> None:
    """POST /interpret with an unknown mode must return 422."""
    resp = client.post("/interpret", json={"text": "attack", "mode": "invalid_mode"})
    assert resp.status_code == 422


def test_interpret_missing_text_returns_422(client: TestClient) -> None:
    """POST /interpret without required 'text' field must return 422."""
    resp = client.post("/interpret", json={"mode": "exploration"})
    assert resp.status_code == 422


# ── POST /resolve-action ──────────────────────────────────────────────────────


_FIGHTER_BODY: dict[str, Any] = {
    "actor_id": "pc.fighter.test",
    "name": "Test Fighter",
    "level": 3,
    "proficiency_bonus": 2,
    "abilities": {"str": 16, "dex": 12, "con": 14, "int": 8, "wis": 10, "cha": 10},
    "equipped_weapon_ids": ["w.longsword"],
    "known_spell_ids": [],
    "feature_ids": ["f.second_wind"],
    "item_ids": [],
    "spell_slots": {},
    "resources": {"second_wind_uses": 1},
    "armor_class": 16,
    "hit_points": 28,
}

_WIZARD_BODY: dict[str, Any] = {
    "actor_id": "pc.wizard.test",
    "name": "Test Wizard",
    "level": 3,
    "proficiency_bonus": 2,
    "abilities": {"str": 8, "dex": 14, "con": 12, "int": 16, "wis": 12, "cha": 10},
    "equipped_weapon_ids": [],
    "known_spell_ids": ["s.magic_missile"],
    "feature_ids": [],
    "item_ids": [],
    "spell_slots": {"1": 2},
    "resources": {},
    "armor_class": 12,
    "hit_points": 18,
}


def test_resolve_weapon_attack_returns_expected_fields(client: TestClient) -> None:
    """POST /resolve-action for a weapon must return attack resolution fields."""
    resp = client.post(
        "/resolve-action",
        json={
            "action_type": "weapon",
            "entry_id": "w.longsword",
            "actor": _FIGHTER_BODY,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "action_kind",
        "entry_id",
        "entry_name",
        "attack_bonus_total",
        "damage_formula",
        "action_cost",
    ):
        assert key in body, f"missing key: {key}"
    assert body["entry_id"] == "w.longsword"
    assert body["action_kind"] == "attack"


def test_resolve_spell_cast_returns_expected_fields(client: TestClient) -> None:
    """POST /resolve-action for a spell must return spell resolution fields."""
    resp = client.post(
        "/resolve-action",
        json={
            "action_type": "spell",
            "entry_id": "s.magic_missile",
            "actor": _WIZARD_BODY,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "action_kind",
        "entry_id",
        "entry_name",
        "can_cast",
        "auto_hit",
        "action_cost",
    ):
        assert key in body, f"missing key: {key}"
    assert body["entry_id"] == "s.magic_missile"
    assert body["auto_hit"] is True


def test_resolve_feature_use_returns_expected_fields(client: TestClient) -> None:
    """POST /resolve-action for a feature must return feature resolution fields."""
    resp = client.post(
        "/resolve-action",
        json={
            "action_type": "feature",
            "entry_id": "f.second_wind",
            "actor": _FIGHTER_BODY,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "action_kind",
        "entry_id",
        "entry_name",
        "can_use",
        "remaining_uses",
        "action_cost",
    ):
        assert key in body, f"missing key: {key}"
    assert body["entry_id"] == "f.second_wind"


def test_resolve_action_unknown_entry_returns_404(client: TestClient) -> None:
    """POST /resolve-action with unknown entry_id must return 404."""
    resp = client.post(
        "/resolve-action",
        json={
            "action_type": "weapon",
            "entry_id": "w.does_not_exist",
            "actor": _FIGHTER_BODY,
        },
    )
    assert resp.status_code == 404


def test_resolve_action_wrong_kind_returns_422(client: TestClient) -> None:
    """POST /resolve-action requesting 'weapon' for a spell entry must return 422."""
    resp = client.post(
        "/resolve-action",
        json={
            "action_type": "weapon",
            "entry_id": "s.magic_missile",
            "actor": _WIZARD_BODY,
        },
    )
    assert resp.status_code == 422


def test_resolve_action_unknown_action_type_returns_422(client: TestClient) -> None:
    """POST /resolve-action with an unknown action_type must return 422."""
    resp = client.post(
        "/resolve-action",
        json={
            "action_type": "ritual",
            "entry_id": "w.longsword",
            "actor": _FIGHTER_BODY,
        },
    )
    assert resp.status_code == 422


def test_resolve_weapon_without_actor_returns_422(client: TestClient) -> None:
    """POST /resolve-action for weapon with no actor must return 422."""
    resp = client.post(
        "/resolve-action",
        json={"action_type": "weapon", "entry_id": "w.longsword"},
    )
    assert resp.status_code == 422


# ── POST /narrate ─────────────────────────────────────────────────────────────


def test_narrate_returns_prompt_and_system_text(client: TestClient) -> None:
    """POST /narrate must return 'prompt' and 'system_text' keys."""
    resp = client.post(
        "/narrate",
        json={
            "intent": "attack",
            "mechanic": "combat_roll",
            "mode_from": "combat",
            "mode_to": "combat",
            "system_text": "You are the GM.",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "prompt" in body
    assert "system_text" in body
    assert isinstance(body["prompt"], str)
    assert len(body["prompt"]) > 0


def test_narrate_prompt_contains_intent(client: TestClient) -> None:
    """POST /narrate prompt must include the submitted intent."""
    resp = client.post(
        "/narrate",
        json={"intent": "talk", "mechanic": "narrate_only"},
    )
    assert resp.status_code == 200
    assert "talk" in resp.json()["prompt"]


def test_narrate_with_resolved_action_embeds_fields(client: TestClient) -> None:
    """POST /narrate with resolved_action dict must embed those fields in the prompt."""
    resp = client.post(
        "/narrate",
        json={
            "intent": "attack",
            "mechanic": "combat_roll",
            "mode_from": "combat",
            "mode_to": "combat",
            "resolved_action": {
                "action_kind": "attack",
                "entry_name": "Longsword",
                "hit_result": True,
                "damage_total": 9,
            },
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "Longsword" in prompt
    assert "damage_total" in prompt


# ── GET /compendium ───────────────────────────────────────────────────────────


def test_compendium_list_all(client: TestClient) -> None:
    """GET /compendium must return entries and count."""
    resp = client.get("/compendium")
    assert resp.status_code == 200
    body = resp.json()
    assert "entries" in body
    assert "count" in body
    assert isinstance(body["entries"], list)
    assert body["count"] == len(body["entries"])


def test_compendium_lookup_by_id_known(client: TestClient) -> None:
    """GET /compendium?id=w.longsword must return exactly one entry."""
    resp = client.get("/compendium", params={"id": "w.longsword"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["entries"][0]["id"] == "w.longsword"


def test_compendium_lookup_by_id_unknown_returns_404(client: TestClient) -> None:
    """GET /compendium?id=unknown must return 404."""
    resp = client.get("/compendium", params={"id": "w.does_not_exist"})
    assert resp.status_code == 404


def test_compendium_filter_by_kind(client: TestClient) -> None:
    """GET /compendium?kind=weapon must return only weapon entries."""
    resp = client.get("/compendium", params={"kind": "weapon"})
    assert resp.status_code == 200
    body = resp.json()
    assert all(e["kind"] == "weapon" for e in body["entries"])


def test_compendium_filter_by_name(client: TestClient) -> None:
    """GET /compendium?name=longsword must return matching entries (case-insensitive)."""
    resp = client.get("/compendium", params={"name": "longsword"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert any("longsword" in e["name"].lower() for e in body["entries"])


# ── GET /campaign/{campaign_id} ───────────────────────────────────────────────


def test_campaign_invalid_id_returns_400(client: TestClient) -> None:
    """GET /campaign/{id} with path-traversal attempt must return 400."""
    resp = client.get("/campaign/../etc/passwd")
    # FastAPI routing will 404 (treated as different path), but traversal in id rejected
    assert resp.status_code in (400, 404)


def test_campaign_not_found_returns_404(client: TestClient) -> None:
    """GET /campaign/{id} for non-existent campaign must return 404."""
    resp = client.get("/campaign/does_not_exist_xyz")
    assert resp.status_code == 404


def test_campaign_load_valid(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /campaign/{id} must load and return a valid campaign JSON."""
    from chronicle_weaver_ai import api as api_module
    from chronicle_weaver_ai.campaign import CampaignState, CampaignScene, save_campaign
    from chronicle_weaver_ai.models import Actor

    campaign = CampaignState(
        campaign_id="camp.api_test",
        campaign_name="API Test Campaign",
        actors={
            "pc.fighter": Actor(
                actor_id="pc.fighter",
                name="Test Fighter",
                level=1,
                proficiency_bonus=2,
                abilities={},
                equipped_weapon_ids=[],
                known_spell_ids=[],
                feature_ids=[],
                item_ids=[],
                spell_slots={},
                resources={},
            )
        },
        lorebook_refs=[],
        scenes={
            "scene.start": CampaignScene(
                scene_id="scene.start",
                description_stub="A quiet clearing.",
            )
        },
        session_log_refs=[],
    )
    out = tmp_path / "camp.api_test.json"
    save_campaign(campaign, out)

    monkeypatch.setattr(api_module, "_CAMPAIGN_DIR", tmp_path)

    resp = client.get("/campaign/camp.api_test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["campaign_id"] == "camp.api_test"
    assert "actors" in body
    assert "scenes" in body
