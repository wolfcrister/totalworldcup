from __future__ import annotations

import argparse
import platform
import time
from random import Random
from typing import Optional

from global_knockout_cup import Direction, PenaltyShootoutEngine, ShootoutResult, Team, clamp, generate_teams

_DIRECTION_MAP = {
    "a": "left",
    "s": "centre",
    "d": "right",
    "left": "left",
    "centre": "centre",
    "center": "centre",
    "right": "right",
}

_DIVE_MAP = {
    "j": "left",
    "k": "centre",
    "l": "right",
    "left": "left",
    "centre": "centre",
    "center": "centre",
    "right": "right",
}


def _normalize_direction(raw: str, mapping: dict[str, Direction]) -> Optional[Direction]:
    key = raw.strip().lower()
    return mapping.get(key)


def _prompt_direction(prompt: str, mapping: dict[str, Direction], auto: bool, rng: Random) -> Direction:
    if auto:
        return rng.choice(("left", "centre", "right"))

    while True:
        raw = input(prompt).strip()
        direction = _normalize_direction(raw, mapping)
        if direction is not None:
            return direction
        print("Invalid input. Try again.")


def _sample_ai_timing(team: Team, rng: Random) -> float:
    base = 0.5 + (team.penalty_strength - 0.5) * 0.30
    jitter = rng.uniform(-0.20, 0.20)
    return clamp(base + jitter, 0.0, 1.0)


def _timing_quality_realtime(rng: Random, auto: bool, seconds: float = 1.8) -> float:
    if auto:
        return rng.uniform(0.35, 0.90)

    if platform.system().lower() == "windows":
        import msvcrt

        print("Timing meter: press SPACE to lock timing.")
        start = time.perf_counter()
        width = 25

        while True:
            elapsed = time.perf_counter() - start
            if elapsed >= seconds:
                print("\nTime up.")
                return 0.25

            progress = elapsed / seconds
            triangle = progress * 2.0 if progress <= 0.5 else (1.0 - progress) * 2.0
            cursor_idx = min(width - 1, max(0, int(triangle * (width - 1))))

            bar = ["-"] * width
            bar[cursor_idx] = "|"
            center = width // 2
            bar[center] = "G"
            print("\r[" + "".join(bar) + "]", end="", flush=True)

            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch == " ":
                    quality = max(0.0, 1.0 - abs(triangle - 0.5) * 2.0)
                    print()
                    return quality
            time.sleep(0.03)

    while True:
        raw = input("Timing fallback (0-100): ").strip()
        if raw.isdigit():
            value = int(raw)
            if 0 <= value <= 100:
                return value / 100.0
        print("Enter a whole number from 0 to 100.")


def _print_header(player: Team, opponent: Team, auto: bool, title: str = "Real-Time Penalty Shootout") -> None:
    print("\n=== Real-Time Penalty Shootout ===")
    if title != "Real-Time Penalty Shootout":
        print(title)
    print(f"You: {player.name} (seed {player.seed})")
    print(f"AI : {opponent.name} (seed {opponent.seed})")
    if not auto:
        print("Shooter controls: A left, S centre, D right")
        print("Keeper controls : J left, K centre, L right")


def play_realtime_match(
    engine: PenaltyShootoutEngine,
    human_team: Team,
    ai_team: Team,
    auto: bool = False,
    title: str = "Real-Time Penalty Shootout",
) -> ShootoutResult:
    rng = engine.rng
    _print_header(human_team, ai_team, auto, title=title)

    def choose_player_shot(_: Team, __: Team, kick_index: int) -> Direction:
        return _prompt_direction(f"Kick {kick_index} shot (A/S/D): ", _DIRECTION_MAP, auto, rng)

    def choose_ai_shot(team: Team, _: Team, __: int) -> Direction:
        weights = [0.34, 0.32, 0.34]
        if team.penalty_strength > 0.75:
            weights = [0.38, 0.24, 0.38]
        return rng.choices(("left", "centre", "right"), weights=weights, k=1)[0]

    def choose_player_dive(_: Team, __: Team, kick_index: int) -> Direction:
        return _prompt_direction(f"Kick {kick_index} dive (J/K/L): ", _DIVE_MAP, auto, rng)

    def choose_ai_dive(team: Team, _: Team, __: int) -> Direction:
        weights = [0.33, 0.34, 0.33]
        if team.goalkeeper_rating > 0.75:
            weights = [0.36, 0.28, 0.36]
        return rng.choices(("left", "centre", "right"), weights=weights, k=1)[0]

    result = engine.shootout(
        human_team,
        ai_team,
        chooser_a=choose_player_shot,
        chooser_b=choose_ai_shot,
        dive_chooser_a=choose_player_dive,
        dive_chooser_b=choose_ai_dive,
        timing_chooser_a=lambda *_: _timing_quality_realtime(rng, auto),
        timing_chooser_b=lambda team, *_: _sample_ai_timing(team, rng),
    )

    print("\n--- Shootout Result ---")
    print(f"Final: {human_team.name} {result.score_a} - {result.score_b} {ai_team.name}")
    if result.winner == human_team:
        print("You win.")
    else:
        print("AI wins.")
    return result


def run_single_match(auto: bool = False, seed: Optional[int] = None) -> int:
    rng = Random(seed)
    teams = generate_teams(64)

    player = teams[rng.randrange(0, 32)]
    opponent = teams[rng.randrange(32, 64)]

    engine = PenaltyShootoutEngine(rng)
    result = play_realtime_match(engine, player, opponent, auto=auto)
    if result.winner == player:
        return 0
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Play a simple terminal real-time penalty shootout.")
    parser.add_argument("--auto", action="store_true", help="Run without interactive input.")
    parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed for reproducible sessions.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return run_single_match(auto=args.auto, seed=args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
