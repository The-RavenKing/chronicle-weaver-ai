# Chronicle Weaver

Phase-1 repository skeleton for a deterministic AI RPG engine.

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

## Run CLI demo

```bash
source .venv/bin/activate
chronicle-weaver demo --player-input "attack goblin" --seed 42
```
