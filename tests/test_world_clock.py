"""Tests for WorldClock — advance_time, time_of_day, clock_display, campaign round-trip."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from chronicle_weaver_ai.models import (
    WorldClock,
    advance_time,
    clock_display,
    time_of_day,
)


# ── advance_time ──────────────────────────────────────────────────────────────


def test_advance_time_by_zero():
    clock = WorldClock(day=1, hour=8, minute=0)
    assert advance_time(clock, 0) == clock


def test_advance_time_minutes_only():
    clock = WorldClock(day=1, hour=8, minute=0)
    result = advance_time(clock, 45)
    assert result == WorldClock(day=1, hour=8, minute=45)


def test_advance_time_rolls_over_hour():
    clock = WorldClock(day=1, hour=8, minute=50)
    result = advance_time(clock, 30)
    assert result == WorldClock(day=1, hour=9, minute=20)


def test_advance_time_rolls_over_day():
    clock = WorldClock(day=1, hour=23, minute=0)
    result = advance_time(clock, 120)
    assert result == WorldClock(day=2, hour=1, minute=0)


def test_advance_time_multiple_days():
    clock = WorldClock(day=1, hour=0, minute=0)
    # 3 full days = 3 * 24 * 60 = 4320 minutes
    result = advance_time(clock, 4320)
    assert result == WorldClock(day=4, hour=0, minute=0)


def test_advance_time_preserves_immutability():
    original = WorldClock(day=2, hour=10, minute=30)
    advance_time(original, 60)
    assert original.hour == 10  # unchanged


def test_advance_time_large_step():
    clock = WorldClock(day=1, hour=6, minute=0)
    result = advance_time(clock, 60 * 24 + 180)  # 1 day + 3 hours
    assert result == WorldClock(day=2, hour=9, minute=0)


# ── time_of_day ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "hour,expected",
    [
        (0, "midnight"),
        (2, "deep_night"),
        (5, "dawn"),
        (6, "dawn"),
        (7, "morning"),
        (10, "morning"),
        (11, "midday"),
        (13, "midday"),
        (14, "afternoon"),
        (16, "afternoon"),
        (17, "dusk"),
        (19, "dusk"),
        (20, "night"),
        (23, "night"),
    ],
)
def test_time_of_day_labels(hour: int, expected: str):
    assert time_of_day(WorldClock(day=1, hour=hour)) == expected


# ── clock_display ──────────────────────────────────────────────────────────────


def test_clock_display_format():
    clock = WorldClock(day=3, hour=14, minute=5)
    text = clock_display(clock)
    assert "Day 3" in text
    assert "14:05" in text
    assert "afternoon" in text


def test_clock_display_zero_padding():
    clock = WorldClock(day=1, hour=8, minute=3)
    assert "08:03" in clock_display(clock)


# ── campaign persistence round-trip ───────────────────────────────────────────


def test_world_clock_campaign_round_trip():
    from chronicle_weaver_ai.campaign import CampaignState, load_campaign, save_campaign

    clock = WorldClock(day=5, hour=21, minute=45)
    campaign = CampaignState(
        campaign_id="c1",
        campaign_name="Test",
        actors={},
        lorebook_refs=[],
        scenes={},
        session_log_refs=[],
        world_clock=clock,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "camp.json"
        save_campaign(campaign, path)
        loaded = load_campaign(path)

    assert loaded.world_clock.day == 5
    assert loaded.world_clock.hour == 21
    assert loaded.world_clock.minute == 45


def test_world_clock_default_in_campaign():
    from chronicle_weaver_ai.campaign import CampaignState

    campaign = CampaignState(
        campaign_id="c1",
        campaign_name="Test",
        actors={},
        lorebook_refs=[],
        scenes={},
        session_log_refs=[],
    )
    assert campaign.world_clock == WorldClock()


def test_world_clock_backwards_compat_missing_key():
    """Campaigns saved before clock was added should load with default clock."""
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
    assert campaign.world_clock == WorldClock()
