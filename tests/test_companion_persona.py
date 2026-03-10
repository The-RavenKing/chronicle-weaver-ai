"""Tests for CompanionPersona and context_builder companion integration."""

from __future__ import annotations

import tempfile
from pathlib import Path

from chronicle_weaver_ai.models import CompanionPersona, GameMode, GameState


# ── CompanionPersona model ────────────────────────────────────────────────────


def test_companion_persona_defaults():
    c = CompanionPersona(companion_id="c.elara", character_name="Elara")
    assert c.class_flavor == ""
    assert c.pronouns == "they/them"
    assert c.role == "party_member"


def test_companion_persona_custom():
    c = CompanionPersona(
        companion_id="c.elara",
        character_name="Elara",
        class_flavor="elven healer",
        pronouns="she/her",
        role="npc_ally",
    )
    assert c.class_flavor == "elven healer"
    assert c.pronouns == "she/her"
    assert c.role == "npc_ally"


def test_companion_persona_frozen():
    c = CompanionPersona(companion_id="c.x", character_name="X")
    try:
        c.character_name = "Y"  # type: ignore[misc]
        assert False, "should have raised FrozenInstanceError"
    except Exception:
        pass


# ── context_builder integration ───────────────────────────────────────────────


def test_companions_appear_in_persona_context():
    from chronicle_weaver_ai.memory.context_builder import ContextBuilder

    builder = ContextBuilder()
    state = GameState(mode=GameMode.EXPLORATION)
    companions = [
        CompanionPersona(
            companion_id="c.elara", character_name="Elara", role="npc_ally"
        ),
        CompanionPersona(
            companion_id="c.brom", character_name="Brom", role="party_member"
        ),
    ]
    bundle = builder.build(state, companions=companions, budget_tokens=512)

    persona_item = next(i for i in bundle.items if i.id == "always.persona")
    assert "Elara" in persona_item.text
    assert "Brom" in persona_item.text


def test_no_companions_does_not_crash():
    from chronicle_weaver_ai.memory.context_builder import ContextBuilder

    builder = ContextBuilder()
    state = GameState()
    bundle = builder.build(state, companions=[], budget_tokens=512)
    persona_item = next(i for i in bundle.items if i.id == "always.persona")
    assert "companions" not in persona_item.text


def test_companions_without_name_excluded():
    from chronicle_weaver_ai.memory.context_builder import ContextBuilder

    builder = ContextBuilder()
    state = GameState()
    companions = [CompanionPersona(companion_id="c.nameless", character_name="")]
    bundle = builder.build(state, companions=companions, budget_tokens=512)
    persona_item = next(i for i in bundle.items if i.id == "always.persona")
    assert "companions" not in persona_item.text


# ── campaign persistence round-trip ───────────────────────────────────────────


def test_companions_campaign_round_trip():
    from chronicle_weaver_ai.campaign import CampaignState, load_campaign, save_campaign

    companions = [
        CompanionPersona(
            companion_id="c.elara",
            character_name="Elara",
            class_flavor="healer",
            pronouns="she/her",
            role="npc_ally",
        ),
        CompanionPersona(
            companion_id="c.brom",
            character_name="Brom",
            role="party_member",
        ),
    ]
    campaign = CampaignState(
        campaign_id="c1",
        campaign_name="Test",
        actors={},
        lorebook_refs=[],
        scenes={},
        session_log_refs=[],
        companions=companions,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "camp.json"
        save_campaign(campaign, path)
        loaded = load_campaign(path)

    assert len(loaded.companions) == 2
    elara = next(c for c in loaded.companions if c.companion_id == "c.elara")
    assert elara.character_name == "Elara"
    assert elara.pronouns == "she/her"
    assert elara.role == "npc_ally"


def test_companions_backwards_compat_missing_key():
    from chronicle_weaver_ai.campaign import campaign_from_dict

    d = {
        "campaign_id": "c1",
        "campaign_name": "Old",
        "actors": {},
        "lorebook_refs": [],
        "scenes": {},
        "session_log_refs": [],
    }
    campaign = campaign_from_dict(d)
    assert campaign.companions == []
