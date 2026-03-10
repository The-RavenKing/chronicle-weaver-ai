"""Tests for GmPersona, PlayerPersona, and context_builder integration."""

from __future__ import annotations

import tempfile
from pathlib import Path

from chronicle_weaver_ai.models import (
    DEFAULT_GM_PERSONA,
    DEFAULT_PLAYER_PERSONA,
    GameMode,
    GameState,
    GmPersona,
    PlayerPersona,
    WorldClock,
)


# ── GmPersona defaults ────────────────────────────────────────────────────────


def test_gm_persona_defaults():
    p = GmPersona()
    assert p.gm_style == "balanced"
    assert p.narrative_voice == "third_person"
    assert p.detail_level == "medium"


def test_default_gm_persona_constant():
    assert DEFAULT_GM_PERSONA == GmPersona()


def test_gm_persona_custom():
    p = GmPersona(
        gm_style="gritty", narrative_voice="second_person", detail_level="vivid"
    )
    assert p.gm_style == "gritty"
    assert p.narrative_voice == "second_person"
    assert p.detail_level == "vivid"


# ── PlayerPersona defaults ────────────────────────────────────────────────────


def test_player_persona_defaults():
    p = PlayerPersona()
    assert p.character_name == ""
    assert p.class_flavor == ""
    assert p.pronouns == "they/them"


def test_default_player_persona_constant():
    assert DEFAULT_PLAYER_PERSONA == PlayerPersona()


def test_player_persona_custom():
    p = PlayerPersona(
        character_name="Aria", class_flavor="elven ranger", pronouns="she/her"
    )
    assert p.character_name == "Aria"
    assert p.class_flavor == "elven ranger"
    assert p.pronouns == "she/her"


# ── context_builder integration ───────────────────────────────────────────────


def test_context_builder_persona_text_no_player():
    from chronicle_weaver_ai.memory.context_builder import ContextBuilder

    builder = ContextBuilder()
    state = GameState(mode=GameMode.EXPLORATION)
    gm = GmPersona(gm_style="heroic")
    bundle = builder.build(state, gm_persona=gm, budget_tokens=512)

    persona_items = [i for i in bundle.items if i.id == "always.persona"]
    assert len(persona_items) == 1
    assert "heroic" in persona_items[0].text


def test_context_builder_persona_text_with_player():
    from chronicle_weaver_ai.memory.context_builder import ContextBuilder

    builder = ContextBuilder()
    state = GameState(mode=GameMode.EXPLORATION)
    player = PlayerPersona(
        character_name="Thane", class_flavor="stoic fighter", pronouns="he/him"
    )
    bundle = builder.build(state, player_persona=player, budget_tokens=512)

    persona_items = [i for i in bundle.items if i.id == "always.persona"]
    assert "Thane" in persona_items[0].text
    assert "he/him" in persona_items[0].text


def test_context_builder_clock_text_present():
    from chronicle_weaver_ai.memory.context_builder import ContextBuilder

    builder = ContextBuilder()
    state = GameState(mode=GameMode.EXPLORATION)
    clock = WorldClock(day=4, hour=17, minute=30)
    bundle = builder.build(state, world_clock=clock, budget_tokens=512)

    clock_items = [i for i in bundle.items if i.id == "always.clock"]
    assert len(clock_items) == 1
    assert "Day 4" in clock_items[0].text
    assert "17:30" in clock_items[0].text


def test_context_builder_clock_default_when_none():
    from chronicle_weaver_ai.memory.context_builder import ContextBuilder

    builder = ContextBuilder()
    state = GameState()
    bundle = builder.build(state, world_clock=None, budget_tokens=512)

    clock_items = [i for i in bundle.items if i.id == "always.clock"]
    assert "Day 1" in clock_items[0].text


# ── campaign persistence round-trip ───────────────────────────────────────────


def test_persona_campaign_round_trip():
    from chronicle_weaver_ai.campaign import CampaignState, load_campaign, save_campaign

    gm = GmPersona(
        gm_style="gritty", narrative_voice="second_person", detail_level="vivid"
    )
    player = PlayerPersona(
        character_name="Rook", class_flavor="thief", pronouns="he/him"
    )
    campaign = CampaignState(
        campaign_id="c1",
        campaign_name="Test",
        actors={},
        lorebook_refs=[],
        scenes={},
        session_log_refs=[],
        gm_persona=gm,
        player_persona=player,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "camp.json"
        save_campaign(campaign, path)
        loaded = load_campaign(path)

    assert loaded.gm_persona.gm_style == "gritty"
    assert loaded.gm_persona.detail_level == "vivid"
    assert loaded.player_persona.character_name == "Rook"
    assert loaded.player_persona.pronouns == "he/him"


def test_persona_backwards_compat_missing_key():
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
    assert campaign.gm_persona == GmPersona()
    assert campaign.player_persona == PlayerPersona()
