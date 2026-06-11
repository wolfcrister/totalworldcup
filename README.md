# totalworldcup

Minimal MVP tournament simulation for the **Global Knockout Cup** concept.

## Project instructions

See [PROJECT_INSTRUCTIONS.md](PROJECT_INSTRUCTIONS.md) for the dev/designer workflow, feature rules, and roadmap toward the football RPG direction.

For the real-time penalty game mode plan, see [REALTIME_PENALTY_MODE_DESIGN.md](REALTIME_PENALTY_MODE_DESIGN.md).

For the visual EXE roadmap and nation-list plan, see [VISUAL_EXE_AND_NATIONS_PLAN.md](VISUAL_EXE_AND_NATIONS_PLAN.md).

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

## Play visual penalty mode (Pygame)

```bash
python visual_penalty_game.py --mode single --featured-seed 1
```

Controls:
- Shot direction: LEFT / RIGHT, ENTER to confirm
- Timing: SPACE
- Keeper dive: LEFT / DOWN / RIGHT, ENTER to confirm

The shootout now alternates turns: you shoot, then you defend, and so on.

## Play visual tournament mode (Pygame)

```bash
python visual_penalty_game.py --mode tournament --featured-seed 1
```

In tournament mode, featured-team matches are playable and all other matches are auto-simulated.
At launch, you can select your team in-game before the tournament starts.
From Round of 32 onward, a visual playoff tree is shown between rounds.
After every round, a tournament results screen shows all match outcomes for that round.
That screen now also includes a compact timeline panel with featured-team path and biggest upsets so far.

Tournament results controls:
- ENTER / SPACE: continue to the next stage
- LEFT / RIGHT: switch round view
- UP / DOWN: scroll match list in the selected round

## Simplest way to run

Default (visual tournament):

```bash
python play_game.py
```

Single visual match:

```bash
python play_game.py --single
```

Randomness:
- Default: randomized each run.
- Reproducible run: pass `--seed`, for example `python play_game.py --seed 7`.

Windows double-click options:
- Play Tournament.bat
- Play Single Match.bat

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
