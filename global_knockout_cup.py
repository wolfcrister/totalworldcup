from __future__ import annotations

import csv
from dataclasses import dataclass, field, replace
from pathlib import Path
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
class NationEntry:
    id: int
    name: str
    fifa_code: str
    confederation: str
    is_playable: bool
    strength_tier: int


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
class KickEvent:
    team: Team
    phase: Literal["resolve"]
    shot_direction: Direction
    dive_direction: Direction
    timing_quality: Optional[float]
    scored: bool
    score_a: int
    score_b: int
    message: str


@dataclass(frozen=True)
class ShootoutResult:
    winner: Team
    loser: Team
    score_a: int
    score_b: int
    kicks: tuple[Kick, ...]
    events: tuple[KickEvent, ...] = ()


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


@dataclass(frozen=True)
class ProjectStatus:
    done: tuple[str, ...]
    next_steps: tuple[str, ...]
    playable: bool
    playability_note: str


def get_project_status() -> ProjectStatus:
    return ProjectStatus(
        done=(
            "211-team tournament generation with seeded strength profiles",
            "Phase 1 knockout flow through Round of 64",
            "Open redraw at 32 teams, then fixed rounds to champion",
            "Penalty shootouts with early-finish and sudden-death logic",
        ),
        next_steps=(
            "Add a simple CLI loop for match-by-match user interaction",
            "Expose richer match logs for presentation layers",
            "Add save/resume support for long tournament runs",
        ),
        playable=True,
        playability_note="Playable now as an auto-simulated tournament run.",
    )


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def load_nation_dataset(
    file_path: Optional[str] = None,
    expected_playable_count: int = 211,
) -> tuple[NationEntry, ...]:
    dataset_path = Path(file_path) if file_path is not None else Path(__file__).resolve().parent / "data" / "nations.csv"
    if not dataset_path.exists():
        return tuple()

    required_columns = {
        "id",
        "name",
        "fifa_code",
        "confederation",
        "is_playable",
        "strength_tier",
    }
    allowed_confederations = {"AFC", "CAF", "CONCACAF", "CONMEBOL", "OFC", "UEFA"}

    with dataset_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError(f"Nation dataset has no header: {dataset_path}")
        missing_columns = required_columns.difference(set(reader.fieldnames))
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Nation dataset missing required columns ({missing}): {dataset_path}")

        entries: list[NationEntry] = []
        for row in reader:
            confederation = row["confederation"].strip()
            if confederation not in allowed_confederations:
                raise ValueError(f"Invalid confederation '{confederation}' for nation '{row['name']}'")

            is_playable_raw = row["is_playable"].strip().lower()
            if is_playable_raw not in {"true", "false"}:
                raise ValueError(f"Invalid is_playable value '{row['is_playable']}' for nation '{row['name']}'")

            entries.append(
                NationEntry(
                    id=int(row["id"]),
                    name=row["name"].strip(),
                    fifa_code=row["fifa_code"].strip().upper(),
                    confederation=confederation,
                    is_playable=is_playable_raw == "true",
                    strength_tier=int(row["strength_tier"]),
                )
            )

    playable_entries = [entry for entry in entries if entry.is_playable]
    if len(playable_entries) != expected_playable_count:
        raise ValueError(
            f"Expected {expected_playable_count} playable nations, found {len(playable_entries)} in {dataset_path}"
        )

    names = [entry.name for entry in playable_entries]
    fifa_codes = [entry.fifa_code for entry in playable_entries]
    if len(names) != len(set(names)):
        raise ValueError("Nation dataset contains duplicate nation names")
    if len(fifa_codes) != len(set(fifa_codes)):
        raise ValueError("Nation dataset contains duplicate FIFA codes")

    return tuple(sorted(playable_entries, key=lambda entry: entry.id))


