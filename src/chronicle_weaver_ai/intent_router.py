"""Hybrid intent routing with deterministic rules-first classification."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from chronicle_weaver_ai.models import (
    ActionCategory,
    GameMode,
    Intent,
    IntentResult,
    Mechanic,
)
from chronicle_weaver_ai.compendium import (
    CompendiumEntry,
    CompendiumLoadError,
    CompendiumStore,
    compact_compendium_text,
    normalize_compendium_text,
    resolve_compendium_roots,
)
from chronicle_weaver_ai.narration.narrator import post_json

HttpPostJson = Any
DEFAULT_INTENT_PROVIDER = "auto"
DEFAULT_INTENT_TIMEOUT_SECONDS = 10.0
_ALLOWED_PROVIDERS = {"auto", "rules", "ollama", "openai"}
_LOW_CONFIDENCE = 0.2
_INVALID_LLM_CONFIDENCE = 0.1

_ENTRY_KIND_BY_INTENT: dict[str, Intent] = {
    "weapon": Intent.ATTACK,
    "spell": Intent.CAST_SPELL,
    "item": Intent.USE_ITEM,
    "feature": Intent.USE_FEATURE,
}
_MATCHABLE_ENTRY_KINDS = frozenset(_ENTRY_KIND_BY_INTENT.keys())
_DEFAULT_COMPENDIUM_MATCHERS: list[tuple[str, str, CompendiumEntry]] | None = None

_INTENT_VERBS: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    (
        Intent.ATTACK,
        (
            "attack",
            "strike",
            "hit",
            "swing",
            "lunge",
            "stab",
            "slash",
            "shoot",
            "fire",
            "punch",
            "kick",
        ),
    ),
    (
        Intent.CAST_SPELL,
        (
            "cast",
            "unleash",
            "invoke",
        ),
    ),
    (
        Intent.TALK,
        (
            "talk",
            "speak",
            "ask",
            "say",
            "chat",
            "greet",
            "haggle",
            "persuade",
            "intimidate",
        ),
    ),
    (
        Intent.SEARCH,
        (
            "search",
            "look",
            "inspect",
            "examine",
            "check",
            "scan",
            "investigate",
            "explore",
        ),
    ),
    (
        Intent.OBJECT_INTERACTION,
        (
            "open",
            "close",
            "take",
            "grab",
            "pick up",
            "drop",
            "equip",
            "unequip",
            "interact with",
            "use",
        ),
    ),
    (
        Intent.DISENGAGE,
        (
            "flee",
            "run",
            "escape",
            "retreat",
            "disengage",
            "withdraw",
            "end combat",
        ),
    ),
)

_TARGET_REMOVE_WORDS = {
    "my",
    "to",
    "at",
    "on",
    "in",
    "into",
    "with",
    "using",
    "around",
    "the",
    "a",
    "an",
}
_DISENGAGE_NO_TARGET_WORDS = {"away", "off", "out"}


class HybridIntentRouter:
    """Rules-first router with optional LLM fallback for unknown inputs."""

    def __init__(
        self,
        provider: str | None = None,
        http_post_json: HttpPostJson | None = None,
        timeout_seconds: float = DEFAULT_INTENT_TIMEOUT_SECONDS,
        compendium_store: CompendiumStore | None = None,
    ) -> None:
        self.provider = _resolve_provider(provider)
        self._http_post_json = http_post_json or post_json
        self.timeout_seconds = timeout_seconds
        self._compendium_matchers: list[tuple[str, str, CompendiumEntry]] = []
        if compendium_store is not None:
            self._compendium_matchers = _build_compendium_matchers(
                compendium_store.entries,
            )
        else:
            self._compendium_matchers = _load_default_compendium_matchers()

    def route(self, text: str, current_mode: GameMode) -> IntentResult:
        rule_result = self._route_rules(text)
        if rule_result.intent != Intent.UNKNOWN:
            return self._validate(rule_result, current_mode)

        if self.provider == "rules":
            return self._validate(rule_result, current_mode)

        llm_provider = self._resolve_fallback_provider()
        if llm_provider is None:
            return self._validate(
                _unknown_result(
                    provider="none",
                    confidence=_LOW_CONFIDENCE,
                    rationale="no llm provider available",
                ),
                current_mode,
            )

        llm_result = self._route_with_llm(text=text, provider=llm_provider)
        return self._validate(llm_result, current_mode)

    def _resolve_fallback_provider(self) -> str | None:
        if self.provider in {"openai", "ollama"}:
            return self.provider
        if self.provider == "rules":
            return None
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        if os.environ.get("OLLAMA_BASE_URL"):
            return "ollama"
        return None

    def _route_rules(self, text: str) -> IntentResult:
        stripped = text.strip()
        normalized = stripped.lower()
        normalized_for_match = _normalize_for_matching(normalized)
        if not normalized:
            return _unknown_result(
                provider="rules",
                confidence=_LOW_CONFIDENCE,
                rationale="empty input",
            )

        match = _find_first_verb_match(normalized_for_match)
        compendium_match = _find_compendium_match(
            normalized_for_match,
            self._compendium_matchers,
        )
        if compendium_match is None and match is None:
            return _unknown_result(
                provider="rules",
                confidence=_LOW_CONFIDENCE,
                rationale="no rules match",
            )

        if compendium_match is not None:
            entry, _, _, match_start, match_end = compendium_match
            entry_intent = _entry_intent(entry)
            if entry_intent is None:
                return _unknown_result(
                    provider="rules",
                    confidence=_LOW_CONFIDENCE,
                    rationale=f"unhandled compendium kind: {entry.kind}",
                )

            residual = _remove_text_span(
                text=normalized_for_match,
                start=match_start,
                end=match_end,
            )
            residual_match = _find_first_verb_match(residual)
            verb_index = residual_match[2] if residual_match is not None else None
            verb_end = residual_match[3] if residual_match is not None else None
            intent = _resolve_compendium_intent(
                entry_intent=entry_intent,
                verb=residual_match[1] if residual_match is not None else None,
            )

            if residual_match is None:
                confidence = 0.9
            else:
                confidence = 0.95 if verb_index == 0 else 0.85
            target = _extract_target_after_match(
                normalized_for_match=residual,
                match_end=verb_end or 0,
                intent=intent,
            )
            rationale = f"matched compendium {entry.kind}: {entry.name}"
            if residual_match is not None:
                rationale = f"matched verb '{residual_match[1]}' and {rationale}"

            return IntentResult(
                intent=intent,
                mechanic=_intent_to_mechanic(intent),
                confidence=confidence,
                rationale=rationale,
                target=target,
                provider_used="rules",
                is_valid=True,
                action_category=_intent_to_action_category(intent),
                entry_id=entry.id,
                entry_kind=entry.kind,
                entry_name=entry.name,
            )

        if match is None:
            return _unknown_result(
                provider="rules",
                confidence=_LOW_CONFIDENCE,
                rationale="no rules match",
            )

        intent, verb, start_index, end_index = match
        confidence = 0.95 if start_index == 0 else 0.75
        target_raw = stripped[end_index:]
        target = _normalize_target(target_raw, intent)

        return IntentResult(
            intent=intent,
            mechanic=_intent_to_mechanic(intent),
            confidence=confidence,
            rationale=f"matched synonym: {verb}",
            target=target,
            provider_used="rules",
            is_valid=True,
            action_category=_intent_to_action_category(intent),
            entry_id=None,
            entry_kind=None,
            entry_name=None,
        )

    def _route_with_llm(self, text: str, provider: str) -> IntentResult:
        user_prompt = _build_llm_prompt(text)
        try:
            if provider == "openai":
                raw_content = _classify_with_openai(
                    text_prompt=user_prompt,
                    timeout_seconds=self.timeout_seconds,
                    http_post_json=self._http_post_json,
                )
            else:
                raw_content = _classify_with_ollama(
                    text_prompt=user_prompt,
                    timeout_seconds=self.timeout_seconds,
                    http_post_json=self._http_post_json,
                )
            return _parse_llm_json_result(raw_content, provider)
        except Exception:
            return _unknown_result(
                provider=provider,
                confidence=_INVALID_LLM_CONFIDENCE,
                rationale="llm classification failed",
            )

    def _validate(self, result: IntentResult, current_mode: GameMode) -> IntentResult:
        # Minimal validation for this slice: social/exploration actions in combat are contested.
        if current_mode == GameMode.COMBAT and result.intent in {
            Intent.SEARCH,
            Intent.TALK,
            Intent.OBJECT_INTERACTION,
        }:
            return IntentResult(
                intent=result.intent,
                mechanic=Mechanic.CLARIFY,
                confidence=0.4,
                rationale="action during combat needs clarification",
                target=result.target,
                provider_used=result.provider_used,
                is_valid=False,
                action_category=result.action_category,
                entry_id=result.entry_id,
                entry_kind=result.entry_kind,
                entry_name=result.entry_name,
            )
        return result


# Backward-compatible name used across the codebase/tests.
IntentRouter = HybridIntentRouter


def _resolve_provider(provider: str | None) -> str:
    raw = provider or os.environ.get("INTENT_PROVIDER") or DEFAULT_INTENT_PROVIDER
    normalized = raw.strip().lower()
    if normalized not in _ALLOWED_PROVIDERS:
        raise ValueError(
            "--intent-provider must be one of: auto, rules, ollama, openai"
        )
    return normalized


def _find_first_verb_match(
    normalized_text: str,
) -> tuple[Intent, str, int, int] | None:
    matches: list[tuple[int, int, Intent, str, int]] = []
    for intent, verbs in _INTENT_VERBS:
        for verb in verbs:
            pattern = rf"\b{re.escape(verb)}\b"
            for match in re.finditer(pattern, normalized_text):
                matches.append(
                    (
                        match.start(),
                        -len(verb),
                        intent,
                        verb,
                        match.end(),
                    )
                )
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1], item[3], item[2]))
    best = matches[0]
    return best[2], best[3], best[0], best[4]


def _resolve_compendium_intent(
    entry_intent: Intent,
    verb: str | None,
) -> Intent:
    if entry_intent == Intent.CAST_SPELL:
        return Intent.CAST_SPELL
    if verb is None:
        return entry_intent
    if entry_intent == Intent.USE_FEATURE and verb in {"use", "activate"}:
        return Intent.USE_FEATURE
    if entry_intent == Intent.USE_ITEM and verb in {"use", "activate", "drink", "draw"}:
        return Intent.USE_ITEM
    return entry_intent


def _remove_text_span(text: str, start: int, end: int) -> str:
    if start < 0 or end < start or end > len(text):
        return text
    trimmed = f"{text[:start]} {text[end:]}"
    return _normalize_for_matching(trimmed)


def _load_default_compendium_matchers() -> list[tuple[str, str, CompendiumEntry]]:
    global _DEFAULT_COMPENDIUM_MATCHERS

    if _DEFAULT_COMPENDIUM_MATCHERS is not None:
        return _DEFAULT_COMPENDIUM_MATCHERS

    try:
        store = CompendiumStore()
        store.load(resolve_compendium_roots("compendiums"))
        _DEFAULT_COMPENDIUM_MATCHERS = _build_compendium_matchers(store.entries)
        return _DEFAULT_COMPENDIUM_MATCHERS
    except (OSError, CompendiumLoadError):
        _DEFAULT_COMPENDIUM_MATCHERS = []
        return _DEFAULT_COMPENDIUM_MATCHERS


def _build_compendium_matchers(
    entries: list[CompendiumEntry],
) -> list[tuple[str, str, CompendiumEntry]]:
    matchers: list[tuple[str, str, CompendiumEntry]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if entry.kind not in _MATCHABLE_ENTRY_KINDS:
            continue
        candidate_phrases = [entry.name, *entry.aliases]
        for phrase in candidate_phrases:
            normalized_name = _normalize_for_matching(phrase)
            compact_name = compact_compendium_text(phrase)
            if not normalized_name or not compact_name:
                continue
            dedupe_key = (entry.id, normalized_name)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            matchers.append((normalized_name, compact_name, entry))

    matchers.sort(key=lambda item: (-len(item[1]), -len(item[0]), item[0], item[2].id))
    return matchers


def _find_compendium_match(
    normalized_text: str,
    matchers: list[tuple[str, str, CompendiumEntry]],
) -> tuple[CompendiumEntry, str, int, int, int] | None:
    """Return (entry, normalized_name, start, end, intent) for the best match."""
    if not normalized_text or not matchers:
        return None

    matches: list[tuple[int, int, int, str, CompendiumEntry]] = []
    seen_matches: set[tuple[int, int, str, str]] = set()
    for normalized_name, compact_name, entry in matchers:
        start = 0
        while True:
            index = normalized_text.find(normalized_name, start)
            if index == -1:
                break
            end = index + len(normalized_name)
            if _has_word_boundaries(normalized_text, index, end):
                _record_compendium_match(
                    matches=matches,
                    seen=seen_matches,
                    start=index,
                    end=end,
                    compact_len=len(compact_name),
                    normalized_name=normalized_name,
                    entry=entry,
                )
            start = index + 1

    compact_lookup: dict[str, list[tuple[str, CompendiumEntry]]] = {}
    max_phrase_tokens = 1
    for normalized_name, compact_name, entry in matchers:
        compact_lookup.setdefault(compact_name, []).append((normalized_name, entry))
        max_phrase_tokens = max(max_phrase_tokens, len(normalized_name.split()))

    tokens = _token_spans(normalized_text)
    max_window_tokens = max_phrase_tokens + 1
    for start_token in range(len(tokens)):
        compact_candidate = ""
        for end_token in range(
            start_token, min(len(tokens), start_token + max_window_tokens)
        ):
            compact_candidate += tokens[end_token][0]
            candidates = compact_lookup.get(compact_candidate)
            if candidates is None:
                continue
            span_start = tokens[start_token][1]
            span_end = tokens[end_token][2]
            for normalized_name, entry in candidates:
                _record_compendium_match(
                    matches=matches,
                    seen=seen_matches,
                    start=span_start,
                    end=span_end,
                    compact_len=len(compact_candidate),
                    normalized_name=normalized_name,
                    entry=entry,
                )

    if not matches:
        return None

    matches.sort(key=lambda match: (-match[2], match[0], match[3], match[4].id))
    start, end, compact_len, normalized_name, entry = matches[0]
    return entry, normalized_name, compact_len, start, end


def _has_word_boundaries(text: str, start: int, end: int) -> bool:
    if start < 0 or end > len(text) or start > end:
        return False
    before = start == 0 or text[start - 1] == " "
    after = end == len(text) or text[end] == " "
    return before and after


def _normalize_for_matching(raw_text: str) -> str:
    return normalize_compendium_text(raw_text)


def _token_spans(normalized_text: str) -> list[tuple[str, int, int]]:
    return [
        (match.group(0), match.start(), match.end())
        for match in re.finditer(r"\S+", normalized_text)
    ]


def _record_compendium_match(
    matches: list[tuple[int, int, int, str, CompendiumEntry]],
    seen: set[tuple[int, int, str, str]],
    start: int,
    end: int,
    compact_len: int,
    normalized_name: str,
    entry: CompendiumEntry,
) -> None:
    key = (start, end, normalized_name, entry.id)
    if key in seen:
        return
    seen.add(key)
    matches.append((start, end, compact_len, normalized_name, entry))


def _extract_target_after_match(
    normalized_for_match: str, match_end: int, intent: Intent
) -> str | None:
    raw_target = normalized_for_match[match_end:]
    return _normalize_target(raw_target, intent)


def _normalize_target(raw: str, intent: Intent) -> str | None:
    normalized = raw.lower().strip()
    normalized = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", normalized)
    if not normalized:
        return None

    words = normalized.split()
    while words and words[0] in _TARGET_REMOVE_WORDS:
        words.pop(0)
    while words and words[-1] in _TARGET_REMOVE_WORDS:
        words.pop()

    if not words:
        return None
    if intent == Intent.DISENGAGE and all(
        word in _DISENGAGE_NO_TARGET_WORDS for word in words
    ):
        return None
    return " ".join(words)


def _unknown_result(provider: str, confidence: float, rationale: str) -> IntentResult:
    return IntentResult(
        intent=Intent.UNKNOWN,
        mechanic=Mechanic.CLARIFY,
        confidence=confidence,
        rationale=rationale,
        target=None,
        provider_used=provider,
        is_valid=False,
        action_category=ActionCategory.PRIMARY_ACTION,
    )


def _build_llm_prompt(text: str) -> str:
    return (
        "Allowed intents: attack, cast_spell, use_item, use_feature, "
        "talk, search, interact, disengage, unknown.\n"
        "Return JSON only with exactly these keys: intent, target, confidence.\n"
        "Do not include extra keys or prose.\n"
        "Examples:\n"
        'Input: "I lunge at the goblin"\n'
        'Output: {"intent":"attack","target":"goblin","confidence":0.75}\n'
        'Input: "I cast magic missile at the goblin"\n'
        'Output: {"intent":"cast_spell","target":"goblin","confidence":0.75}\n'
        'Input: "I strike the guard"\n'
        'Output: {"intent":"attack","target":"guard","confidence":0.75}\n'
        'Input: "I speak to the innkeeper"\n'
        'Output: {"intent":"talk","target":"innkeeper","confidence":0.75}\n'
        'Input: "I open the gate"\n'
        'Output: {"intent":"interact","target":"gate","confidence":0.75}\n'
        'Input: "I examine the room"\n'
        'Output: {"intent":"search","target":"room","confidence":0.75}\n'
        'Input: "I run away"\n'
        'Output: {"intent":"disengage","target":null,"confidence":0.75}\n'
        f'Input: "{text}"'
    )


def _classify_with_ollama(
    text_prompt: str,
    timeout_seconds: float,
    http_post_json: HttpPostJson,
) -> str:
    base_url = (os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip(
        "/"
    )
    model = os.environ.get("OLLAMA_MODEL") or "llama3"
    payload = {
        "model": model,
        "stream": False,
        "prompt": ("You are a classifier. Output JSON only.\n" f"{text_prompt}"),
    }
    response = http_post_json(
        url=f"{base_url}/api/generate",
        payload=payload,
        timeout_seconds=timeout_seconds,
    )
    content = response.get("response")
    if not isinstance(content, str):
        raise ValueError("ollama response missing text")
    return content


def _classify_with_openai(
    text_prompt: str,
    timeout_seconds: float,
    http_post_json: HttpPostJson,
) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for openai intent provider")
    base_url = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com").rstrip(
        "/"
    )
    model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a classifier. Output JSON only."},
            {"role": "user", "content": text_prompt},
        ],
        "temperature": 0,
    }
    response = http_post_json(
        url=f"{base_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        payload=payload,
        timeout_seconds=timeout_seconds,
    )
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("openai response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("openai response choice invalid")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("openai response missing message")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("openai response missing content")
    return content


def _parse_llm_json_result(content: str, provider: str) -> IntentResult:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return _unknown_result(
            provider=provider,
            confidence=_INVALID_LLM_CONFIDENCE,
            rationale="invalid llm json",
        )
    if not isinstance(parsed, dict):
        return _unknown_result(
            provider=provider,
            confidence=_INVALID_LLM_CONFIDENCE,
            rationale="invalid llm payload",
        )

    if set(parsed.keys()) != {"intent", "target", "confidence"}:
        return _unknown_result(
            provider=provider,
            confidence=_INVALID_LLM_CONFIDENCE,
            rationale="llm json keys invalid",
        )

    raw_intent = parsed.get("intent")
    if not isinstance(raw_intent, str):
        return _unknown_result(
            provider=provider,
            confidence=_INVALID_LLM_CONFIDENCE,
            rationale="llm intent invalid",
        )
    intent = _parse_intent(raw_intent.strip().lower())
    if intent is None:
        return _unknown_result(
            provider=provider,
            confidence=_INVALID_LLM_CONFIDENCE,
            rationale="llm intent out of schema",
        )

    confidence = _parse_confidence(parsed.get("confidence"))
    target: str | None = None
    raw_target = parsed.get("target")
    if isinstance(raw_target, str):
        target = _normalize_target(raw_target, intent)
    elif raw_target is not None:
        return _unknown_result(
            provider=provider,
            confidence=_INVALID_LLM_CONFIDENCE,
            rationale="llm target invalid",
        )
    mechanic = _intent_to_mechanic(intent)
    is_valid = intent != Intent.UNKNOWN

    return IntentResult(
        intent=intent,
        mechanic=mechanic,
        confidence=confidence,
        rationale=f"classified via {provider}",
        target=target,
        provider_used=provider,
        is_valid=is_valid,
        action_category=_intent_to_action_category(intent),
    )


def _parse_confidence(raw: object) -> float:
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw)
        except ValueError:
            return 0.2
    else:
        return 0.2
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _parse_intent(raw: str) -> Intent | None:
    mapping = {
        "attack": Intent.ATTACK,
        "cast_spell": Intent.CAST_SPELL,
        "use_item": Intent.USE_ITEM,
        "use_feature": Intent.USE_FEATURE,
        "talk": Intent.TALK,
        "search": Intent.SEARCH,
        "interact": Intent.OBJECT_INTERACTION,
        "disengage": Intent.DISENGAGE,
        "unknown": Intent.UNKNOWN,
    }
    return mapping.get(raw)


def _intent_to_mechanic(intent: Intent) -> Mechanic:
    if intent in {Intent.ATTACK, Intent.CAST_SPELL}:
        return Mechanic.COMBAT_ROLL
    if intent == Intent.DISENGAGE:
        return Mechanic.DISENGAGE
    if intent in {
        Intent.TALK,
        Intent.SEARCH,
        Intent.OBJECT_INTERACTION,
        Intent.USE_ITEM,
        Intent.USE_FEATURE,
    }:
        return Mechanic.NARRATE_ONLY
    return Mechanic.CLARIFY


def _entry_intent(entry: CompendiumEntry) -> Intent | None:
    return _ENTRY_KIND_BY_INTENT.get(entry.kind)


def _intent_to_action_category(intent: Intent) -> ActionCategory:
    if intent in {Intent.ATTACK, Intent.DISENGAGE}:
        return ActionCategory.PRIMARY_ACTION
    if intent == Intent.OBJECT_INTERACTION:
        return ActionCategory.OBJECT_INTERACTION
    if intent == Intent.TALK:
        return ActionCategory.BRIEF_SPEECH
    if intent == Intent.SEARCH:
        return ActionCategory.FREE_OBSERVATION
    return ActionCategory.PRIMARY_ACTION
