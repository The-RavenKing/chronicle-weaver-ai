"""Narrator protocol, prompt builder, and provider factory."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Protocol
from urllib import error, request

from chronicle_weaver_ai.narration.models import (
    ActionResult,
    EncounterContext,
    NarrationRequest,
    NarrationResponse,
    SceneState,
)
from chronicle_weaver_ai.models import JSONValue, _to_json_value

NON_OUTCOME_RULE = "LLM generates words, not outcomes."


class Narrator(Protocol):
    """Narration-only adapter interface."""

    provider: str

    def narrate(self, request: NarrationRequest) -> NarrationResponse:
        """Generate narrative text from deterministic context + action result."""
        ...


HttpPostJson = Any
DEFAULT_NARRATOR_TIMEOUT_SECONDS = 120
_LOGGER = logging.getLogger(__name__)


def build_system_text(request: NarrationRequest) -> str:
    """Build system text enforcing non-outcome narration constraints."""
    base = request.context.system_text.strip()
    if NON_OUTCOME_RULE in base:
        return base
    if not base:
        return NON_OUTCOME_RULE
    return f"{base}\n{NON_OUTCOME_RULE}"


def build_user_prompt(request: NarrationRequest) -> str:
    """Build deterministic user prompt for narration backends."""
    action = request.action
    dice = "none" if action.dice_roll is None else str(action.dice_roll)
    mode_from = action.mode_from or "unknown"
    mode_to = action.mode_to or "unknown"

    context_lines = []
    for item in request.context.items:
        for line in _sanitize_context_item_lines(item.text):
            context_lines.append(f"- {line}")
    if not context_lines:
        context_lines = ["- no context items"]

    combat_opening_guidance = (
        "6. Emphasize the beginning of combat when a combat mode transition occurs."
    )
    if mode_to != "combat":
        combat_opening_guidance = "6. If combat begins, emphasize its opening moment."
    resolved_action_lines = _resolved_action_lines(action)

    sections = [
        "Action Result:",
        f"intent: {action.intent}",
        f"mechanic: {action.mechanic}",
        f"action_category: {action.action_category}",
        f"dice_roll: {dice}",
        f"mode_transition: {mode_from} -> {mode_to}",
        "",
        "Narrative Guidance:",
        "Describe the scene as the player experiences it. Focus on motion and reaction rather than abstract reporting. The dice roll determines how well the action occurs, but you do not invent additional mechanics or numbers. Keep the narration grounded and immediate.",
        "",
        "Style Rules:",
        "1. Write 2-5 sentences.",
        "2. Use present tense and second person.",
        "3. Use prose only; no bullet points.",
        "4. Never mention internal metadata words like score, priority, tokens, entropy, provider, graph, or retrieved.",
        "5. Do not invent outcomes; Action Result and Resolved Action are authoritative.",
        combat_opening_guidance,
        "7. Never invent a die result unless explicitly provided.",
        "8. Never infer a die roll from attack_bonus_total.",
        "9. If attack_roll_d20 exists, you may reference it; if absent, do not mention a numeric roll.",
        "10. If auto_hit=true, do not imply a miss or failed connection.",
        "10b. If hit_result=true, describe the attack connecting. If hit_result=false, describe a miss or deflection—never describe damage or HP loss in a miss.",
        "11. If damage is not resolved, do not invent HP loss or exact damage numbers.",
        "11b. If defeated=true, narration may describe the target falling or being incapacitated. Do not invent gore or additional mechanics.",
        "11c. If target_hp_after=0, do not describe the target continuing to fight.",
        "11d. If healing_total is present, describe recovery or renewed vigor using only that exact number. Do not invent additional healing.",
        "12. If resolution includes a rejection reason, do not narrate success.",
        "13. You may only describe details supported by Action Result, Resolved Action, or Context Items.",
        "14. Do not invent setting details (lighting, weather, scenery); use neutral language when unknown.",
        "15. Do not introduce new entities, locations, or items.",
        "16. Encounter Context shows the current round and whose turn it is; you may reference it for immediacy.",
        "17. Active conditions are listed in the Conditions section; do not invent conditions not listed there.",
        "18. Never invent enemy reinforcements, terrain features, or lighting not present in context.",
        "19. If roll_mode=disadvantage, you may allude to impaired movement or disorientation only if the causing condition is listed in Conditions. Do not invent conditions.",
        "",
        "Resolved Action:",
        *resolved_action_lines,
        "",
        *_target_outcome_section(action),
        *_healing_outcome_section(action),
        *_scene_section(request.scene),
        *_encounter_context_section(request.encounter_context),
        *_conditions_section(request.encounter_context),
        "Context Items:",
        *context_lines,
        "",
        "Write exactly one short immersive paragraph.",
    ]
    return "\n".join(sections)


def post_json(
    url: str,
    payload: dict[str, JSONValue],
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, JSONValue]:
    """POST JSON via stdlib urllib and return parsed JSON object."""
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if headers:
        request_headers.update(headers)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url=url, data=body, headers=request_headers, method="POST")

    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = _short_detail(exc.read())
        raise RuntimeError(f"HTTP {exc.code} calling {url}: {detail}") from exc
    except error.URLError as exc:
        reason = str(getattr(exc, "reason", exc))
        raise RuntimeError(f"Network error calling {url}: {reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"Timeout calling {url}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON response from {url}: {exc.msg}") from exc
    parsed_payload = _to_json_value(parsed)
    if not isinstance(parsed_payload, dict):
        raise RuntimeError(f"Invalid JSON response from {url}: expected object")
    return parsed_payload


def get_narrator(
    provider: str = "auto",
    http_post_json: HttpPostJson | None = None,
    timeout_seconds: int | None = None,
) -> Narrator:
    """Resolve narrator backend from provider flag and environment."""
    normalized = provider.strip().lower()
    if normalized not in {"auto", "ollama", "openai"}:
        raise ValueError("--provider must be one of: auto, ollama, openai")

    if normalized == "auto":
        if os.environ.get("OPENAI_API_KEY"):
            normalized = "openai"
        elif os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_MODEL"):
            normalized = "ollama"
        else:
            raise ValueError(
                "No narrator provider available. Set OPENAI_API_KEY for OpenAI or "
                "set OLLAMA_BASE_URL/OLLAMA_MODEL (or use --provider ollama)."
            )

    resolved_timeout = resolve_timeout_seconds(timeout_seconds)

    if normalized == "openai":
        from chronicle_weaver_ai.narration.openai import OpenAINarrator

        return OpenAINarrator(
            http_post_json=http_post_json,
            timeout_seconds=resolved_timeout,
        )

    from chronicle_weaver_ai.narration.ollama import OllamaNarrator

    return OllamaNarrator(
        http_post_json=http_post_json,
        timeout_seconds=resolved_timeout,
    )


def _short_detail(raw: bytes, max_len: int = 200) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return "no response body"
    compact = " ".join(text.split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def _sanitize_context_item_lines(text: str) -> list[str]:
    """Remove internal metadata and render context text as plain narrative hints."""
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        cleaned = raw_line.strip()
        if not cleaned:
            continue

        # Remove layer labels and backend markers.
        cleaned = re.sub(r"^\[[^\]]+\]\s*", "", cleaned)
        cleaned = re.sub(r"^(Retrieved|Lore):\s*", "", cleaned, flags=re.IGNORECASE)
        if re.match(
            r"^Graph neighbors\s*\(depth=\d+\):\s*$", cleaned, flags=re.IGNORECASE
        ):
            continue
        cleaned = re.sub(r"^(?:-\s*)+", "", cleaned)

        # Remove retrieval metadata.
        cleaned = re.sub(r"\s*\(score=[^)]+\)", "", cleaned)
        cleaned = re.sub(r"\bscore\s*=\s*[^,\s)]+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bpriority\s*=\s*[^,\s)]+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"\btokens(?:_est)?\s*=\s*[^,\s)]+", "", cleaned, flags=re.IGNORECASE
        )

        # Remove internal deterministic mechanics metadata that should not leak.
        cleaned = re.sub(r",?\s*remaining_entropy=\d+", "", cleaned)
        cleaned = re.sub(r",?\s*entropy_source=[A-Za-z0-9_:-]+", "", cleaned)
        cleaned = re.sub(r",?\s*fallback_reason=[A-Za-z0-9_:-]+", "", cleaned)
        cleaned = re.sub(
            r"\b(provider|retrieved|graph)\b\s*:?", "", cleaned, flags=re.IGNORECASE
        )
        cleaned = " ".join(cleaned.split()).strip()
        if not cleaned:
            continue

        relation_sentence = _render_relation_sentence(cleaned)
        cleaned_lines.append(relation_sentence or cleaned)

    return cleaned_lines


def _render_relation_sentence(line: str) -> str | None:
    """Convert relation-graph syntax to simple natural language."""
    match = re.match(
        r"^(?P<subject>[^-][^-].*?)\s*--(?P<predicate>[a-z_]+)-->+\s*(?P<object>.+?)\.?$",
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    subject = _with_article(match.group("subject"), is_subject=True)
    obj = _with_article(match.group("object"), is_subject=False)
    predicate = match.group("predicate").lower()

    predicate_map = {
        "attacked": "has attacked",
        "spoke_to": "has spoken to",
        "searched": "has searched",
        "owns": "owns",
        "located_in": "is located in",
        "encountered_in": "has encountered in",
    }
    phrase = predicate_map.get(predicate, f"has {predicate.replace('_', ' ')}")
    sentence = f"{subject} {phrase} {obj}."
    return sentence[:1].upper() + sentence[1:]


def _with_article(name: str, is_subject: bool) -> str:
    text = " ".join(name.strip().split())
    if not text:
        return text
    lowered = text.lower()
    if lowered == "player":
        return "the player"
    if lowered.startswith(("the ", "a ", "an ", "your ", "my ", "this ", "that ")):
        return text
    if not is_subject and lowered == "scene":
        return "the scene"
    return f"the {text}"


def _target_outcome_section(action: ActionResult) -> list[str]:
    """Return 'Target Outcome:' section lines when combat outcome fields are present."""
    payload = action.resolved_action
    if not payload:
        return []
    outcome_keys = (
        "hit_result",
        "damage_total",
        "target_hp_before",
        "target_hp_after",
        "defeated",
    )
    lines: list[str] = []
    for key in outcome_keys:
        value = payload.get(key)
        if value is not None:
            lines.append(f"{key}: {_prompt_value(value)}")
    if not lines:
        return []
    return ["Target Outcome:", *lines, ""]


def _healing_outcome_section(action: ActionResult) -> list[str]:
    """Return 'Healing Outcome:' section lines when healing fields are present."""
    payload = action.resolved_action
    if not payload:
        return []
    outcome_keys = (
        "healing_total",
        "self_hp_before",
        "self_hp_after",
    )
    lines: list[str] = []
    for key in outcome_keys:
        value = payload.get(key)
        if value is not None:
            lines.append(f"{key}: {_prompt_value(value)}")
    if not lines:
        return []
    return ["Healing Outcome:", *lines, ""]


def _scene_section(scene: SceneState | None) -> list[str]:
    """Return 'Scene:' section lines when a SceneState is provided."""
    if scene is None:
        return []
    lines = [
        "Scene:",
        f"scene_id: {scene.scene_id}",
        f"description: {scene.description_stub}",
        f"combat_active: {'true' if scene.combat_active else 'false'}",
    ]
    if scene.combatants_present:
        lines.append(f"combatants_present: {', '.join(scene.combatants_present)}")
    lines.append("")
    return lines


def _encounter_context_section(ec: EncounterContext | None) -> list[str]:
    """Return 'Encounter Context:' section lines when an EncounterContext is provided."""
    if ec is None:
        return []
    order_str = " → ".join(ec.turn_order) if ec.turn_order else "(none)"
    return [
        "Encounter Context:",
        f"round: {ec.current_round}",
        f"acting_combatant: {ec.acting_combatant}",
        f"turn_order: {order_str}",
        "",
    ]


def _conditions_section(ec: EncounterContext | None) -> list[str]:
    """Return 'Conditions:' section lines when an EncounterContext is provided."""
    if ec is None:
        return []
    attacker_str = (
        ", ".join(ec.attacker_conditions) if ec.attacker_conditions else "(none)"
    )
    target_str = ", ".join(ec.target_conditions) if ec.target_conditions else "(none)"
    return [
        "Conditions:",
        f"attacker: {attacker_str}",
        f"target: {target_str}",
        "",
    ]


def _resolved_action_lines(action: ActionResult) -> list[str]:
    payload = action.resolved_action
    if not payload:
        return ["none"]
    keys = (
        "action_kind",
        "entry_name",
        "action_cost",
        "explanation",
        "attacker_name",
        "target_name",
        "roll_mode",
        "attack_rolls_d20",
        "attack_roll_d20",
        "attack_bonus_total",
        "attack_total",
        "target_armor_class",
        "hit_result",
        "damage_formula",
        "damage_rolls",
        "damage_modifier_total",
        "damage_total",
        "target_hp_before",
        "target_hp_after",
        "defeated",
        "healing_formula",
        "healing_rolls",
        "healing_modifier_total",
        "healing_total",
        "self_hp_before",
        "self_hp_after",
        "auto_hit",
        "effect_summary",
        "remaining_uses",
        "slot_level_used",
        "reason",
    )
    lines: list[str] = []
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        lines.append(f"{key}: {_prompt_value(value)}")
    if not lines:
        return ["none"]
    return lines


def _prompt_value(value: JSONValue) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def postprocess_narration_text(text: str, debug: bool = False) -> str:
    """Normalize and cap narration length to at most 5 sentences."""
    normalized = " ".join(text.strip().split())
    if not normalized:
        return ""

    sentences = _split_sentences(normalized)
    if len(sentences) > 5:
        return " ".join(sentences[:5]).strip()
    if len(sentences) < 2 and debug:
        _LOGGER.warning("Narration shorter than 2 sentences (%d).", len(sentences))
    return normalized


def _split_sentences(text: str) -> list[str]:
    """Deterministic sentence splitting on terminal punctuation."""
    parts = re.findall(r"[^.!?]+[.!?]?", text)
    return [part.strip() for part in parts if part.strip()]


def build_prompt_parts(request: NarrationRequest) -> tuple[str, str]:
    """Build exact system/user prompt parts sent to narrator backends."""
    return build_system_text(request), build_user_prompt(request)


def resolve_timeout_seconds(override_seconds: int | None = None) -> int:
    """Resolve narrator timeout from CLI override or environment."""
    if override_seconds is not None:
        if override_seconds <= 0:
            raise ValueError("timeout must be > 0 seconds")
        return override_seconds

    raw = os.environ.get("NARRATOR_TIMEOUT_SECONDS")
    if raw is None or not raw.strip():
        return DEFAULT_NARRATOR_TIMEOUT_SECONDS

    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError("NARRATOR_TIMEOUT_SECONDS must be an integer") from exc
    if parsed <= 0:
        raise ValueError("NARRATOR_TIMEOUT_SECONDS must be > 0")
    return parsed
