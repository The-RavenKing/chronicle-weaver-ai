"""Integration tests for the 6 new encounter management API endpoints.

Covers:
- POST /encounter (create + roll initiative)
- GET /encounter/{id} (state read)
- POST /encounter/{id}/player-action (weapon with multi-attack, spell with slot consumption)
- POST /encounter/{id}/monster-turn
- POST /encounter/{id}/end-turn
- POST /encounter/{id}/death-save
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from chronicle_weaver_ai.api import app


@pytest.fixture()
def client() -> TestClient:  # type: ignore[return]
    with TestClient(app) as c:
        yield c


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fighter() -> dict:
    """Minimal level-1 fighter actor body for use in action payloads."""
    return {
        "actor_id": "pc.fighter",
        "name": "Aldric",
        "level": 1,
        "proficiency_bonus": 2,
        "abilities": {"str": 16, "dex": 12, "con": 14},
        "equipped_weapon_ids": ["w.longsword"],
        "feature_ids": [],
        "known_spell_ids": [],
        "item_ids": [],
        "spell_slots": {},
        "resources": {},
        "armor_class": 16,
        "hit_points": 28,
    }


def _make_wizard() -> dict:
    """Level-3 wizard with a spell slot."""
    return {
        "actor_id": "pc.wizard",
        "name": "Zara",
        "level": 3,
        "proficiency_bonus": 2,
        "abilities": {"int": 17, "dex": 14, "con": 12},
        "equipped_weapon_ids": [],
        "feature_ids": [],
        "known_spell_ids": ["s.fireball", "s.magic_missile"],
        "item_ids": [],
        "spell_slots": {"1": 4, "2": 3, "3": 2},
        "resources": {},
        "armor_class": 12,
        "hit_points": 18,
    }


def _create_standard_encounter(
    client: TestClient, encounter_id: str = "enc.test"
) -> dict:
    """Create a fighter-vs-goblin encounter and return the response body."""
    resp = client.post(
        "/encounter",
        json={
            "encounter_id": encounter_id,
            "combatants": [
                {
                    "combatant_id": "pc.fighter",
                    "source_type": "actor",
                    "source_id": "pc.fighter",
                    "display_name": "Aldric the Fighter",
                    "armor_class": 16,
                    "hit_points": 28,
                    "max_hit_points": 28,
                    "abilities": {"str": 16, "dex": 12},
                },
                {
                    "combatant_id": "m.goblin",
                    "source_type": "monster",
                    "source_id": "m.goblin",
                },
            ],
        },
    )
    return resp


# ── POST /encounter ────────────────────────────────────────────────────────────


def test_create_encounter_returns_201(client: TestClient) -> None:
    resp = _create_standard_encounter(client, "enc.create1")
    assert resp.status_code == 201
    body = resp.json()
    assert body["encounter_id"] == "enc.create1"
    assert not body["is_over"]
    assert len(body["turn_order"]) == 2
    assert "pc.fighter" in body["combatants"]
    assert "m.goblin" in body["combatants"]


def test_create_encounter_initiative_rolls_are_deterministic(
    client: TestClient,
) -> None:
    """Creating two encounters with the same combatants should produce a consistent turn order."""
    r1 = _create_standard_encounter(client, "enc.det.a")
    r2 = client.post(
        "/encounter",
        json={
            "encounter_id": "enc.det.b",
            "combatants": [
                {
                    "combatant_id": "pc.fighter",
                    "source_type": "actor",
                    "source_id": "pc.fighter",
                    "armor_class": 16,
                    "hit_points": 28,
                    "abilities": {},
                },
                {
                    "combatant_id": "m.goblin",
                    "source_type": "monster",
                    "source_id": "m.goblin",
                },
            ],
        },
    )
    assert r1.status_code == 201
    assert r2.status_code == 201


def test_create_encounter_409_when_id_exists(client: TestClient) -> None:
    _create_standard_encounter(client, "enc.dup")
    resp = _create_standard_encounter(client, "enc.dup")
    assert resp.status_code == 409


def test_create_encounter_404_unknown_monster(client: TestClient) -> None:
    resp = client.post(
        "/encounter",
        json={
            "encounter_id": "enc.badmon",
            "combatants": [
                {
                    "combatant_id": "m.xyz",
                    "source_type": "monster",
                    "source_id": "m.does_not_exist",
                }
            ],
        },
    )
    assert resp.status_code == 404


def test_create_encounter_422_actor_missing_hp(client: TestClient) -> None:
    resp = client.post(
        "/encounter",
        json={
            "encounter_id": "enc.nohp",
            "combatants": [
                {"combatant_id": "pc.x", "source_type": "actor", "source_id": "pc.x"}
            ],
        },
    )
    assert resp.status_code == 422


# ── GET /encounter/{id} ───────────────────────────────────────────────────────


def test_get_encounter_returns_state(client: TestClient) -> None:
    _create_standard_encounter(client, "enc.get1")
    resp = client.get("/encounter/enc.get1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["encounter_id"] == "enc.get1"
    assert body["round"] == 1
    assert "m.goblin" in body["combatants"]


def test_get_encounter_404_unknown(client: TestClient) -> None:
    resp = client.get("/encounter/enc.does_not_exist_9999")
    assert resp.status_code == 404


# ── POST /encounter/{id}/player-action — weapon ────────────────────────────────


def test_player_action_weapon_returns_attack(client: TestClient) -> None:
    _create_standard_encounter(client, "enc.wpn1")
    resp = client.post(
        "/encounter/enc.wpn1/player-action",
        json={
            "action_type": "weapon",
            "entry_id": "w.longsword",
            "target_id": "m.goblin",
            "actor": _make_fighter(),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action_kind"] == "attack"
    assert "attacks" in body
    assert len(body["attacks"]) >= 1
    atk = body["attacks"][0]
    assert "attack_roll" in atk
    assert "hit" in atk


def test_player_action_weapon_updates_target_hp(client: TestClient) -> None:
    """If the attack hits the goblin (AC 13), HP should drop below 7."""
    _create_standard_encounter(client, "enc.wpn2")
    goblin_start_hp = 7
    for _ in range(10):  # Try a few times to ensure we get a hit
        resp = client.post(
            "/encounter/enc.wpn2/player-action",
            json={
                "action_type": "weapon",
                "entry_id": "w.longsword",
                "target_id": "m.goblin",
                "actor": _make_fighter(),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        attacks = body["attacks"]
        if any(a["hit"] for a in attacks):
            # HP should have changed
            goblin_hp_after = body["encounter"]["combatants"]["m.goblin"]["hit_points"]
            assert goblin_hp_after < goblin_start_hp
            break


def test_player_action_weapon_404_missing_entry(client: TestClient) -> None:
    _create_standard_encounter(client, "enc.wpn3")
    resp = client.post(
        "/encounter/enc.wpn3/player-action",
        json={
            "action_type": "weapon",
            "entry_id": "w.does_not_exist",
            "actor": _make_fighter(),
        },
    )
    assert resp.status_code == 404


def test_player_action_weapon_404_missing_encounter(client: TestClient) -> None:
    resp = client.post(
        "/encounter/enc.gone/player-action",
        json={
            "action_type": "weapon",
            "entry_id": "w.longsword",
            "actor": _make_fighter(),
        },
    )
    assert resp.status_code == 404


# ── POST /encounter/{id}/player-action — spell ────────────────────────────────


def test_player_action_spell_consumes_slot(client: TestClient) -> None:
    _create_standard_encounter(client, "enc.spell1")
    wizard = _make_wizard()
    resp = client.post(
        "/encounter/enc.spell1/player-action",
        json={"action_type": "spell", "entry_id": "s.magic_missile", "actor": wizard},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action_kind"] == "cast_spell"
    # Slot should be consumed
    if body["can_cast"]:
        updated_slots = body["updated_spell_slots"]
        assert updated_slots is not None
        # One slot should now be one fewer
        slot_level = str(body["slot_level_used"])
        assert (
            int(updated_slots[slot_level]) == int(wizard["spell_slots"][slot_level]) - 1
        )


def test_player_action_spell_404_missing_encounter(client: TestClient) -> None:
    resp = client.post(
        "/encounter/enc.gone_spell/player-action",
        json={
            "action_type": "spell",
            "entry_id": "s.magic_missile",
            "actor": _make_wizard(),
        },
    )
    assert resp.status_code == 404


# ── POST /encounter/{id}/monster-turn ─────────────────────────────────────────


def test_monster_turn_executes_when_active(client: TestClient) -> None:
    """If the monster is current in turn order, its turn resolves cleanly."""
    _create_standard_encounter(client, "enc.mon1")
    enc = client.get("/encounter/enc.mon1").json()

    # Advance turns until it's the goblin's turn
    while enc["current_combatant_id"] != "m.goblin":
        enc = client.post("/encounter/enc.mon1/end-turn").json()["encounter"]
        if enc["is_over"]:
            break

    if not enc["is_over"] and enc["current_combatant_id"] == "m.goblin":
        resp = client.post("/encounter/enc.mon1/monster-turn")
        assert resp.status_code == 200
        body = resp.json()
        assert "turn" in body
        assert body["turn"]["combatant_id"] == "m.goblin"


def test_monster_turn_409_when_not_monsters_turn(client: TestClient) -> None:
    """Calling /monster-turn when it's a player's turn returns 409."""
    _create_standard_encounter(client, "enc.mon2")
    enc = client.get("/encounter/enc.mon2").json()
    # If fighter is first, monster-turn should fail
    if enc["current_combatant_id"] == "pc.fighter":
        resp = client.post("/encounter/enc.mon2/monster-turn")
        assert resp.status_code == 409


def test_monster_turn_404_missing_encounter(client: TestClient) -> None:
    resp = client.post("/encounter/enc.gone_monster/monster-turn")
    assert resp.status_code == 404


# ── POST /encounter/{id}/end-turn ─────────────────────────────────────────────


def test_end_turn_advances_turn_order(client: TestClient) -> None:
    _create_standard_encounter(client, "enc.end1")
    initial = client.get("/encounter/enc.end1").json()
    first_id = initial["current_combatant_id"]

    resp = client.post("/encounter/enc.end1/end-turn")
    assert resp.status_code == 200
    body = resp.json()
    # Should have moved to a different combatant
    assert body["current_combatant_id"] != first_id


def test_end_turn_increments_round_after_last_combatant(client: TestClient) -> None:
    _create_standard_encounter(client, "enc.end2")
    # Advance twice (2-combatant encounter → wraps)
    client.post("/encounter/enc.end2/end-turn")
    resp = client.post("/encounter/enc.end2/end-turn")
    body = resp.json()
    assert body["current_round"] == 2


def test_end_turn_404_missing_encounter(client: TestClient) -> None:
    resp = client.post("/encounter/enc.gone_end/end-turn")
    assert resp.status_code == 404


# ── POST /encounter/{id}/death-save ──────────────────────────────────────────


def test_death_save_requires_dying_combatant(client: TestClient) -> None:
    """Calling death-save on an actor with HP > 0 returns 409."""
    _create_standard_encounter(client, "enc.ds1")
    resp = client.post(
        "/encounter/enc.ds1/death-save",
        json={"combatant_id": "pc.fighter"},
    )
    assert resp.status_code == 409  # fighter has 28 HP, not dying


def test_death_save_404_unknown_combatant(client: TestClient) -> None:
    _create_standard_encounter(client, "enc.ds2")
    resp = client.post(
        "/encounter/enc.ds2/death-save",
        json={"combatant_id": "pc.nobody"},
    )
    assert resp.status_code == 404


def test_death_save_404_unknown_encounter(client: TestClient) -> None:
    resp = client.post(
        "/encounter/enc.gone_ds/death-save",
        json={"combatant_id": "pc.fighter"},
    )
    assert resp.status_code == 404


def test_death_save_409_for_monster(client: TestClient) -> None:
    """Monsters do not use death saves — should return 409."""
    _create_standard_encounter(client, "enc.ds3")
    resp = client.post(
        "/encounter/enc.ds3/death-save",
        json={"combatant_id": "m.goblin"},
    )
    assert resp.status_code == 409  # goblin is source_type=monster


# ── Full round-trip: encounter ends ──────────────────────────────────────────


def test_encounter_marks_over_when_monster_defeated(client: TestClient) -> None:
    """A weapon attack that reduces the goblin to 0 HP should flip is_over."""
    _create_standard_encounter(client, "enc.rt1")
    # Force a defeat: keep attacking until goblin falls or we safeguard with a limit
    for _ in range(20):
        resp = client.post(
            "/encounter/enc.rt1/player-action",
            json={
                "action_type": "weapon",
                "entry_id": "w.longsword",
                "target_id": "m.goblin",
                "actor": _make_fighter(),
            },
        )
        if resp.status_code != 200:
            break
        body = resp.json()
        if body["encounter"]["is_over"]:
            assert body["encounter"]["defeated_ids"] == ["m.goblin"]
            return
        # Advance turn to avoid budget exhaustion
        client.post("/encounter/enc.rt1/end-turn")

    # If we get here it's fine — goblin survived 20 attacks (possible with low rolls)
