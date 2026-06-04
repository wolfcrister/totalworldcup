from __future__ import annotations

import argparse
from random import Random
from typing import Iterable, Optional

from global_knockout_cup import GlobalKnockoutCup, Match, Team, TournamentOutcome, create_seeded_pairings
from realtime_penalty_mode import play_realtime_match


def _pick_featured_team(cup: GlobalKnockoutCup, seed: Optional[int]) -> Team:
    if seed is None:
        return cup.teams[0]
    for team in cup.teams:
        if team.seed == seed:
            return team
    raise ValueError(f"No team exists with seed {seed}.")


def _round_matches_seeded(teams: Iterable[Team], round_name: str) -> tuple[Match, ...]:
    return tuple(Match(pair.team_a, pair.team_b, round_name) for pair in create_seeded_pairings(teams))


def _round_matches_open(rng: Random, teams: Iterable[Team], round_name: str) -> tuple[Match, ...]:
    pool = list(teams)
    rng.shuffle(pool)
    return tuple(Match(pool[i], pool[i + 1], round_name) for i in range(0, len(pool), 2))


def _play_round(
    cup: GlobalKnockoutCup,
    matches: tuple[Match, ...],
    featured_team_seed: int,
    auto: bool,
) -> tuple[Team, ...]:
    winners: list[Team] = []
    for idx, match in enumerate(matches, start=1):
        involves_featured = match.team_a.seed == featured_team_seed or match.team_b.seed == featured_team_seed
        if involves_featured:
            print(f"\n[Featured Match {idx}/{len(matches)}] {match.team_a.name} vs {match.team_b.name}")
            if match.team_a.seed == featured_team_seed:
                result = play_realtime_match(
                    cup.shootout_engine,
                    human_team=match.team_a,
                    ai_team=match.team_b,
                    auto=auto,
                    title=f"{match.round_name} - Featured Match",
                )
                winners.append(result.winner)
            else:
                result = play_realtime_match(
                    cup.shootout_engine,
                    human_team=match.team_b,
                    ai_team=match.team_a,
                    auto=auto,
                    title=f"{match.round_name} - Featured Match",
                )
                winners.append(result.winner)
        else:
            winners.append(cup.play_match(match))
    return tuple(winners)


def run_featured_tournament(
    featured_seed: Optional[int] = None,
    auto: bool = False,
    rng_seed: Optional[int] = None,
) -> TournamentOutcome:
    rng = Random(rng_seed)
    cup = GlobalKnockoutCup(rng=rng)
    featured_team = _pick_featured_team(cup, featured_seed)
    print(f"Featured team: {featured_team.name} (seed {featured_team.seed})")

    rounds: dict[str, tuple[Match, ...]] = {}

    plan = cup.create_tournament_plan()
    rounds["Preliminary Round"] = plan.preliminary_matches
    preliminary_winners = _play_round(cup, plan.preliminary_matches, featured_team.seed, auto)

    phase1_128_teams = tuple(sorted((*plan.preliminary_byes, *preliminary_winners), key=lambda t: t.seed))
    round_128_matches = _round_matches_seeded(phase1_128_teams, "Round of 128")
    rounds["Round of 128"] = round_128_matches
    round_64_teams = _play_round(cup, round_128_matches, featured_team.seed, auto)

    round_64_matches = _round_matches_seeded(round_64_teams, "Round of 64")
    rounds["Round of 64"] = round_64_matches
    qualified_32 = _play_round(cup, round_64_matches, featured_team.seed, auto)

    current = qualified_32
    for round_name, winner_count in (
        ("Round of 32", 16),
        ("Round of 16", 8),
        ("Quarterfinal", 4),
        ("Semifinal", 2),
        ("Final", 1),
    ):
        matches = _round_matches_open(rng, current, round_name)
        rounds[round_name] = matches
        current = _play_round(cup, matches, featured_team.seed, auto)
        if len(current) != winner_count:
            raise ValueError(f"Unexpected winner count in {round_name}: {len(current)}")

    outcome = TournamentOutcome(champion=current[0], phase1_qualified_32=qualified_32, rounds=rounds)
    print("\n=== Tournament Complete ===")
    print(f"Champion: {outcome.champion.name} (seed {outcome.champion.seed})")
    if outcome.champion.seed == featured_team.seed:
        print("Featured team won the cup.")
    else:
        print("Featured team did not win the cup.")
    return outcome


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a full tournament where featured-team matches are played in real-time penalty mode."
    )
    parser.add_argument(
        "--featured-seed",
        type=int,
        default=1,
        help="Team seed to control in featured matches (default: 1).",
    )
    parser.add_argument("--auto", action="store_true", help="Run featured matches without interactive input.")
    parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed for reproducible tournament draws.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    run_featured_tournament(featured_seed=args.featured_seed, auto=args.auto, rng_seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
