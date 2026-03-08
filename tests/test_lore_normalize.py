"""Tests for canonical lore normalization helpers."""

from chronicle_weaver_ai.lore.normalize import entity_id, normalize_name


def test_normalize_name_variants_map_to_same_value() -> None:
    variants = ["Goblin", "goblin", "goblins", "the goblin"]
    normalized = {normalize_name(value) for value in variants}
    assert normalized == {"goblin"}


def test_entity_id_is_stable_for_name_variants() -> None:
    ids = {
        entity_id("Goblin", "npc"),
        entity_id("goblins", "npc"),
        entity_id("the goblin", "npc"),
    }
    assert len(ids) == 1
