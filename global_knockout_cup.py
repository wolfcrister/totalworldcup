from __future__ import annotations

from dataclasses import dataclass, field, replace
from random import Random
from typing import Callable, Iterable, Literal, Optional

Direction = Literal["left", "centre", "right"]


@dataclass(frozen=True)
class Team:
    name: str
    seed: int
    region: str = ""
    penalty_strength: float = 0.5
    goalkeeper_rating: float = 0.5


@dataclass(frozen=True)
class Match:
    team_a: Team
    team_b: Team
    round_name: str


@dataclass(frozen=True)
class Kick:
    team: Team
    direction: Direction
    keeper_dive: Direction
    scored: bool


@dataclass(frozen=True)
class ShootoutResult:
    winner: Team
    loser: Team
    score_a: int
    score_b: int
    kicks: tuple[Kick, ...]


@dataclass
class TournamentPlan:
    regions: dict[str, tuple[Team, ...]]
    preliminary_matches: tuple[Match, ...]
    preliminary_byes: tuple[Team, ...]


@dataclass
class TournamentOutcome:
    champion: Team
    phase1_qualified_32: tuple[Team, ...]
    rounds: dict[str, tuple[Match, ...]] = field(default_factory=dict)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def generate_teams(count: int = 211) -> tuple[Team, ...]:
    teams = []
    for seed in range(1, count + 1):
        strength = clamp(1.0 - ((seed - 1) / max(1, count - 1)), 0.0, 1.0)
        teams.append(
            Team(
                name=f"Nation {seed}",
                seed=seed,
                penalty_strength=strength,
                goalkeeper_rating=clamp(strength * 0.9 + 0.05, 0.0, 1.0),
            )
        )
    return tuple(teams)


def assign_regions_snake(
    teams: Iterable[Team],
    regions: tuple[str, ...] = ("Germany", "England/UK", "France", "Spain"),
) -> dict[str, tuple[Team, ...]]:
    ordered = sorted(teams, key=lambda t: t.seed)
    region_map: dict[str, list[Team]] = {r: [] for r in regions}
    for idx, team in enumerate(ordered):
        cycle = idx // len(regions)
        offset = idx % len(regions)
        region_idx = offset if cycle % 2 == 0 else (len(regions) - 1 - offset)
        region_name = regions[region_idx]
        region_map[region_name].append(replace(team, region=region_name))
    return {key: tuple(value) for key, value in region_map.items()}


class PenaltyShootoutEngine:
    def __init__(self, rng: Optional[Random] = None):
        self.rng = rng or Random()

    def resolve_kick(
        self,
        shooter: Team,
        goalkeeper: Team,
        shot_direction: Direction,
        keeper_dive: Direction,
        kick_number_for_shooter: int,
    ) -> bool:
        chance = 0.75
        chance += shooter.penalty_strength * 0.15
        chance -= goalkeeper.goalkeeper_rating * 0.15
        chance += 0.10 if shot_direction != keeper_dive else -0.30
        if shot_direction == "centre" and keeper_dive == "centre":
            chance -= 0.10
        pressure_penalty = min(0.10, max(0.0, (kick_number_for_shooter - 1) * 0.015))
        chance -= pressure_penalty
        chance = clamp(chance, 0.20, 0.95)
        return self.rng.random() < chance

    def shootout(
        self,
        team_a: Team,
        team_b: Team,
        chooser_a: Optional[Callable[[Team, Team, int], Direction]] = None,
        chooser_b: Optional[Callable[[Team, Team, int], Direction]] = None,
    ) -> ShootoutResult:
        chooser_a = chooser_a or (lambda *_: self.rng.choice(("left", "centre", "right")))
        chooser_b = chooser_b or (lambda *_: self.rng.choice(("left", "centre", "right")))

        kicks: list[Kick] = []
        score_a = 0
        score_b = 0
        taken_a = 0
        taken_b = 0

        for _ in range(5):
            taken_a += 1
            dir_a = chooser_a(team_a, team_b, taken_a)
            dive_b = self.rng.choice(("left", "centre", "right"))
            scored_a = self.resolve_kick(team_a, team_b, dir_a, dive_b, taken_a)
            score_a += int(scored_a)
            kicks.append(Kick(team_a, dir_a, dive_b, scored_a))

            if score_a > score_b + (5 - taken_b):
                return ShootoutResult(team_a, team_b, score_a, score_b, tuple(kicks))

            taken_b += 1
            dir_b = chooser_b(team_b, team_a, taken_b)
            dive_a = self.rng.choice(("left", "centre", "right"))
            scored_b = self.resolve_kick(team_b, team_a, dir_b, dive_a, taken_b)
            score_b += int(scored_b)
            kicks.append(Kick(team_b, dir_b, dive_a, scored_b))

            if score_b > score_a + (5 - taken_a):
                return ShootoutResult(team_b, team_a, score_a, score_b, tuple(kicks))
            if score_a > score_b + (5 - taken_b):
                return ShootoutResult(team_a, team_b, score_a, score_b, tuple(kicks))

        sudden_round = 5
        while True:
            sudden_round += 1
            dir_a = chooser_a(team_a, team_b, sudden_round)
            dive_b = self.rng.choice(("left", "centre", "right"))
            scored_a = self.resolve_kick(team_a, team_b, dir_a, dive_b, sudden_round)
            kicks.append(Kick(team_a, dir_a, dive_b, scored_a))

            dir_b = chooser_b(team_b, team_a, sudden_round)
            dive_a = self.rng.choice(("left", "centre", "right"))
            scored_b = self.resolve_kick(team_b, team_a, dir_b, dive_a, sudden_round)
            kicks.append(Kick(team_b, dir_b, dive_a, scored_b))

            score_a += int(scored_a)
            score_b += int(scored_b)
            if scored_a != scored_b:
                winner = team_a if score_a > score_b else team_b
                loser = team_b if winner == team_a else team_a
                return ShootoutResult(winner, loser, score_a, score_b, tuple(kicks))


