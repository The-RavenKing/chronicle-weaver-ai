# Chronicle Weaver

Deterministic AI RPG engine — Phase 1.

The backend owns all game state, dice, and mechanics. The LLM layer handles
intent classification and narrative prose only. No randomness or outcome
adjudication is ever delegated to the language model.

## Install dependencies

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Run tests

```bash
source .venv/bin/activate
pytest -q
```

## Run CLI demo (interactive)

```bash
source .venv/bin/activate
chronicle-weaver demo --player-input "attack goblin" --seed 42
```

## Run CLI demo (full encounter)

```bash
source .venv/bin/activate
chronicle-weaver demo --spawn goblin --seed 42 --compendium-root compendiums
```

## Run API server

```bash
source .venv/bin/activate
uvicorn chronicle_weaver_ai.api:app --reload
```

Open `http://localhost:8000` for the UI shell.
API docs at `http://localhost:8000/docs`.

## Current status

| Area | Status |
|------|--------|
| Deterministic dice / entropy (CSPRNG + drand) | ✅ |
| Intent routing (rules-first + LLM fallback) | ✅ |
| Compendium (weapons, spells, features, monsters) | ✅ |
| Combat resolution pipeline | ✅ |
| Encounter management + initiative | ✅ |
| Monster turns (AI v0) | ✅ |
| Narration (OpenAI + Ollama adapters) | ✅ |
| Campaign persistence (save/load JSON) | ✅ |
| FastAPI layer | ✅ |
| Minimal UI shell | ✅ |
| Healing / resource restoration | ❌ next |
| Conditions with mechanical effects | ❌ |
| Opportunity attacks / reactions | ❌ |
