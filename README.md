# totalworldcup

Minimal MVP tournament simulation for the **Global Knockout Cup** concept.

## Project instructions

See [PROJECT_INSTRUCTIONS.md](PROJECT_INSTRUCTIONS.md) for the dev/designer workflow, feature rules, and roadmap toward the football RPG direction.

For the real-time penalty game mode plan, see [REALTIME_PENALTY_MODE_DESIGN.md](REALTIME_PENALTY_MODE_DESIGN.md).

## Included

- 211 generated national teams with seed, penalty strength, and goalkeeper rating
- Snake-seeded regional assignment across Germany, England/UK, France, and Spain
- Phase 1 knockout flow: Preliminary (166 teams), Round of 128, Round of 64
- Open redraw at the last 32 teams, then fixed rounds to a champion
- Penalty-shootout match engine with:
  - alternating kicks
  - early finish when comeback becomes impossible
  - sudden death after 5-5 kick sets
- Manual control hooks for team shot-direction choice
- Auto-simulated tournament progression

## Run tests

```bash
python -m unittest discover -s tests -q
```

## Play real-time penalty mode

```bash
python realtime_penalty_mode.py
```

Optional reproducible auto-sim smoke test:

```bash
python realtime_penalty_mode.py --auto --seed 42
```

## Play featured-team tournament mode

Play a full tournament where only your featured team's matches are real-time and all other matches auto-sim:

```bash
python tournament_featured_mode.py --featured-seed 1
```

Optional reproducible auto-run:

```bash
python tournament_featured_mode.py --featured-seed 1 --auto --seed 7
```

## Current game readiness

- **Done:** 211-team setup, full knockout progression, and tested penalty shootouts.
- **Next:** interactive CLI flow, richer match logs, and save/resume support.
- **Playable?** Yes — currently as an auto-simulated tournament run.
