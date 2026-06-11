# Project Instructions

This document is the shared working agreement for **Total World Cup**.

## Team Roles

- Game Designer (you): defines feel, player fantasy, mode ideas, progression systems, and acceptance criteria.
- Developer (Copilot): implements systems, keeps code quality high, writes tests, and reports tradeoffs early.

## Product Direction

- Current product: simple and fun tournament simulator to validate knockout format and balancing assumptions.
- Long-term product: football-flavored RPG experience built on top of tournament structure.
- Design principle: keep each new feature playable quickly, then deepen it in layers.

## Core Design Pillars

- Fast to play: low friction, quick decisions, clear outcomes.
- Tournament-first: bracket integrity and progression clarity come before content breadth.
- Deterministic where needed: seeded structure should be testable and reproducible.
- Drama by design: penalty moments and underdog upsets should feel meaningful.

## Development Rules

- Keep the simulation engine decoupled from presentation (CLI/UI).
- Every new rule should be represented in unit tests.
- Prefer small vertical slices over big rewrites.
- Preserve backward compatibility in public API unless explicitly approved by designer.
- Track assumptions in code comments or docs when they impact game balance.

## Current Scope (MVP)

- 211 generated teams with seeded attributes.
- Snake regional assignment.
- Preliminary -> Round of 128 -> Round of 64 -> open redraw at 32 -> champion.
- Penalty shootout engine with early-finish and sudden-death logic.
- Auto-simulated full run.

## Next Milestones

1. Playable CLI match flow
- Prompt human choices for selected team(s).
- Show concise but dramatic kick-by-kick logs.
- Allow full auto mode and manual mode.

2. Tournament Presentation Layer
- Bracket snapshots per round.
- Match history and key moments.
- Session summary at tournament end.

3. Save/Resume Foundation
- Serialize tournament state.
- Resume from any round.
- Version save format for future compatibility.

4. RPG Transition (Early)
- Add one persistent manager profile.
- Add lightweight team identity stats (morale, chemistry, clutch).
- Introduce small progression rewards between rounds.

## Working Cadence

- Designer provides: feature intent, player fantasy, and "definition of fun".
- Developer returns: implementation, tests, and known edge cases.
- Each cycle ends with: what changed, what is validated, what to tune next.

## Definition of Done (Per Feature)

- Feature is playable.
- Feature has tests for normal and edge cases.
- Behavior and constraints are documented.
- No regressions in existing tournament flow.

## Immediate Backlog Candidates

- Human shot-direction chooser wiring in CLI.
- Detailed shootout event log object.
- Optional seeded RNG input for reproducible designer playtests.
- Upset-rate telemetry for balancing passes.
- Real-time penalty mode vertical slice (single-match, terminal-first).
- Replace placeholder team names with validated 211-entry nation dataset.
