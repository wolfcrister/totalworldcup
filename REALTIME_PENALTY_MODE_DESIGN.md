# Real-Time Penalty Mode Design

Purpose: define a simple, fun, real-time player mode built on the existing penalty engine.

## Vision

- Deliver a fast arcade-feel penalty experience that can be played standalone or inside the tournament.
- Keep controls easy to learn in under 30 seconds.
- Reuse existing deterministic simulation logic where possible.

## Player Fantasy

- "I am in the pressure moment."
- "My timing and choices matter."
- "I can upset stronger teams if I stay calm."

## Mode Scope (V1)

- One human-controlled team vs AI opponent in a single shootout.
- Human acts as shooter and goalkeeper each turn.
- Best-of-5 with sudden death.
- Round duration target: 60-120 seconds.

Out of scope for V1:
- Full character progression systems.
- Network multiplayer.
- Advanced animation system.

## Core Loop

1. Match intro: show teams and pressure meter reset.
2. Kick phase:
- Shooter selects direction (left/centre/right).
- Shooter sets power timing with a short moving meter.
- Goalkeeper selects dive direction with reaction window.
3. Resolve result immediately with short feedback.
4. Update score and pressure state.
5. Repeat until early-finish or sudden-death conclusion.

## Input Design (Simple and Real-Time)

Shooter controls:
- `A` = left, `S` = centre, `D` = right.
- `Space` = lock power (timing).

Goalkeeper controls:
- `Left Arrow` = dive left.
- `Down Arrow` = hold centre.
- `Right Arrow` = dive right.

Accessibility fallback:
- Turn off timing and use direction-only mode.
- Optional slower timing meter.

## Game Feel Rules

- Timing meter width has a "green zone" center; result quality based on lock timing.
- Perfect timing: +accuracy and +power bonus.
- Poor timing: increased miss/save chance.
- Consecutive pressure moments slightly shrink green zone.

## Resolution Model

Current engine uses:
- shooter penalty strength
- goalkeeper rating
- shot vs dive direction
- pressure by kick number

V1 real-time extension adds:
- `timing_quality` in range 0.0-1.0
- `input_latency_bucket` (optional): early/normal/late

Proposed chance adjustment:
- `chance += (timing_quality - 0.5) * 0.20`
- clamp final chance to existing 0.20-0.95 bounds

This keeps compatibility with existing balancing while letting skill matter.

## Data Contract Additions

Add a lightweight event model for presentation and replay:

- `KickEvent`
- `phase`: "shooter_select" | "shooter_timing" | "keeper_select" | "resolve"
- `shot_direction`
- `dive_direction`
- `timing_quality`
- `scored`
- `score_a`, `score_b`
- `message`

Add optional metadata to shootout result:
- `events: tuple[KickEvent, ...]`

## Architecture Plan

Keep domain and interface separate:

- Domain layer (pure Python, testable)
- Extend `PenaltyShootoutEngine` with optional timing parameter.
- Add event-emitting API.

- Adapter layer (real-time loop)
- New module: `realtime_penalty_mode.py`
- Handles input polling, timing meter, and frame updates.
- Feeds direction + timing into domain layer.

- Presentation layer
- Start with terminal-based pseudo real-time refresh.
- Later migrate to richer UI without changing domain.

## CLI First Implementation Strategy

Use a time-step loop in terminal:
- 20 FPS text refresh target (best effort).
- Draw meter and cursor using simple ASCII bar.
- Accept keypresses with non-blocking reads (platform-aware handling).

If terminal key capture is unstable on Windows:
- Fall back to segmented prompts with countdown timers.
- Preserve same API so UI can be swapped later.

## AI Behavior (V1)

Shooter AI:
- Weighted random direction based on team penalty strength.
- Timing_quality sampled around team composure baseline.

Keeper AI:
- Weighted dive toward opponent historical tendencies (short memory of last 3 kicks).

## Balancing Targets

- Baseline conversion rate around 72%-82% across mixed seeds.
- Perfect-timing player should gain noticeable edge but not guaranteed goals.
- Strong seed should still have advantage over many kicks.

## Milestone Plan

1. Domain preparation
- Add timing-aware resolve function with defaults preserving old behavior.
- Add kick event structure.
- Tests for compatibility and timing impact.

2. Real-time single match CLI
- Implement standalone real-time shootout loop.
- Human shooter + keeper controls.
- End screen summary.

3. Tournament integration
- Add mode flag: auto, manual-turn, realtime-single-match.
- Use real-time only for featured matches, auto-sim for others.

4. Polish
- Better text effects and pacing controls.
- Optional commentary lines from event stream.

## Acceptance Criteria (V1)

- Player can complete a full shootout with real-time inputs.
- Early finish and sudden death still function correctly.
- Existing unit tests still pass.
- New tests cover timing quality behavior.
- Average match length stays under 2 minutes.

## Risks and Mitigations

- Risk: terminal real-time input inconsistency on Windows.
- Mitigation: provide countdown prompt fallback mode.

- Risk: timing bonus overwhelms stat-based balancing.
- Mitigation: cap timing effect and validate with seeded simulation tests.

- Risk: complexity creep.
- Mitigation: freeze V1 scope to one standalone mode.

## RPG Path Hooks

Design now so future RPG features plug in cleanly:
- Store per-manager "clutch" modifier affecting timing window.
- Track confidence streaks across tournament matches.
- Persist player tendency profile for AI adaptation.