def create_seeded_pairings(teams: Iterable[Team]) -> tuple[Match, ...]:
    ordered = sorted(teams, key=lambda t: t.seed)
    pairs = []
    for i in range(len(ordered) // 2):
        pairs.append(Match(ordered[i], ordered[-(i + 1)], ""))
    return tuple(pairs)


class GlobalKnockoutCup:
    def __init__(self, teams: Optional[Iterable[Team]] = None, rng: Optional[Random] = None):
        self.rng = rng or Random()
        self.teams = tuple(teams) if teams is not None else generate_teams(211)
        self.shootout_engine = PenaltyShootoutEngine(self.rng)

    def create_tournament_plan(self) -> TournamentPlan:
        regions = assign_regions_snake(self.teams)
        ordered = sorted(self.teams, key=lambda t: t.seed)
        byes = tuple(team for team in ordered if team.seed <= 45)
        preliminary_teams = tuple(team for team in ordered if team.seed > 45)
        preliminary = tuple(
            Match(m.team_a, m.team_b, "Preliminary Round") for m in create_seeded_pairings(preliminary_teams)
        )
        return TournamentPlan(regions=regions, preliminary_matches=preliminary, preliminary_byes=byes)

    def play_match(
        self,
        match: Match,
        chooser_for_team: Optional[dict[int, Callable[[Team, Team, int], Direction]]] = None,
    ) -> Team:
        chooser_for_team = chooser_for_team or {}
        result = self.shootout_engine.shootout(
            match.team_a,
            match.team_b,
            chooser_a=chooser_for_team.get(match.team_a.seed),
            chooser_b=chooser_for_team.get(match.team_b.seed),
        )
        return result.winner

    def _simulate_knockout_round(self, teams: Iterable[Team], round_name: str) -> tuple[tuple[Match, ...], tuple[Team, ...]]:
        pairings = [Match(p.team_a, p.team_b, round_name) for p in create_seeded_pairings(teams)]
        winners = tuple(self.play_match(match) for match in pairings)
        return tuple(pairings), winners

    def _draw_open_pairings(self, teams: Iterable[Team], round_name: str) -> tuple[Match, ...]:
        pool = list(teams)
        self.rng.shuffle(pool)
        return tuple(Match(pool[i], pool[i + 1], round_name) for i in range(0, len(pool), 2))

    def run_tournament(
        self,
        chooser_for_team: Optional[dict[int, Callable[[Team, Team, int], Direction]]] = None,
    ) -> TournamentOutcome:
        chooser_for_team = chooser_for_team or {}
        rounds: dict[str, tuple[Match, ...]] = {}

        plan = self.create_tournament_plan()
        rounds["Preliminary Round"] = plan.preliminary_matches
        preliminary_winners = tuple(self.play_match(match, chooser_for_team) for match in plan.preliminary_matches)

        phase1_128_teams = tuple(sorted((*plan.preliminary_byes, *preliminary_winners), key=lambda t: t.seed))
        round_128_matches, round_64_teams = self._simulate_knockout_round(phase1_128_teams, "Round of 128")
        rounds["Round of 128"] = round_128_matches

        round_64_matches, qualified_32 = self._simulate_knockout_round(round_64_teams, "Round of 64")
        rounds["Round of 64"] = round_64_matches

        current = qualified_32
        for round_name, winner_count in (
            ("Round of 32", 16),
            ("Round of 16", 8),
            ("Quarterfinal", 4),
            ("Semifinal", 2),
            ("Final", 1),
        ):
            matches = self._draw_open_pairings(current, round_name)
            rounds[round_name] = matches
            current = tuple(self.play_match(match, chooser_for_team) for match in matches)
            if len(current) != winner_count:
                raise ValueError(f"Unexpected winner count in {round_name}: {len(current)}")

        return TournamentOutcome(champion=current[0], phase1_qualified_32=qualified_32, rounds=rounds)
