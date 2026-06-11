# Visual EXE + Nation List Plan

This plan turns the current terminal prototype into a simple visual game that ships as a Windows EXE, while introducing a proper nation dataset.

## Goal

- Build a lightweight visual penalty game loop.
- Keep the existing simulation engine as the source of truth.
- Package a playable Windows EXE.
- Replace placeholder team names with a real nation list.

## Recommended Tech Stack

- Runtime/UI: Python + Pygame CE
- Packaging: PyInstaller
- Data format: CSV (easy to edit by design)

Why this stack:
- Fastest path from current Python code to visual playable game.
- Easy Windows EXE packaging.
- Minimal rewrite risk because core logic can stay in existing modules.

## Architecture

1. Core domain (existing)
- Keep match rules in global_knockout_cup.py.
- Keep outcome determinism with RNG seed support.

2. Visual adapter (new)
- Create a game loop module that translates key inputs and timing into existing shootout calls.
- Use event stream (KickEvent) for HUD updates and replay text.

3. Data layer (new)
- Nation roster loaded from data/nations.csv.
- Team generation reads names and confederation metadata from file.

4. Packaging layer (new)
- Build script and PyInstaller spec for one-file EXE output.

## Milestones

### M1: Nation data foundation (1 day)
- Add data/nations.csv schema.
- Add loader with validation and clear errors.
- Add fallback to generated Nation 1..N if file missing.
- Tests for count/uniqueness/required columns.

### M2: Visual single-match penalty mode (2-3 days)
- Pygame window with simple pitch, goal, keeper marker, HUD score.
- Direction input + timing meter.
- Basic animations: ball travel, keeper dive, goal/miss flash.
- End screen with replay summary.

### M3: Featured-team tournament visual flow (2 days)
- Tournament map screen (simple bracket list is enough for V1).
- Auto-sim non-featured matches.
- Enter playable scene only on featured matches.
- Return to bracket after each played match.

### M4: EXE packaging and QA (1 day)
- PyInstaller build config.
- Create dist build task and run instructions.
- Smoke tests on clean machine (or fresh venv).

## Nation List Plan

Target dataset: 211 playable associations (to match current tournament size).

### Data schema

CSV columns:
- id: stable integer id
- name: display nation name
- fifa_code: short code
- confederation: AFC/CAF/CONCACAF/CONMEBOL/OFC/UEFA
- is_playable: true/false
- strength_tier: 1-5

### Validation rules

- Exactly 211 rows with is_playable=true.
- Unique name and fifa_code.
- No blank confederation values.
- Stable ordering by id for reproducible seeding.

### Content policy for names

- Use neutral, publicly known country/association names.
- Avoid logos/flags and trademarked assets in V1.
- Keep text-only assets for safe EXE distribution.

## Delivery Definition

- Player can open EXE and play a full featured-match shootout visually.
- Tournament continues between playable matches.
- Nation names are real dataset entries (not Nation 1..N).
- Existing tests pass; new data/UI adapter tests added.

## Immediate Sprint Tasks

1. Create nation file + loader.
2. Integrate names into team generation.
3. Add Pygame visual shootout scene.
4. Add basic build script for Windows EXE.
