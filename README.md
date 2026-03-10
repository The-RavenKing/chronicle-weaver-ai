# Chronicle Weaver

A **deterministic AI-driven tabletop RPG engine** built in Python.

The LLM generates words — the engine owns mechanics, dice, and outcomes.

---

## Features

- Deterministic combat: weapon attacks, spell casting, features, healing
- Monster turns with AI action selection and initiative management
- Conditions with mechanical effects (prone, poisoned, stunned)
- Opportunity attacks and reactions
- Inventory and equipment affecting AC and attack stats
- AoE spell targeting with saving throws
- Concentration spell tracking
- Campaign persistence (JSON save/load)
- Scene state and environmental context
- World clock and time advancement
- GM + Player persona system
- Companion personas
- Lore queue with Scribe approval workflow and conflict detection
- Hybrid lexical + n-gram TF-IDF retrieval
- State snapshots and rollback
- Short/long rest mechanics
- XP and levelling
- FastAPI HTTP layer
- Interactive browser UI

---

## Quickstart

### Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Run the API server

```bash
uvicorn chronicle_weaver_ai.api:app --reload
```

Open [http://localhost:8000](http://localhost:8000) for the browser UI.  
Open [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive API docs.

### CLI demo

```bash
# Basic exploration demo
chronicle-weaver demo

# Spawn a goblin and run a combat encounter
chronicle-weaver demo --spawn goblin

# List available compendium entries
chronicle-weaver compendium

# Interpret player intent
chronicle-weaver interpret "I attack the goblin with my longsword"
```

---

## Tests

```bash
pytest -q
```

566 tests passing.

---

## Architecture

See [`docs/ENGINE_PIPELINE.md`](docs/ENGINE_PIPELINE.md) for the full pipeline description.  
See [`docs/ARCHITECTURE_OVERVIEW.md`](docs/ARCHITECTURE_OVERVIEW.md) for the development roadmap.  
See [`docs/PROJECT_GLOSSARY.md`](docs/PROJECT_GLOSSARY.md) for terminology.

---

## Rules

All agents and contributors must follow [`AGENTS.md`](AGENTS.md).
