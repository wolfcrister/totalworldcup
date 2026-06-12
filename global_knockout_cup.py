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
    fifa_rank: int = 0
    overall_rating: int = 70
    shooting_rating: int = 70
    reaction_rating: int = 70
    penalty_strength: float = 0.5
    goalkeeper_rating: float = 0.5


@dataclass(frozen=True)
class NationEntry:
    id: int
    name: str
    fifa_code: str
    confederation: str
    is_playable: bool
    fifa_rank: int
    strength_tier: int
    overall_rating: int
    shooting_rating: int
    reaction_rating: int


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
    regional_preliminary: dict[str, tuple[Match, ...]]
    regional_byes: dict[str, tuple[Team, ...]]


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


def _derive_team_ratings(fifa_rank: int, field_size: int) -> tuple[int, int, int, float, float]:
    base_strength = clamp(1.0 - ((fifa_rank - 1) / max(1, field_size - 1)), 0.0, 1.0)
    overall_rating = round(58 + base_strength * 34)
    shooting_rating = round(56 + base_strength * 36)
    reaction_rating = round(55 + base_strength * 35)
    penalty_strength = clamp(0.30 + base_strength * 0.60, 0.0, 1.0)
    goalkeeper_rating = clamp(0.28 + base_strength * 0.57, 0.0, 1.0)
    return overall_rating, shooting_rating, reaction_rating, penalty_strength, goalkeeper_rating


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
                    fifa_rank=int(row.get("fifa_rank", row["id"])),
                    strength_tier=int(row["strength_tier"]),
                    overall_rating=int(row.get("overall_rating") or 0),
                    shooting_rating=int(row.get("shooting_rating") or 0),
                    reaction_rating=int(row.get("reaction_rating") or 0),
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

    return tuple(sorted(playable_entries, key=lambda entry: (entry.fifa_rank, entry.id)))


def generate_teams(count: int = 211, nation_dataset_path: Optional[str] = None) -> tuple[Team, ...]:
    nation_entries = load_nation_dataset(nation_dataset_path)
    use_nation_names = len(nation_entries) >= count

    teams = []
    for seed in range(1, count + 1):
        nation_entry = nation_entries[seed - 1] if use_nation_names else None
        fifa_rank = nation_entry.fifa_rank if nation_entry is not None else seed
        overall_rating, shooting_rating, reaction_rating, penalty_strength, goalkeeper_rating = _derive_team_ratings(
            fifa_rank,
            count,
        )
        if nation_entry is not None and nation_entry.overall_rating > 0:
            overall_rating = nation_entry.overall_rating
        if nation_entry is not None and nation_entry.shooting_rating > 0:
            shooting_rating = nation_entry.shooting_rating
            penalty_strength = clamp(nation_entry.shooting_rating / 100.0, 0.0, 1.0)
        if nation_entry is not None and nation_entry.reaction_rating > 0:
            reaction_rating = nation_entry.reaction_rating
            goalkeeper_rating = clamp(nation_entry.reaction_rating / 100.0, 0.0, 1.0)
        team_name = nation_entry.name if nation_entry is not None else f"Nation {seed}"
        teams.append(
            Team(
                name=team_name,
                seed=seed,
                fifa_rank=fifa_rank,
                overall_rating=overall_rating,
                shooting_rating=shooting_rating,
                reaction_rating=reaction_rating,
                penalty_strength=penalty_strength,
                goalkeeper_rating=goalkeeper_rating,
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
        regional_preliminary: dict[str, tuple[Match, ...]] = {}
        regional_byes: dict[str, tuple[Team, ...]] = {}
        for region_name, region_teams in regions.items():
            ordered = sorted(region_teams, key=lambda t: t.seed)
            # Each region targets 32 teams entering R128. bye_count = 64 - region_size
            # ensures preliminary winners + byes = 32 exactly.
            bye_count = 64 - len(ordered)
            regional_byes[region_name] = tuple(ordered[:bye_count])
            prelim_teams = tuple(ordered[bye_count:])
            regional_preliminary[region_name] = tuple(
                Match(p.team_a, p.team_b, "Preliminary Round")
                for p in create_seeded_pairings(prelim_teams)
            )
        return TournamentPlan(
            regions=regions,
            regional_preliminary=regional_preliminary,
            regional_byes=regional_byes,
        )

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

        # Phase 1: Regional Preliminary — all regions played together, grouped by region.
        all_prelim_matches = tuple(m for matches in plan.regional_preliminary.values() for m in matches)
        rounds["Preliminary Round"] = all_prelim_matches
        prelim_winners = tuple(self.play_match(m, chooser_for_team) for m in all_prelim_matches)

        # Regional Round of 128 — each region's prelim winners + byes → 32 per region.
        all_r128_matches: list[Match] = []
        for region_name, region_byes in plan.regional_byes.items():
            region_prelim_winners = tuple(w for w in prelim_winners if w.region == region_name)
            r128_teams = tuple(sorted((*region_byes, *region_prelim_winners), key=lambda t: t.seed))
            all_r128_matches.extend(Match(p.team_a, p.team_b, "Round of 128") for p in create_seeded_pairings(r128_teams))
        rounds["Round of 128"] = tuple(all_r128_matches)
        r128_winners = tuple(self.play_match(m, chooser_for_team) for m in all_r128_matches)

        # Regional Round of 64 — 16 per region → 8 qualifiers per region = 32 total.
        all_r64_matches: list[Match] = []
        for region_name in plan.regions:
            region_r128_winners = tuple(w for w in r128_winners if w.region == region_name)
            all_r64_matches.extend(Match(p.team_a, p.team_b, "Round of 64") for p in create_seeded_pairings(region_r128_winners))
        rounds["Round of 64"] = tuple(all_r64_matches)
        qualified_32 = tuple(self.play_match(m, chooser_for_team) for m in all_r64_matches)

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