def generate_teams(count: int = 211, nation_dataset_path: Optional[str] = None) -> tuple[Team, ...]:
    nation_entries = load_nation_dataset(nation_dataset_path)
    use_nation_names = len(nation_entries) >= count

    teams = []
    for seed in range(1, count + 1):
        strength = clamp(1.0 - ((seed - 1) / max(1, count - 1)), 0.0, 1.0)
        team_name = nation_entries[seed - 1].name if use_nation_names else f"Nation {seed}"
        teams.append(
            Team(
                name=team_name,
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
        timing_quality: Optional[float] = None,
    ) -> bool:
        chance = 0.75
        chance += shooter.penalty_strength * 0.15
        chance -= goalkeeper.goalkeeper_rating * 0.15
        chance += 0.10 if shot_direction != keeper_dive else -0.30
        if shot_direction == "centre" and keeper_dive == "centre":
            chance -= 0.10
        pressure_penalty = min(0.10, max(0.0, (kick_number_for_shooter - 1) * 0.015))
        chance -= pressure_penalty
        if timing_quality is not None:
            timing_quality = clamp(timing_quality, 0.0, 1.0)
            chance += (timing_quality - 0.5) * 0.20
        chance = clamp(chance, 0.20, 0.95)
        return self.rng.random() < chance

    def _build_kick_event(
        self,
        team: Team,
        direction: Direction,
        dive_direction: Direction,
        timing_quality: Optional[float],
        scored: bool,
        score_a: int,
        score_b: int,
    ) -> KickEvent:
        action = "scored" if scored else "missed"
        return KickEvent(
            team=team,
            phase="resolve",
            shot_direction=direction,
            dive_direction=dive_direction,
            timing_quality=timing_quality,
            scored=scored,
            score_a=score_a,
            score_b=score_b,
            message=f"{team.name} {action} ({score_a}-{score_b})",
        )

    def shootout(
        self,
        team_a: Team,
        team_b: Team,
        chooser_a: Optional[Callable[[Team, Team, int], Direction]] = None,
        chooser_b: Optional[Callable[[Team, Team, int], Direction]] = None,
        dive_chooser_a: Optional[Callable[[Team, Team, int], Direction]] = None,
        dive_chooser_b: Optional[Callable[[Team, Team, int], Direction]] = None,
        timing_chooser_a: Optional[Callable[[Team, Team, int], float]] = None,
        timing_chooser_b: Optional[Callable[[Team, Team, int], float]] = None,
    ) -> ShootoutResult:
        chooser_a = chooser_a or (lambda *_: self.rng.choice(("left", "centre", "right")))
        chooser_b = chooser_b or (lambda *_: self.rng.choice(("left", "centre", "right")))
        dive_chooser_a = dive_chooser_a or (lambda *_: self.rng.choice(("left", "centre", "right")))
        dive_chooser_b = dive_chooser_b or (lambda *_: self.rng.choice(("left", "centre", "right")))

        kicks: list[Kick] = []
        events: list[KickEvent] = []
        score_a = 0
        score_b = 0
        taken_a = 0
        taken_b = 0

        for _ in range(5):
            taken_a += 1
            dir_a = chooser_a(team_a, team_b, taken_a)
            dive_b = dive_chooser_b(team_b, team_a, taken_a)
            timing_a = timing_chooser_a(team_a, team_b, taken_a) if timing_chooser_a is not None else None
            scored_a = self.resolve_kick(team_a, team_b, dir_a, dive_b, taken_a, timing_a)
            score_a += int(scored_a)
            kicks.append(Kick(team_a, dir_a, dive_b, scored_a))
            events.append(self._build_kick_event(team_a, dir_a, dive_b, timing_a, scored_a, score_a, score_b))

            if score_a > score_b + (5 - taken_b):
                return ShootoutResult(team_a, team_b, score_a, score_b, tuple(kicks), tuple(events))

            taken_b += 1
            dir_b = chooser_b(team_b, team_a, taken_b)
            dive_a = dive_chooser_a(team_a, team_b, taken_b)
            timing_b = timing_chooser_b(team_b, team_a, taken_b) if timing_chooser_b is not None else None
            scored_b = self.resolve_kick(team_b, team_a, dir_b, dive_a, taken_b, timing_b)
            score_b += int(scored_b)
            kicks.append(Kick(team_b, dir_b, dive_a, scored_b))
            events.append(self._build_kick_event(team_b, dir_b, dive_a, timing_b, scored_b, score_a, score_b))

            if score_b > score_a + (5 - taken_a):
                return ShootoutResult(team_b, team_a, score_a, score_b, tuple(kicks), tuple(events))
            if score_a > score_b + (5 - taken_b):
                return ShootoutResult(team_a, team_b, score_a, score_b, tuple(kicks), tuple(events))

        sudden_round = 5
        while True:
            sudden_round += 1
            dir_a = chooser_a(team_a, team_b, sudden_round)
            dive_b = dive_chooser_b(team_b, team_a, sudden_round)
            timing_a = timing_chooser_a(team_a, team_b, sudden_round) if timing_chooser_a is not None else None
            scored_a = self.resolve_kick(team_a, team_b, dir_a, dive_b, sudden_round, timing_a)
            kicks.append(Kick(team_a, dir_a, dive_b, scored_a))

            dir_b = chooser_b(team_b, team_a, sudden_round)
            dive_a = dive_chooser_a(team_a, team_b, sudden_round)
            timing_b = timing_chooser_b(team_b, team_a, sudden_round) if timing_chooser_b is not None else None
            scored_b = self.resolve_kick(team_b, team_a, dir_b, dive_a, sudden_round, timing_b)
            kicks.append(Kick(team_b, dir_b, dive_a, scored_b))

            score_a += int(scored_a)
            score_b += int(scored_b)
            events.append(self._build_kick_event(team_a, dir_a, dive_b, timing_a, scored_a, score_a, score_b))
            events.append(self._build_kick_event(team_b, dir_b, dive_a, timing_b, scored_b, score_a, score_b))
            if scored_a != scored_b:
                winner = team_a if score_a > score_b else team_b
                loser = team_b if winner == team_a else team_a
                return ShootoutResult(winner, loser, score_a, score_b, tuple(kicks), tuple(events))


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
