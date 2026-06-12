from __future__ import annotations

import argparse
import json
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from random import Random

import pygame

from global_knockout_cup import Direction, GlobalKnockoutCup, Match, PenaltyShootoutEngine, Team, clamp, create_seeded_pairings

WIDTH = 1280
HEIGHT = 800
FPS = 60

BG = (14, 56, 34)
PITCH_STRIPE = (17, 64, 40)
PITCH_LINE = (165, 200, 165)
GOAL_COLOR = (228, 232, 228)
NET_LINE = (148, 152, 162)
BALL_COLOR = (252, 252, 252)
BALL_SHADOW = (20, 20, 20)
KEEPER_COLOR = (255, 196, 28)
TEXT_COLOR = (238, 244, 240)
ACCENT = (65, 210, 255)
GOOD = (48, 204, 80)
BAD = (230, 70, 70)
GOLD = (255, 192, 38)

DIRECTION_ORDER: tuple[Direction, ...] = ("left", "centre", "right")
LANE_LABELS: tuple[str, ...] = ("F-L", "LEFT", "CENTRE", "RIGHT", "F-R")


def _draw_panel(
    surface: pygame.Surface,
    rect: tuple[int, int, int, int],
    color: tuple[int, int, int, int],
    radius: int = 8,
) -> None:
    """Blit a filled rounded rectangle with alpha onto *surface*."""
    s = pygame.Surface((rect[2], rect[3]), pygame.SRCALPHA)
    pygame.draw.rect(s, color, (0, 0, rect[2], rect[3]), border_radius=radius)
    surface.blit(s, (rect[0], rect[1]))


@dataclass
class ShotAnimation:
    shooter: Team
    goalkeeper: Team
    shot_direction: Direction
    keeper_dive: Direction
    shot_lane: int
    keeper_lane: int
    actual_lane: int
    timing_quality: float
    reaction_quality: float
    scored: bool
    off_target: bool
    kick_index: int
    is_player_shot: bool


@dataclass(frozen=True)
class TournamentMatchResult:
    round_name: str
    match_number: int
    total_matches: int
    team_a: Team
    team_b: Team
    winner: Team
    score_a: int
    score_b: int
    was_featured_match: bool


def _team_rank_label(team: Team) -> str:
    return f"#{team.fifa_rank if team.fifa_rank > 0 else team.seed}"


def _team_compact_label(team: Team, max_len: int = 14) -> str:
    prefix = f"{_team_rank_label(team)} "
    available = max(4, max_len - len(prefix))
    name = team.name if len(team.name) <= available else team.name[: available - 1] + "."
    return prefix + name


def _team_rating_line(team: Team) -> str:
    return (
        f"{_team_rank_label(team)} {team.name}  "
        f"OVR {team.overall_rating}  SHO {team.shooting_rating}  GK {team.reaction_rating}"
    )


class VisualPenaltyGame:
    def __init__(self, player_team: Team, ai_team: Team, rng: Random, title: str = "Visual Penalty Shootout"):
        self.player_team = player_team
        self.ai_team = ai_team
        self.rng = rng
        self.engine = PenaltyShootoutEngine(rng)
        self.title = title
        self._engine_player_team = self._balanced_team(self.player_team)
        self._engine_ai_team = self._balanced_team(self.ai_team)

        self.score_player = 0
        self.score_ai = 0
        self.taken_player = 0
        self.taken_ai = 0
        self.player_kick_outcomes: list[bool] = []
        self.ai_kick_outcomes: list[bool] = []
        self.finished = False
        self.winner: Team | None = None

        self.current_phase = "player_direction"
        self.player_is_shooting = True
        self.selection_index = 2
        self.timing_value = 0.0
        self.timing_direction = 1.0
        self.selected_timing = 0.5
        self._pending_lane = 2
        self.phase_clock = 0.0
        self.scene_complete = False

        self.player_dive_choice = 2
        self.current_animation: ShotAnimation | None = None
        self.last_message = "Pick your shot lane, then lock shot precision"
        self.ticker_events: list[str] = []
        self._last_resolution_debug: dict[str, object] = {}
        self._match_result_logged = False
        self._match_log_path = self._create_match_log_file()

    def _balanced_team(self, team: Team) -> Team:
        # Compress extremes so visual matches remain dramatic even with large seed gaps.
        blend = 0.55
        return Team(
            name=team.name,
            seed=team.seed,
            region=team.region,
            fifa_rank=team.fifa_rank,
            overall_rating=team.overall_rating,
            shooting_rating=team.shooting_rating,
            reaction_rating=team.reaction_rating,
            penalty_strength=clamp(0.5 + (team.penalty_strength - 0.5) * blend, 0.0, 1.0),
            goalkeeper_rating=clamp(0.5 + (team.goalkeeper_rating - 0.5) * blend, 0.0, 1.0),
        )

    def _lane_to_direction(self, lane: int) -> Direction:
        if lane <= 1:
            return "left"
        if lane >= 3:
            return "right"
        return "centre"

    def _lane_x(self, lane: int, center: int, spread: int) -> int:
        offsets = (-2, -1, 0, 1, 2)
        clamped_lane = max(0, min(4, lane))
        return center + offsets[clamped_lane] * spread

    def _lane_label(self, lane: int) -> str:
        return LANE_LABELS[max(0, min(4, lane))]

    def _push_ticker_event(self, text: str) -> None:
        self.ticker_events.insert(0, text)
        if len(self.ticker_events) > 16:
            self.ticker_events = self.ticker_events[:16]

    def _slug(self, text: str) -> str:
        slug = "".join(ch if ch.isalnum() else "_" for ch in text)
        return slug.strip("_")[:24] or "team"

    def _create_match_log_file(self) -> Path | None:
        try:
            logs_dir = Path(__file__).resolve().parent / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"match_{self._slug(self.player_team.name)}_vs_{self._slug(self.ai_team.name)}_{stamp}.jsonl"
            path = logs_dir / filename
            self._write_log_record(
                path,
                {
                    "event": "match_start",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "title": self.title,
                    "player_team": self.player_team.name,
                    "ai_team": self.ai_team.name,
                    "player_shooting": self.player_team.shooting_rating,
                    "player_reaction": self.player_team.reaction_rating,
                    "ai_shooting": self.ai_team.shooting_rating,
                    "ai_reaction": self.ai_team.reaction_rating,
                },
            )
            return path
        except OSError:
            return None

    def _write_log_record(self, path: Path | None, record: dict[str, object]) -> None:
        if path is None:
            return
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        except OSError:
            return

    def _log_kick_event(
        self,
        side: str,
        shooter_name: str,
        keeper_name: str,
        intended_lane: int,
        keeper_lane: int,
        timing_quality: float,
        reaction_quality: float,
        scored: bool,
        actual_lane: int,
        off_target: bool,
        shot_tier: str,
        keeper_tier: str,
        result_message: str,
    ) -> None:
        debug = dict(self._last_resolution_debug)
        self._write_log_record(
            self._match_log_path,
            {
                "event": "kick",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "side": side,
                "kick_number": self.taken_player if side == "player" else self.taken_ai,
                "score_player": self.score_player,
                "score_ai": self.score_ai,
                "shooter": shooter_name,
                "keeper": keeper_name,
                "intended_lane": intended_lane,
                "intended_lane_label": self._lane_label(intended_lane),
                "keeper_lane": keeper_lane,
                "keeper_lane_label": self._lane_label(keeper_lane),
                "actual_lane": actual_lane,
                "actual_lane_label": self._lane_label(actual_lane),
                "timing_quality": round(timing_quality, 4),
                "reaction_quality": round(reaction_quality, 4),
                "shot_tier": shot_tier,
                "keeper_tier": keeper_tier,
                "result": result_message,
                "scored": scored,
                "off_target": off_target,
                "calculation": debug,
            },
        )

    def _wrap_text(self, font: pygame.font.Font, text: str, max_width: int) -> list[str]:
        words = text.split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if font.size(trial)[0] <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _timing_error(self, timing_quality: float) -> float:
        return abs(clamp(timing_quality, 0.0, 1.0) - 0.5) * 2.0

    def _timing_center_quality(self, timing_quality: float) -> float:
        # Unified meter meaning: centre is best, edges are worst.
        return clamp(1.0 - self._timing_error(timing_quality), 0.0, 1.0)

    def _shot_drift(self, shooter: Team, timing_quality: float) -> int | None:
        error = self._timing_error(timing_quality)
        clean_threshold = clamp(0.22 + shooter.shooting_rating / 260.0, 0.32, 0.58)
        drift_threshold = clamp(clean_threshold + 0.20, 0.52, 0.82)
        if error <= clean_threshold:
            return 0
        if error <= drift_threshold:
            return 1
        if error <= 0.95:
            return 2
        return None

    def _reaction_strength(self, goalkeeper: Team, reaction_quality: float) -> float:
        quality = clamp(reaction_quality, 0.0, 1.0)
        base = 0.35 + goalkeeper.reaction_rating / 140.0
        return clamp(base + quality * 0.85, 0.0, 1.7)

    def _shot_tier(self, timing_quality: float, intended_lane: int, shooter: Team | None = None) -> str:
        shooter = shooter or self._engine_player_team
        error = self._timing_error(timing_quality)
        clean_threshold = clamp(0.22 + shooter.shooting_rating / 260.0, 0.32, 0.58)
        drift_threshold = clamp(clean_threshold + 0.20, 0.52, 0.82)
        if intended_lane == 2 and timing_quality == 0.5:
            return "Perfect"
        if error <= clean_threshold * 0.28:
            return "Excellent"
        if error <= clean_threshold:
            return "Great"
        if error <= drift_threshold:
            return "Good"
        if error <= 0.95:
            return "Ok"
        return "Bad"

    def _keeper_tier(self, reaction_quality: float, goalkeeper: Team | None = None) -> str:
        goalkeeper = goalkeeper or self._engine_player_team
        error = self._timing_error(reaction_quality)
        clean_threshold = clamp(0.22 + goalkeeper.reaction_rating / 260.0, 0.32, 0.58)
        drift_threshold = clamp(clean_threshold + 0.20, 0.52, 0.82)
        if reaction_quality == 0.5:
            return "Perfect"
        if error <= clean_threshold * 0.28:
            return "Excellent"
        if error <= clean_threshold:
            return "Great"
        if error <= drift_threshold:
            return "Good"
        if error <= 0.95:
            return "Ok"
        return "Bad"

    def _save_probability(self, shot_tier: str, keeper_tier: str, lane_gap: int) -> float:
        if shot_tier == "Perfect":
            return 0.0

        # Keeper cannot save shots that are three or more lanes away.
        if lane_gap >= 3:
            return 0.0

        # Base save chance by shot quality and keeper-lane match.
        # Same lane should punish poor shots heavily, while adjacent saves are
        # mostly for weaker shots.
        same_lane_base = {
            "Excellent": 0.24,
            "Great": 0.42,
            "Good": 0.60,
            "Ok": 0.78,
            "Bad": 0.88,
        }
        adjacent_base = {
            "Excellent": 0.06,
            "Great": 0.16,
            "Good": 0.30,
            "Ok": 0.44,
            "Bad": 0.55,
        }
        keeper_adjust = {
            "Perfect": 0.10,
            "Excellent": 0.05,
            "Great": 0.00,
            "Good": -0.03,
            "Ok": -0.07,
            "Bad": -0.12,
        }

        two_lane_base = {
            "Excellent": 0.01,
            "Great": 0.06,
            "Good": 0.12,
            "Ok": 0.20,
            "Bad": 0.28,
        }
        two_lane_keeper_adjust = {
            "Perfect": 0.08,
            "Excellent": 0.05,
            "Great": 0.02,
            "Good": 0.00,
            "Ok": -0.03,
            "Bad": -0.06,
        }

        if lane_gap == 2:
            return clamp(two_lane_base[shot_tier] + two_lane_keeper_adjust[keeper_tier], 0.0, 0.30)

        base = same_lane_base[shot_tier] if lane_gap == 0 else adjacent_base[shot_tier]
        return clamp(base + keeper_adjust[keeper_tier], 0.0, 0.98)

    def _timing_meter_speed(self) -> float:
        if self.current_phase == "player_timing":
            skill_rating = self._engine_player_team.shooting_rating
        else:
            skill_rating = self._engine_player_team.reaction_rating

        # Better teams get a slightly slower meter, giving them a cleaner chance
        # to line up a perfect shot or save.
        return clamp(1.38 - skill_rating / 300.0, 0.88, 1.26)

    def _resolve_lane_kick(
        self,
        shooter: Team,
        goalkeeper: Team,
        intended_lane: int,
        keeper_lane: int,
        timing_quality: float,
        reaction_quality: float,
    ) -> tuple[bool, int, bool]:
        shot_tier = self._shot_tier(timing_quality, intended_lane, shooter)
        keeper_tier = self._keeper_tier(reaction_quality, goalkeeper)
        drift = self._shot_drift(shooter, timing_quality)
        if drift is None:
            self._last_resolution_debug = {
                "shot_tier": shot_tier,
                "keeper_tier": keeper_tier,
                "drift": None,
                "timing_quality": round(timing_quality, 4),
                "reaction_quality": round(reaction_quality, 4),
                "reason": "drift_off_target",
            }
            return False, intended_lane, True

        # A perfect shot is always uncatchable, even if the keeper reads it.
        if shot_tier == "Perfect":
            actual_lane = intended_lane
            if actual_lane < 0 or actual_lane > 4:
                self._last_resolution_debug = {
                    "shot_tier": shot_tier,
                    "keeper_tier": keeper_tier,
                    "drift": drift,
                    "lane_gap": None,
                    "save_probability": 0.0,
                    "saved_roll": None,
                    "reason": "perfect_out_of_bounds",
                }
                return False, max(0, min(4, actual_lane)), True
            self._last_resolution_debug = {
                "shot_tier": shot_tier,
                "keeper_tier": keeper_tier,
                "drift": drift,
                "lane_gap": abs(actual_lane - keeper_lane),
                "save_probability": 0.0,
                "saved_roll": None,
                "reason": "perfect_uncatchable",
            }
            return True, actual_lane, False

        if drift == 0:
            actual_lane = intended_lane
        else:
            direction = -1 if timing_quality < 0.5 else 1
            actual_lane = intended_lane + direction * drift

        if actual_lane < 0 or actual_lane > 4:
            self._last_resolution_debug = {
                "shot_tier": shot_tier,
                "keeper_tier": keeper_tier,
                "drift": drift,
                "lane_gap": None,
                "save_probability": 0.0,
                "saved_roll": None,
                "reason": "drift_out_of_bounds",
            }
            return False, max(0, min(4, actual_lane)), True

        lane_gap = abs(actual_lane - keeper_lane)
        save_probability = self._save_probability(shot_tier, keeper_tier, lane_gap)
        saved_roll = self.rng.random()
        saved = saved_roll < save_probability
        self._last_resolution_debug = {
            "shot_tier": shot_tier,
            "keeper_tier": keeper_tier,
            "drift": drift,
            "lane_gap": lane_gap,
            "save_probability": round(save_probability, 4),
            "saved_roll": round(saved_roll, 4),
            "saved": saved,
            "reason": "resolved",
        }
        return (not saved), actual_lane, False

    def _sample_ai_shot_lane(self, team: Team) -> int:
        weights = [0.18, 0.21, 0.22, 0.21, 0.18]
        if team.shooting_rating >= 80:
            weights = [0.22, 0.21, 0.14, 0.21, 0.22]
        return self.rng.choices(range(5), weights=weights, k=1)[0]

    def _sample_ai_dive_lane(self, team: Team) -> int:
        weights = [0.20, 0.20, 0.20, 0.20, 0.20]
        if team.reaction_rating >= 80:
            weights = [0.22, 0.18, 0.20, 0.18, 0.22]
        return self.rng.choices(range(5), weights=weights, k=1)[0]

    def _sample_ai_timing(self, skill_rating: int) -> float:
        base = 0.5
        consistency = (skill_rating - 50) / 100.0 * 0.08
        jitter = self.rng.uniform(-0.20, 0.20)
        return clamp(base + consistency + jitter, 0.0, 1.0)

    def _check_finish(self) -> None:
        in_regulation = self.taken_player < 5 or self.taken_ai < 5

        # Early finish applies only during the first 5 kicks per side.
        if in_regulation:
            if self.score_player > self.score_ai + (5 - self.taken_ai):
                self.finished = True
                self.winner = self.player_team
                return
            if self.score_ai > self.score_player + (5 - self.taken_player):
                self.finished = True
                self.winner = self.ai_team
                return

        # In sudden death, both teams must take the same number of kicks
        # before a one-goal lead can decide the winner.
        if self.taken_player >= 5 and self.taken_ai >= 5 and self.taken_player == self.taken_ai and self.score_player != self.score_ai:
            self.finished = True
            self.winner = self.player_team if self.score_player > self.score_ai else self.ai_team

        if self.finished and not self._match_result_logged:
            self._match_result_logged = True
            self._write_log_record(
                self._match_log_path,
                {
                    "event": "match_end",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "winner": self.winner.name if self.winner is not None else None,
                    "score_player": self.score_player,
                    "score_ai": self.score_ai,
                    "taken_player": self.taken_player,
                    "taken_ai": self.taken_ai,
                },
            )

    def _finalize_player_shot(self, shot_lane: int, timing_quality: float) -> None:
        self.taken_player += 1
        keeper_lane = self._sample_ai_dive_lane(self.ai_team)
        keeper_dive = self._lane_to_direction(keeper_lane)
        reaction_quality = self._sample_ai_timing(self.ai_team.reaction_rating)
        scored, actual_lane, off_target = self._resolve_lane_kick(
            shooter=self._engine_player_team,
            goalkeeper=self._engine_ai_team,
            intended_lane=shot_lane,
            keeper_lane=keeper_lane,
            timing_quality=timing_quality,
            reaction_quality=reaction_quality,
        )
        self.score_player += int(scored)
        self.player_kick_outcomes.append(scored)

        shot_tier = self._shot_tier(timing_quality, shot_lane, self._engine_player_team)
        keeper_tier = self._keeper_tier(reaction_quality, self._engine_ai_team)
        result_message = "PERFECT GOAL" if shot_tier == "Perfect" and scored else ("GOAL" if scored else ("WIDE" if off_target else "SAVED"))
        self._push_ticker_event(
            f"YOU shot {shot_tier} ({self._lane_label(shot_lane)}) | AI save {keeper_tier} ({self._lane_label(keeper_lane)}) | {result_message}"
        )
        self._log_kick_event(
            side="player",
            shooter_name=self.player_team.name,
            keeper_name=self.ai_team.name,
            intended_lane=shot_lane,
            keeper_lane=keeper_lane,
            timing_quality=timing_quality,
            reaction_quality=reaction_quality,
            scored=scored,
            actual_lane=actual_lane,
            off_target=off_target,
            shot_tier=shot_tier,
            keeper_tier=keeper_tier,
            result_message=result_message,
        )

        self.current_animation = ShotAnimation(
            shooter=self.player_team,
            goalkeeper=self.ai_team,
            shot_direction=self._lane_to_direction(shot_lane),
            keeper_dive=keeper_dive,
            shot_lane=shot_lane,
            keeper_lane=keeper_lane,
            actual_lane=actual_lane,
            timing_quality=timing_quality,
            reaction_quality=reaction_quality,
            scored=scored,
            off_target=off_target,
            kick_index=self.taken_player,
            is_player_shot=True,
        )
        self.phase_clock = 0.0
        self.current_phase = "animate_shot"
        self.last_message = result_message

    def _finalize_ai_shot(self, keeper_lane: int, reaction_quality: float) -> None:
        self.taken_ai += 1
        ai_lane = self._sample_ai_shot_lane(self._engine_ai_team)
        ai_timing = self._sample_ai_timing(self._engine_ai_team.shooting_rating)
        scored, actual_lane, off_target = self._resolve_lane_kick(
            shooter=self._engine_ai_team,
            goalkeeper=self._engine_player_team,
            intended_lane=ai_lane,
            keeper_lane=keeper_lane,
            timing_quality=ai_timing,
            reaction_quality=reaction_quality,
        )
        self.score_ai += int(scored)
        self.ai_kick_outcomes.append(scored)

        shot_tier = self._shot_tier(ai_timing, ai_lane, self._engine_ai_team)
        keeper_tier = self._keeper_tier(reaction_quality, self._engine_player_team)
        result_message = "AI PERFECT GOAL" if shot_tier == "Perfect" and scored else ("AI SCORED" if scored else ("AI MISSED" if off_target else "YOU SAVED"))
        self._push_ticker_event(
            f"AI shot {shot_tier} ({self._lane_label(ai_lane)}) | YOU save {keeper_tier} ({self._lane_label(keeper_lane)}) | {result_message}"
        )
        self._log_kick_event(
            side="ai",
            shooter_name=self.ai_team.name,
            keeper_name=self.player_team.name,
            intended_lane=ai_lane,
            keeper_lane=keeper_lane,
            timing_quality=ai_timing,
            reaction_quality=reaction_quality,
            scored=scored,
            actual_lane=actual_lane,
            off_target=off_target,
            shot_tier=shot_tier,
            keeper_tier=keeper_tier,
            result_message=result_message,
        )

        self.current_animation = ShotAnimation(
            shooter=self.ai_team,
            goalkeeper=self.player_team,
            shot_direction=self._lane_to_direction(ai_lane),
            keeper_dive=self._lane_to_direction(keeper_lane),
            shot_lane=ai_lane,
            keeper_lane=keeper_lane,
            actual_lane=actual_lane,
            timing_quality=ai_timing,
            reaction_quality=reaction_quality,
            scored=scored,
            off_target=off_target,
            kick_index=self.taken_ai,
            is_player_shot=False,
        )
        self.phase_clock = 0.0
        self.current_phase = "animate_shot"
        self.last_message = result_message

    def _next_phase_after_animation(self) -> None:
        self._check_finish()
        if self.finished:
            self.current_phase = "finished"
            self.last_message = "You win the shootout" if self.winner == self.player_team else "AI wins the shootout"
            return

        self.player_is_shooting = not self.player_is_shooting
        self.selection_index = 2
        if self.player_is_shooting:
            self.current_phase = "player_direction"
            self.last_message = "Your shot. Pick a lane, then lock shot precision"
        else:
            self.current_phase = "ai_dive"
            self.last_message = "AI is shooting. Pick a dive lane, then lock reaction timing"

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        if self.current_phase == "finished":
            if event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                self.scene_complete = True
            return

        if self.current_phase in ("player_direction", "ai_dive"):
            if event.key == pygame.K_LEFT:
                self.selection_index = max(0, self.selection_index - 1)
            elif event.key == pygame.K_RIGHT:
                self.selection_index = min(4, self.selection_index + 1)
            elif event.key == pygame.K_RETURN:
                if self.current_phase == "player_direction":
                    self.current_phase = "player_timing"
                    self.timing_value = 0.0
                    self.timing_direction = 1.0
                    self.last_message = "Press SPACE to lock shot precision"
                    self._pending_lane = self.selection_index
                else:
                    self.player_dive_choice = self.selection_index
                    self.current_phase = "keeper_timing"
                    self.timing_value = 0.0
                    self.timing_direction = 1.0
                    self.last_message = "Press SPACE to lock keeper reaction"

        elif self.current_phase == "player_timing" and event.key == pygame.K_SPACE:
            self.selected_timing = round(self.timing_value, 2)
            self._finalize_player_shot(self._pending_lane, self.selected_timing)
        elif self.current_phase == "keeper_timing" and event.key == pygame.K_SPACE:
            self.selected_timing = round(self.timing_value, 2)
            self._finalize_ai_shot(self.player_dive_choice, self.selected_timing)

    def update(self, dt: float) -> None:
        if self.current_phase in ("player_timing", "keeper_timing"):
            # Sawtooth motion: when the cursor reaches the right edge it wraps to left.
            self.timing_value = (self.timing_value + dt * self._timing_meter_speed()) % 1.0

        if self.current_phase == "animate_shot":
            self.phase_clock += dt
            if self.phase_clock >= 1.0:
                self._next_phase_after_animation()

    def _draw_pitch(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        screen.fill(BG)
        # Subtle alternating grass stripes
        for sx in range(0, width, 80):
            pygame.draw.rect(screen, PITCH_STRIPE, (sx, 0, 40, height))
        # Outer pitch boundary
        pygame.draw.rect(screen, PITCH_LINE, (80, 100, width - 160, height - 180), width=2)
        # Goal posts & crossbar
        goal_x = width // 2 - 150
        goal_w = 300
        pygame.draw.rect(screen, GOAL_COLOR, (goal_x, 90, goal_w, 28), width=3)
        # Goal net — horizontal then vertical lines
        for ny in range(94, 118, 8):
            pygame.draw.line(screen, NET_LINE, (goal_x + 2, ny), (goal_x + goal_w - 2, ny), 1)
        for nx in range(goal_x + 18, goal_x + goal_w, 18):
            pygame.draw.line(screen, NET_LINE, (nx, 91), (nx, 117), 1)
        # Penalty area
        pygame.draw.rect(screen, PITCH_LINE, (width // 2 - 220, 118, 440, 90), width=1)
        # Penalty spot
        pygame.draw.circle(screen, PITCH_LINE, (width // 2, 196), 4)

    def _direction_x(self, direction: Direction, center: int, spread: int) -> int:
        if direction == "left":
            return center - spread
        if direction == "right":
            return center + spread
        return center

    def _draw_shot_animation(self, screen: pygame.Surface) -> None:
        if self.current_animation is None:
            return

        shot = self.current_animation
        progress = min(1.0, self.phase_clock / 0.7)

        width, height = screen.get_size()
        goal_center_x = width // 2
        goal_y = 104
        start_x = width // 2
        start_y = height - 110

        target_x = self._lane_x(shot.actual_lane, goal_center_x, 58)

        keeper_target_x = self._lane_x(shot.keeper_lane, goal_center_x, 58)
        # Ease the keeper from center to dive side so movement reads as a slide.
        dive_progress = max(0.0, min(1.0, (progress - 0.08) / 0.72))
        eased_dive_progress = 1.0 - (1.0 - dive_progress) ** 3
        keeper_x = int(goal_center_x + (keeper_target_x - goal_center_x) * eased_dive_progress)
        keeper_y = 120

        if shot.scored:
            ball_x = int(start_x + (target_x - start_x) * progress)
            ball_y = int(start_y + (goal_y - start_y) * progress)
        else:
            # Ball travels all the way to the keeper's position at contact_t,
            # then either sticks or deflects. Contact happens near the goal line.
            contact_t = 0.92
            contact_dive_p = max(0.0, min(1.0, (contact_t - 0.08) / 0.72))
            contact_eased = 1.0 - (1.0 - contact_dive_p) ** 3
            contact_keeper_x = int(goal_center_x + (keeper_target_x - goal_center_x) * contact_eased)
            # Ball intercept: keeper's horizontal position, goal-line height.
            intercept_x = contact_keeper_x
            intercept_y = keeper_y + 10  # just in front of keeper body

            if progress <= contact_t:
                local = progress / contact_t
                ball_x = int(start_x + (intercept_x - start_x) * local)
                ball_y = int(start_y + (intercept_y - start_y) * local)
            else:
                post_save = (progress - contact_t) / max(0.001, 1.0 - contact_t)
                save_mode = "bounce" if shot.kick_index % 2 == 0 else "hold"
                if save_mode == "hold":
                    ball_x = intercept_x
                    ball_y = intercept_y
                else:
                    # Deflect away from the keeper's dive direction.
                    bounce_dir = 1 if shot.keeper_lane <= 1 else (-1 if shot.keeper_lane >= 3 else 1)
                    bounce_target_x = intercept_x + 70 * bounce_dir
                    bounce_target_y = intercept_y + 50
                    ball_x = int(intercept_x + (bounce_target_x - intercept_x) * post_save)
                    ball_y = int(intercept_y + (bounce_target_y - intercept_y) * post_save)

        pygame.draw.circle(screen, BALL_SHADOW, (ball_x + 3, ball_y + 3), 10)
        pygame.draw.circle(screen, BALL_COLOR, (ball_x, ball_y), 10)
        pygame.draw.circle(screen, (210, 210, 210), (ball_x - 3, ball_y - 3), 4)  # specular highlight

        for lane in range(5):
            lane_x = self._lane_x(lane, goal_center_x, 58)
            pygame.draw.line(screen, PITCH_LINE, (lane_x, 92), (lane_x, 215), 1)

        # Keeper body + gloves
        pygame.draw.rect(screen, KEEPER_COLOR, (keeper_x - 18, keeper_y, 36, 26), border_radius=5)
        pygame.draw.rect(screen, (200, 148, 18), (keeper_x - 18, keeper_y, 36, 26), width=2, border_radius=5)
        pygame.draw.circle(screen, (255, 218, 80), (keeper_x - 19, keeper_y + 13), 6)
        pygame.draw.circle(screen, (255, 218, 80), (keeper_x + 19, keeper_y + 13), 6)

    def _draw_selection(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        if self.current_phase not in ("player_direction", "ai_dive"):
            return

        width, height = screen.get_size()
        labels = list(LANE_LABELS)
        btn_w, btn_h = 108, 42
        gap = 8
        total_w = len(labels) * btn_w + (len(labels) - 1) * gap
        base_x = width // 2 - total_w // 2
        y = height - 66
        for idx, label in enumerate(labels):
            bx = base_x + idx * (btn_w + gap)
            is_selected = idx == self.selection_index
            if is_selected:
                _draw_panel(screen, (bx, y, btn_w, btn_h), (ACCENT[0], ACCENT[1], ACCENT[2], 220), radius=8)
                txt_color = (8, 14, 24)
            else:
                _draw_panel(screen, (bx, y, btn_w, btn_h), (20, 40, 30, 180), radius=8)
                pygame.draw.rect(screen, PITCH_LINE, (bx, y, btn_w, btn_h), width=1, border_radius=8)
                txt_color = TEXT_COLOR
            text = font.render(label, True, txt_color)
            screen.blit(text, (bx + btn_w // 2 - text.get_width() // 2, y + btn_h // 2 - text.get_height() // 2))

    def _draw_timing_meter(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        if self.current_phase not in ("player_timing", "keeper_timing"):
            return

        width, height = screen.get_size()
        x = width // 2 - 250
        y = height - 86
        w = 500
        h = 30

        # Background card
        _draw_panel(screen, (x - 14, y - 38, w + 28, h + 52), (8, 16, 40, 215), radius=12)

        actor = self._engine_player_team
        skill_rating = actor.shooting_rating if self.current_phase == "player_timing" else actor.reaction_rating

        # Compute thresholds from active role ratings using one shared center-based visual.
        clean_threshold = clamp(0.22 + skill_rating / 260.0, 0.32, 0.58)
        drift_threshold = clamp(clean_threshold + 0.20, 0.52, 0.82)
        excellent_threshold = clean_threshold * 0.28

        # Meter track (dark base)
        pygame.draw.rect(screen, (30, 32, 36), (x, y, w, h), border_radius=7)

        def _draw_error_band(low_error: float, high_error: float, color: tuple[int, int, int]) -> None:
            low = clamp(low_error, 0.0, 1.0)
            high = clamp(high_error, 0.0, 1.0)
            if high <= low:
                return
            left_start = x + int(w * (0.5 - high / 2.0))
            left_end = x + int(w * (0.5 - low / 2.0))
            right_start = x + int(w * (0.5 + low / 2.0))
            right_end = x + int(w * (0.5 + high / 2.0))
            if left_end > left_start:
                pygame.draw.rect(screen, color, (left_start, y, left_end - left_start, h), border_radius=6)
            if right_end > right_start:
                pygame.draw.rect(screen, color, (right_start, y, right_end - right_start, h), border_radius=6)

        # Shared color zones: early/late away from center are weaker.
        _draw_error_band(0.0, excellent_threshold, (72, 214, 128))        # Excellent
        _draw_error_band(excellent_threshold, clean_threshold, GOOD)        # Great
        _draw_error_band(clean_threshold, drift_threshold, (188, 176, 58))  # Good
        _draw_error_band(drift_threshold, 0.95, (214, 138, 38))             # Ok
        _draw_error_band(0.95, 1.0, BAD)                                     # Bad

        # Center marker (best timing point).
        perfect_x = x + w // 2
        pygame.draw.line(screen, (90, 255, 236), (perfect_x, y - 2), (perfect_x, y + h + 2), 2)
        pygame.draw.line(screen, (255, 255, 255), (perfect_x, y - 4), (perfect_x, y + h + 4), 1)

        # Moving cursor bar
        cursor_x = x + int(self.timing_value * w)
        pygame.draw.rect(screen, BALL_COLOR, (cursor_x - 4, y - 8, 8, h + 16), border_radius=4)

        # Help text centred above meter
        is_shot = self.current_phase == "player_timing"
        help_label = "SPACE  —  Lock shot precision" if is_shot else "SPACE  —  Lock reaction timing"
        help_text = font.render(help_label, True, TEXT_COLOR)
        screen.blit(help_text, (x + w // 2 - help_text.get_width() // 2, y - 32))

        early_text = font.render("EARLY", True, TEXT_COLOR)
        good_text = font.render("GOOD", True, TEXT_COLOR)
        late_text = font.render("LATE", True, TEXT_COLOR)
        screen.blit(early_text, (x, y + h + 6))
        screen.blit(good_text, (x + w // 2 - good_text.get_width() // 2, y + h + 6))
        screen.blit(late_text, (x + w - late_text.get_width(), y + h + 6))

    def _draw_penalty_spots(self, screen: pygame.Surface, small_font: pygame.font.Font) -> None:
        width, _ = screen.get_size()
        center_x = width // 2
        top_y = 56
        dot_radius = 9
        dot_gap = 28

        # Translucent pill behind the two rows of dots
        pill_w = dot_gap * 5 + dot_radius * 4 + 80
        _draw_panel(screen, (center_x - pill_w // 2, top_y - 20, pill_w, 68), (8, 16, 40, 180), radius=10)

        def draw_row(label: str, outcomes: list[bool], y: int) -> None:
            label_text = small_font.render(label, True, TEXT_COLOR)
            screen.blit(label_text, (center_x - pill_w // 2 + 8, y - 9))
            start_x = center_x - (dot_gap * 2)
            for idx in range(5):
                dx = start_x + idx * dot_gap
                color = (25, 28, 28)
                if idx < len(outcomes):
                    color = GOOD if outcomes[idx] else BAD
                pygame.draw.circle(screen, color, (dx, y), dot_radius)
                pygame.draw.circle(screen, PITCH_LINE, (dx, y), dot_radius, 1)

        draw_row("YOU", self.player_kick_outcomes, top_y)
        draw_row("AI", self.ai_kick_outcomes, top_y + 28)

        if self.taken_player > 5 or self.taken_ai > 5:
            sudden = small_font.render(
                f"Sudden death +{max(0, self.taken_player - 5)} / +{max(0, self.taken_ai - 5)}",
                True,
                GOLD,
            )
            screen.blit(sudden, (center_x - sudden.get_width() // 2, top_y + 52))

    def _draw_hud(self, screen: pygame.Surface, font: pygame.font.Font, small_font: pygame.font.Font) -> None:
        width, height = screen.get_size()
        left_x = 8
        left_w = 384
        panel_y = 8
        panel_h = height - 16
        right_w = 404
        right_x = width - right_w - 8

        # Left panel: how-to + matrix
        _draw_panel(screen, (left_x, panel_y, left_w, panel_h), (8, 16, 40, 215), radius=10)
        header_font = pygame.font.SysFont("consolas", 22, bold=True)
        body_font = pygame.font.SysFont("consolas", 17)
        screen.blit(header_font.render("How To Play", True, ACCENT), (left_x + 12, panel_y + 10))
        instructions = [
            ("1) Pick lane with arrows, ENTER to lock", TEXT_COLOR),
            ("2) Press SPACE on timing meter", TEXT_COLOR),
            ("3) Center at 0.50 = Perfect (always goal)", GOOD),
            ("4) 3+ lane gap = keeper cannot save", TEXT_COLOR),
            ("5) 2-lane gap has only a small save chance", TEXT_COLOR),
        ]
        info_y = panel_y + 42
        for text, color in instructions:
            for line in self._wrap_text(body_font, text, left_w - 24):
                screen.blit(body_font.render(line, True, color), (left_x + 12, info_y))
                info_y += 22

        mx = left_x + 12
        my = info_y + 14
        screen.blit(header_font.render("Shot vs Keeper Matrix", True, ACCENT), (mx, my))
        matrix_font = pygame.font.SysFont("consolas", 16, bold=True)
        headers = ["Shot", "Keeper", "Outcome"]
        cols = [mx, mx + 130, mx + 252]
        for idx, label in enumerate(headers):
            screen.blit(matrix_font.render(label, True, TEXT_COLOR), (cols[idx], my + 30))
        rows = [
            ("Perfect", "Any", "Shooter", GOOD),
            ("Excellent", "Great", "Shooter", (78, 220, 118)),
            ("Great", "Great", "Even", (170, 196, 96)),
            ("Good", "Great", "Keeper", (210, 130, 26)),
            ("Ok", "Great", "Keeper", (230, 108, 48)),
            ("Bad", "Any", "Keeper", BAD),
        ]
        for idx, (shot_label, keeper_label, edge_label, color) in enumerate(rows):
            y = my + 54 + idx * 20
            screen.blit(matrix_font.render(shot_label, True, color), (cols[0], y))
            screen.blit(matrix_font.render(keeper_label, True, color), (cols[1], y))
            screen.blit(matrix_font.render(edge_label, True, color), (cols[2], y))

        legend_y = my + 194
        screen.blit(body_font.render("Tier meaning:", True, ACCENT), (mx, legend_y))
        for idx, (text, color) in enumerate([
            ("Excellent/Great: in-lane precision", TEXT_COLOR),
            ("Good/Ok: drift risk, keeper pressure", TEXT_COLOR),
            ("Bad: likely wide or easy read", BAD),
        ]):
            for j, line in enumerate(self._wrap_text(body_font, text, left_w - 24)):
                screen.blit(body_font.render(line, True, color), (mx, legend_y + 22 + (idx * 22) + (j * 18)))

        # Right panel: score + ticker
        _draw_panel(screen, (right_x, panel_y, right_w, panel_h), (8, 16, 40, 215), radius=10)
        title_surf = small_font.render(f"{self.player_team.name}  vs  {self.ai_team.name}", True, TEXT_COLOR)
        score_surf = font.render(f"{self.score_player}  —  {self.score_ai}", True, TEXT_COLOR)
        player_meta = small_font.render(
            f"YOU  SHO {self.player_team.shooting_rating}  GK {self.player_team.reaction_rating}",
            True,
            ACCENT,
        )
        ai_meta = small_font.render(
            f"AI   SHO {self.ai_team.shooting_rating}  GK {self.ai_team.reaction_rating}",
            True,
            TEXT_COLOR,
        )
        screen.blit(title_surf, (right_x + 12, panel_y + 12))
        screen.blit(score_surf, (right_x + right_w - score_surf.get_width() - 14, panel_y + 12))
        screen.blit(player_meta, (right_x + 12, panel_y + 56))
        screen.blit(ai_meta, (right_x + 12, panel_y + 82))

        ticker_title_font = pygame.font.SysFont("consolas", 20, bold=True)
        ticker_line_font = pygame.font.SysFont("consolas", 16)
        ticker_top = panel_y + 124
        screen.blit(ticker_title_font.render("Match Ticker", True, ACCENT), (right_x + 12, ticker_top))
        _draw_panel(screen, (right_x + 12, ticker_top + 30, right_w - 24, panel_h - 176), (6, 10, 26, 210), radius=8)

        if not self.ticker_events:
            empty = ticker_line_font.render("No events yet - take the first shot.", True, TEXT_COLOR)
            screen.blit(empty, (right_x + 20, ticker_top + 48))
        else:
            y = ticker_top + 42
            max_lines = (panel_h - 196) // 18
            drawn = 0
            for idx, event in enumerate(self.ticker_events):
                if drawn >= max_lines:
                    break
                color = GOOD if "GOAL" in event else (BAD if "SAVED" in event or "MISSED" in event or "WIDE" in event else TEXT_COLOR)
                wrapped = self._wrap_text(ticker_line_font, event, right_w - 52)
                for line_idx, chunk in enumerate(wrapped):
                    if drawn >= max_lines:
                        break
                    prefix = f"{idx + 1:>2}. " if line_idx == 0 else "    "
                    line = ticker_line_font.render(prefix + chunk, True, color)
                    screen.blit(line, (right_x + 18, y))
                    y += 18
                    drawn += 1

        # Penalty spot indicators stay centered over the pitch.
        self._draw_penalty_spots(screen, small_font)

        # ── Status badge centred at bottom ───────────────────────────────
        msg_lower = self.last_message.lower()
        if "win" in msg_lower or "goal" in msg_lower or "you saved" in msg_lower:
            badge_color = GOOD
        elif self.current_phase in ("player_direction", "player_timing", "ai_dive", "keeper_timing"):
            badge_color = ACCENT
        else:
            badge_color = BAD
        status_surf = small_font.render(self.last_message, True, (8, 12, 22))
        badge_w = status_surf.get_width() + 32
        badge_x = width // 2 - badge_w // 2
        _draw_panel(screen, (badge_x, 12, badge_w, 40), (badge_color[0], badge_color[1], badge_color[2], 230), radius=20)
        screen.blit(status_surf, (badge_x + 16, 20))

        # ── Match-over overlay ───────────────────────────────────────────
        if self.current_phase == "finished":
            overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 145))
            screen.blit(overlay, (0, 0))
            message = "YOU WIN!" if self.winner == self.player_team else "AI WINS"
            msg_color = GOOD if self.winner == self.player_team else BAD
            msg_text = font.render(message, True, msg_color)
            hint_text = small_font.render("Press ENTER or ESC to continue", True, TEXT_COLOR)
            card_w = max(msg_text.get_width(), hint_text.get_width()) + 64
            card_h = 112
            card_x = width // 2 - card_w // 2
            card_y = height // 2 - 66
            _draw_panel(screen, (card_x, card_y, card_w, card_h), (8, 16, 40, 248), radius=14)
            pygame.draw.rect(screen, msg_color, (card_x, card_y, card_w, card_h), width=2, border_radius=14)
            screen.blit(msg_text, (width // 2 - msg_text.get_width() // 2, card_y + 18))
            screen.blit(hint_text, (width // 2 - hint_text.get_width() // 2, card_y + 66))

    def render(self, screen: pygame.Surface, font: pygame.font.Font, small_font: pygame.font.Font) -> None:
        self._draw_pitch(screen)
        self._draw_shot_animation(screen)
        self._draw_selection(screen, small_font)
        self._draw_timing_meter(screen, small_font)
        self._draw_hud(screen, font, small_font)


def run_visual_match(seed: int | None = None, featured_seed: int = 1) -> int:
    rng = Random(seed)
    teams = tuple(GlobalKnockoutCup(rng=rng).teams)

    featured = next((team for team in teams if team.seed == featured_seed), teams[0])
    opponent_candidates = [
        team for team in teams if team.seed != featured.seed and abs(team.seed - featured.seed) <= 40
    ]
    if not opponent_candidates:
        opponent_candidates = [team for team in teams if team.seed != featured.seed]
    opponent = rng.choice(opponent_candidates)

    pygame.init()
    pygame.display.set_caption("Total World Cup - Visual Penalty")
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    clock = pygame.time.Clock()

    font = pygame.font.SysFont("segoeui", 34, bold=True)
    small_font = pygame.font.SysFont("consolas", 22)

    game = VisualPenaltyGame(player_team=featured, ai_team=opponent, rng=rng, title="Single Match")

    while True:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return 0
            game.handle_event(event)

        if game.scene_complete:
            pygame.quit()
            return 0

        game.update(dt)
        game.render(screen, font, small_font)
        pygame.display.flip()


def _show_info_screen(
    screen: pygame.Surface,
    clock: pygame.time.Clock,
    title_font: pygame.font.Font,
    text_font: pygame.font.Font,
    lines: list[str],
) -> bool:
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return True

        width, height = screen.get_size()
        screen.fill(BG)
        # Subtle grass stripes on info screens too
        for sx in range(0, width, 80):
            pygame.draw.rect(screen, PITCH_STRIPE, (sx, 0, 40, height))

        # Card panel
        card_w = min(700, width - 60)
        body_lines = lines[1:]
        card_h = 96 + len(body_lines) * 46 + 20
        card_x = width // 2 - card_w // 2
        card_y = max(60, height // 2 - card_h // 2 - 30)
        _draw_panel(screen, (card_x, card_y, card_w, card_h), (8, 16, 40, 235), radius=16)
        pygame.draw.rect(screen, PITCH_LINE, (card_x, card_y, card_w, card_h), width=1, border_radius=16)

        header = title_font.render(lines[0], True, GOLD)
        screen.blit(header, (width // 2 - header.get_width() // 2, card_y + 24))

        # Divider under header
        pygame.draw.line(screen, PITCH_LINE, (card_x + 24, card_y + 70), (card_x + card_w - 24, card_y + 70), 1)

        y = card_y + 84
        for line in body_lines:
            text = text_font.render(line, True, TEXT_COLOR)
            screen.blit(text, (width // 2 - text.get_width() // 2, y))
            y += 46

        hint = text_font.render("ENTER / SPACE  to continue", True, ACCENT)
        screen.blit(hint, (width // 2 - hint.get_width() // 2, height - 56))
        pygame.display.flip()
        clock.tick(FPS)


def _select_featured_team(
    screen: pygame.Surface,
    clock: pygame.time.Clock,
    title_font: pygame.font.Font,
    text_font: pygame.font.Font,
    teams: tuple[Team, ...],
    default_seed: int,
) -> Team | None:
    ordered = tuple(sorted(teams, key=lambda team: team.seed))
    selected_idx = next((idx for idx, team in enumerate(ordered) if team.seed == default_seed), 0)
    page_size = 18
    row_h = 24

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_UP:
                    selected_idx = max(0, selected_idx - 1)
                elif event.key == pygame.K_DOWN:
                    selected_idx = min(len(ordered) - 1, selected_idx + 1)
                elif event.key == pygame.K_PAGEUP:
                    selected_idx = max(0, selected_idx - page_size)
                elif event.key == pygame.K_PAGEDOWN:
                    selected_idx = min(len(ordered) - 1, selected_idx + page_size)
                elif event.key == pygame.K_RETURN:
                    return ordered[selected_idx]
                elif event.key == pygame.K_ESCAPE:
                    return None

        page_start = (selected_idx // page_size) * page_size
        page_end = min(len(ordered), page_start + page_size)

        width, height = screen.get_size()
        screen.fill(BG)
        for sx in range(0, width, 80):
            pygame.draw.rect(screen, PITCH_STRIPE, (sx, 0, 40, height))

        # Header
        _draw_panel(screen, (0, 0, width, 108), (8, 16, 40, 200), radius=0)
        pygame.draw.line(screen, PITCH_LINE, (0, 108), (width, 108), 1)
        header = title_font.render("Select Your Team", True, GOLD)
        screen.blit(header, (width // 2 - header.get_width() // 2, 20))
        help_text = text_font.render("UP / DOWN  •  PGUP / PGDN  •  ENTER to confirm", True, ACCENT)
        screen.blit(help_text, (width // 2 - help_text.get_width() // 2, 66))

        # Team list
        list_x = max(60, width // 2 - 480)
        y = 122
        for idx in range(page_start, page_end):
            team = ordered[idx]
            is_selected = idx == selected_idx
            if is_selected:
                _draw_panel(screen, (list_x - 8, y - 2, min(900, width - list_x * 2), row_h + 2), (ACCENT[0], ACCENT[1], ACCENT[2], 55), radius=5)
                pygame.draw.rect(screen, ACCENT, (list_x - 8, y - 2, min(900, width - list_x * 2), row_h + 2), width=1, border_radius=5)
            color = ACCENT if is_selected else TEXT_COLOR
            marker = ">" if is_selected else " "
            row = text_font.render(
                f"{marker} {team.seed:>3}. {team.name:<22}  OVR {team.overall_rating:>2}  SHO {team.shooting_rating:>2}  GK {team.reaction_rating:>2}  {team.region}",
                True,
                color,
            )
            screen.blit(row, (list_x, y))
            y += row_h

        page_label = text_font.render(
            f"Showing {page_start + 1}–{page_end} of {len(ordered)} teams",
            True,
            TEXT_COLOR,
        )
        screen.blit(page_label, (width // 2 - page_label.get_width() // 2, height - 36))
        pygame.display.flip()
        clock.tick(FPS)


def _teams_for_bracket_column(
    round_name: str,
    round_matches: dict[str, tuple[Match, ...]],
    round_winners: dict[str, tuple[Team, ...]],
) -> tuple[Team, ...]:
    winners = round_winners.get(round_name)
    if winners is not None:
        return winners
    matches = round_matches.get(round_name)
    if matches is None:
        return tuple()
    teams: list[Team] = []
    for match in matches:
        teams.append(match.team_a)
        teams.append(match.team_b)
    return tuple(teams)


def _show_playoff_bracket_screen(
    screen: pygame.Surface,
    clock: pygame.time.Clock,
    title_font: pygame.font.Font,
    text_font: pygame.font.Font,
    featured_team: Team,
    round_matches: dict[str, tuple[Match, ...]],
    round_winners: dict[str, tuple[Team, ...]],
    round_title: str,
) -> bool:
    columns = ["Round of 32", "Round of 16", "Quarterfinal", "Semifinal", "Final"]
    x_positions = [40, 230, 420, 610, 760]

    def short_name(team: Team, max_len: int = 16) -> str:
        return _team_compact_label(team, max_len)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return True

        width, height = screen.get_size()
        screen.fill(BG)
        for sx in range(0, width, 80):
            pygame.draw.rect(screen, PITCH_STRIPE, (sx, 0, 40, height))

        # Header panel
        _draw_panel(screen, (0, 0, width, 108), (8, 16, 40, 210), radius=0)
        pygame.draw.line(screen, PITCH_LINE, (0, 108), (width, 108), 1)
        title = title_font.render("Playoff Bracket", True, GOLD)
        subtitle = text_font.render(f"Current Round:  {round_title}", True, ACCENT)
        featured_label = text_font.render(f"Featured:  {_team_rating_line(featured_team)}", True, TEXT_COLOR)
        screen.blit(title, (width // 2 - title.get_width() // 2, 10))
        screen.blit(subtitle, (width // 2 - subtitle.get_width() // 2, 50))
        screen.blit(featured_label, (width // 2 - featured_label.get_width() // 2, 80))

        y_top = 130
        y_bottom = height - 48
        available_h = y_bottom - y_top

        positions_by_col: list[list[tuple[int, int, Team]]] = []
        for col_idx, round_name in enumerate(columns):
            teams = _teams_for_bracket_column(round_name, round_matches, round_winners)
            if not teams:
                positions_by_col.append([])
                continue

            x = x_positions[col_idx]
            step = available_h / max(1, len(teams))
            col_positions: list[tuple[int, int, Team]] = []
            for idx, team in enumerate(teams):
                y = int(y_top + step * idx + step / 2)
                col_positions.append((x, y, team))
                is_featured = team.seed == featured_team.seed
                color = ACCENT if is_featured else TEXT_COLOR
                if is_featured:
                    name_surf = text_font.render(short_name(team), True, color)
                    _draw_panel(screen, (x - 4, y - 12, name_surf.get_width() + 10, 22), (ACCENT[0], ACCENT[1], ACCENT[2], 40), radius=4)
                else:
                    name_surf = text_font.render(short_name(team), True, color)
                screen.blit(name_surf, (x, y - 8))

            label = text_font.render(round_name.replace("Round of ", "R"), True, ACCENT)
            screen.blit(label, (x, 112))
            positions_by_col.append(col_positions)

        # Bracket connector lines
        for col_idx in range(len(columns) - 1):
            left_col = positions_by_col[col_idx]
            right_col = positions_by_col[col_idx + 1]
            if not left_col or not right_col:
                continue
            for pair_idx in range(min(len(right_col), len(left_col) // 2)):
                left_a = left_col[pair_idx * 2]
                left_b = left_col[pair_idx * 2 + 1]
                right = right_col[pair_idx]

                x1 = left_a[0] + 162
                x2 = right[0] - 6
                y1 = left_a[1]
                y2 = left_b[1]
                ym = right[1]

                pygame.draw.line(screen, PITCH_LINE, (x1, y1), (x1 + 16, y1), 1)
                pygame.draw.line(screen, PITCH_LINE, (x1, y2), (x1 + 16, y2), 1)
                pygame.draw.line(screen, PITCH_LINE, (x1 + 16, y1), (x1 + 16, y2), 1)
                pygame.draw.line(screen, PITCH_LINE, (x1 + 16, ym), (x2, ym), 1)

        if "Final" in round_winners and round_winners["Final"]:
            champion = round_winners["Final"][0]
            champ_text = text_font.render(f"Champion:  {champion.name}", True, GOLD)
            _draw_panel(screen, (width // 2 - champ_text.get_width() // 2 - 12, height - 38, champ_text.get_width() + 24, 30), (8, 16, 40, 200), radius=8)
            screen.blit(champ_text, (width // 2 - champ_text.get_width() // 2, height - 32))
        else:
            hint = text_font.render("ENTER / SPACE  to continue", True, ACCENT)
            screen.blit(hint, (width // 2 - hint.get_width() // 2, height - 30))

        pygame.display.flip()
        clock.tick(FPS)


def _show_tournament_results_screen(
    screen: pygame.Surface,
    clock: pygame.time.Clock,
    title_font: pygame.font.Font,
    text_font: pygame.font.Font,
    featured_team: Team,
    round_order: tuple[str, ...],
    round_results: dict[str, tuple[TournamentMatchResult, ...]],
    start_round_name: str,
) -> bool:
    def flatten_results() -> list[TournamentMatchResult]:
        flattened: list[TournamentMatchResult] = []
        for name in round_order:
            flattened.extend(round_results.get(name, ()))
        return flattened

    def featured_path_lines() -> list[str]:
        lines: list[str] = []
        all_results = flatten_results()
        featured_matches = [
            result
            for result in all_results
            if result.team_a.seed == featured_team.seed or result.team_b.seed == featured_team.seed
        ]
        if not featured_matches:
            return ["No featured matches yet"]

        for result in featured_matches[-5:]:
            won = result.winner.seed == featured_team.seed
            lines.append(f"{result.round_name}: {'W' if won else 'L'} {result.score_a}-{result.score_b}")
        return lines

    def featured_status_line() -> str:
        all_results = flatten_results()
        featured_matches = [
            result
            for result in all_results
            if result.team_a.seed == featured_team.seed or result.team_b.seed == featured_team.seed
        ]
        if not featured_matches:
            return "Status: waiting to debut"

        last = featured_matches[-1]
        if last.winner.seed == featured_team.seed:
            if "Final" in round_results and round_results["Final"]:
                return (
                    "Status: champion"
                    if round_results["Final"][0].winner.seed == featured_team.seed
                    else "Status: eliminated"
                )
            return "Status: still alive"
        return f"Status: eliminated in {last.round_name}"

    def biggest_upset_lines() -> list[str]:
        all_results = flatten_results()
        upsets: list[tuple[int, TournamentMatchResult, Team]] = []
        for result in all_results:
            loser = result.team_b if result.winner.seed == result.team_a.seed else result.team_a
            margin = result.winner.seed - loser.seed
            if margin > 0:
                upsets.append((margin, result, loser))

        if not upsets:
            return ["No upsets yet"]

        upsets.sort(key=lambda item: (-item[0], round_order.index(item[1].round_name), item[1].match_number))
        return [f"+{margin} {result.winner.name} over {loser.name}" for margin, result, loser in upsets[:3]]

    def short_name(name: str, max_len: int = 16) -> str:
        if len(name) <= max_len:
            return name
        return name[: max_len - 1] + "."

    def shorten_to_width(font_obj: pygame.font.Font, text: str, max_width: int) -> str:
        if font_obj.size(text)[0] <= max_width:
            return text
        suffix = "..."
        trimmed = text
        while trimmed and font_obj.size(trimmed + suffix)[0] > max_width:
            trimmed = trimmed[:-1]
        return (trimmed + suffix) if trimmed else suffix

    round_idx = next((idx for idx, name in enumerate(round_order) if name == start_round_name), 0)
    row_offset = 0
    rows_per_page = 12
    line_font = pygame.font.SysFont("consolas", 18)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    return True
                if event.key == pygame.K_LEFT:
                    round_idx = max(0, round_idx - 1)
                    row_offset = 0
                elif event.key == pygame.K_RIGHT:
                    round_idx = min(len(round_order) - 1, round_idx + 1)
                    row_offset = 0
                elif event.key == pygame.K_UP:
                    row_offset = max(0, row_offset - 1)
                elif event.key == pygame.K_DOWN:
                    active_round = round_order[round_idx]
                    max_offset = max(0, len(round_results.get(active_round, ())) - rows_per_page)
                    row_offset = min(max_offset, row_offset + 1)

        active_round = round_order[round_idx]
        results = round_results.get(active_round, ())
        width, height = screen.get_size()

        screen.fill(BG)
        title = title_font.render("Tournament Results", True, TEXT_COLOR)
        round_label = text_font.render(f"Round: {active_round}", True, ACCENT)
        help_line = text_font.render("LEFT/RIGHT round  UP/DOWN scroll  ENTER continue", True, TEXT_COLOR)
        screen.blit(title, (width // 2 - title.get_width() // 2, 16))
        screen.blit(round_label, (width // 2 - round_label.get_width() // 2, 62))
        screen.blit(help_line, (width // 2 - help_line.get_width() // 2, 90))

        divider_x = int(width * 0.66)
        left_x = 28
        left_w = divider_x - left_x - 16
        panel_x = divider_x + 18
        panel_w = width - panel_x - 20
        pygame.draw.line(screen, PITCH_LINE, (divider_x, 120), (divider_x, height - 26), 1)

        y = 130
        if not results:
            pending = text_font.render("No results yet for this round.", True, TEXT_COLOR)
            screen.blit(pending, (left_x, y + 80))
        else:
            visible = results[row_offset : row_offset + rows_per_page]
            for result in visible:
                featured_row = result.team_a.seed == featured_team.seed or result.team_b.seed == featured_team.seed
                row_color = ACCENT if featured_row else TEXT_COLOR
                row_text = (
                    f"{result.match_number:>2}/{result.total_matches:<2} "
                    f"{_team_compact_label(result.team_a, 16):<16} {result.score_a}-{result.score_b} "
                    f"{_team_compact_label(result.team_b, 16):<16} W:{_team_compact_label(result.winner, 14)}"
                )
                rendered = line_font.render(shorten_to_width(line_font, row_text, left_w), True, row_color)
                screen.blit(rendered, (left_x, y))
                y += 24

            page = text_font.render(
                f"Showing {row_offset + 1}-{min(len(results), row_offset + rows_per_page)} of {len(results)}",
                True,
                TEXT_COLOR,
            )
            screen.blit(page, (left_x, height - 56))

        panel_y = 128
        panel_title = text_font.render("Timeline", True, GOOD)
        screen.blit(panel_title, (panel_x, panel_y))

        status_text = line_font.render(shorten_to_width(line_font, featured_status_line(), panel_w), True, TEXT_COLOR)
        screen.blit(status_text, (panel_x, panel_y + 28))

        path_header = text_font.render("Featured Path", True, ACCENT)
        screen.blit(path_header, (panel_x, panel_y + 62))
        path_y = panel_y + 88
        for line in featured_path_lines():
            rendered = line_font.render(shorten_to_width(line_font, short_name(line, 48), panel_w), True, TEXT_COLOR)
            screen.blit(rendered, (panel_x, path_y))
            path_y += 22

        upset_header = text_font.render("Biggest Upsets", True, ACCENT)
        screen.blit(upset_header, (panel_x, path_y + 12))
        upset_y = path_y + 38
        for line in biggest_upset_lines():
            rendered = line_font.render(shorten_to_width(line_font, short_name(line, 52), panel_w), True, TEXT_COLOR)
            screen.blit(rendered, (panel_x, upset_y))
            upset_y += 22

        final_results = round_results.get("Final", ())
        if final_results:
            champion = final_results[0].winner
            champion_line = text_font.render(f"Champion so far: {champion.name}", True, GOOD)
            screen.blit(champion_line, (width // 2 - champion_line.get_width() // 2, height - 28))

        pygame.display.flip()
        clock.tick(FPS)


def _play_visual_shootout(
    screen: pygame.Surface,
    clock: pygame.time.Clock,
    title_font: pygame.font.Font,
    text_font: pygame.font.Font,
    rng: Random,
    player_team: Team,
    ai_team: Team,
    title: str,
) -> tuple[Team, int, int]:
    game = VisualPenaltyGame(player_team=player_team, ai_team=ai_team, rng=rng, title=title)
    while True:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit(0)
            game.handle_event(event)

        game.update(dt)
        game.render(screen, title_font, text_font)
        pygame.display.flip()

        if game.scene_complete and game.winner is not None:
            return game.winner, game.score_player, game.score_ai


def _round_matches_seeded(teams: tuple[Team, ...], round_name: str) -> tuple[Match, ...]:
    return tuple(Match(pair.team_a, pair.team_b, round_name) for pair in create_seeded_pairings(teams))


def _round_matches_open(rng: Random, teams: tuple[Team, ...], round_name: str) -> tuple[Match, ...]:
    pool = list(teams)
    rng.shuffle(pool)
    return tuple(Match(pool[i], pool[i + 1], round_name) for i in range(0, len(pool), 2))


def run_visual_tournament(seed: int | None = None, featured_seed: int = 1) -> int:
    rng = Random(seed)
    cup = GlobalKnockoutCup(rng=rng)
    all_teams = tuple(sorted(cup.teams, key=lambda team: team.seed))

    pygame.init()
    pygame.display.set_caption("Total World Cup - Visual Tournament")
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    clock = pygame.time.Clock()
    title_font = pygame.font.SysFont("segoeui", 34, bold=True)
    text_font = pygame.font.SysFont("consolas", 22)

    featured = _select_featured_team(screen, clock, title_font, text_font, all_teams, featured_seed)
    if featured is None:
        pygame.quit()
        return 0

    if not _show_info_screen(
        screen,
        clock,
        title_font,
        text_font,
        [
            "Featured Tournament",
            f"You control: {_team_rating_line(featured)}",
            "You will play only featured matches.",
            "All other matches are auto-simulated.",
        ],
    ):
        pygame.quit()
        return 0

    round_matches: dict[str, tuple[Match, ...]] = {}
    round_winners: dict[str, tuple[Team, ...]] = {}
    round_results: dict[str, tuple[TournamentMatchResult, ...]] = {}
    round_order: tuple[str, ...] = (
        "Preliminary Round",
        "Round of 128",
        "Round of 64",
        "Round of 32",
        "Round of 16",
        "Quarterfinal",
        "Semifinal",
        "Final",
    )

    def play_round(matches: tuple[Match, ...], round_name: str) -> tuple[Team, ...]:
        round_matches[round_name] = matches
        if round_name in ("Round of 32", "Round of 16", "Quarterfinal", "Semifinal", "Final"):
            if not _show_playoff_bracket_screen(
                screen,
                clock,
                title_font,
                text_font,
                featured,
                round_matches,
                round_winners,
                round_name,
            ):
                pygame.quit()
                raise SystemExit(0)

        winners: list[Team] = []
        results_for_round: list[TournamentMatchResult] = []
        for idx, match in enumerate(matches, start=1):
            involves_featured = match.team_a.seed == featured.seed or match.team_b.seed == featured.seed
            if involves_featured:
                player_team = match.team_a if match.team_a.seed == featured.seed else match.team_b
                ai_team = match.team_b if player_team == match.team_a else match.team_a

                if not _show_info_screen(
                    screen,
                    clock,
                    title_font,
                    text_font,
                    [
                        f"{round_name} - Featured Match",
                        _team_rating_line(player_team),
                        _team_rating_line(ai_team),
                        f"Match {idx} of {len(matches)}",
                    ],
                ):
                    pygame.quit()
                    raise SystemExit(0)

                winner, player_score, ai_score = _play_visual_shootout(
                    screen,
                    clock,
                    title_font,
                    text_font,
                    rng,
                    player_team=player_team,
                    ai_team=ai_team,
                    title=f"{round_name} - Featured Match",
                )
                winners.append(winner)

                if player_team.seed == match.team_a.seed:
                    score_a = player_score
                    score_b = ai_score
                else:
                    score_a = ai_score
                    score_b = player_score
                results_for_round.append(
                    TournamentMatchResult(
                        round_name=round_name,
                        match_number=idx,
                        total_matches=len(matches),
                        team_a=match.team_a,
                        team_b=match.team_b,
                        winner=winner,
                        score_a=score_a,
                        score_b=score_b,
                        was_featured_match=True,
                    )
                )
            else:
                auto_result = cup.shootout_engine.shootout(match.team_a, match.team_b)
                winners.append(auto_result.winner)
                results_for_round.append(
                    TournamentMatchResult(
                        round_name=round_name,
                        match_number=idx,
                        total_matches=len(matches),
                        team_a=match.team_a,
                        team_b=match.team_b,
                        winner=auto_result.winner,
                        score_a=auto_result.score_a,
                        score_b=auto_result.score_b,
                        was_featured_match=False,
                    )
                )
        winners_tuple = tuple(winners)
        round_winners[round_name] = winners_tuple
        round_results[round_name] = tuple(results_for_round)

        if not _show_tournament_results_screen(
            screen,
            clock,
            title_font,
            text_font,
            featured,
            round_order,
            round_results,
            start_round_name=round_name,
        ):
            pygame.quit()
            raise SystemExit(0)

        return winners_tuple

    plan = cup.create_tournament_plan()

    # Phase 1 Preliminary — all regions together.
    all_prelim_matches = tuple(m for matches in plan.regional_preliminary.values() for m in matches)
    preliminary_winners = play_round(all_prelim_matches, "Preliminary Round")

    # Regional Round of 128.
    r128_list: list[Match] = []
    for region_name, region_byes in plan.regional_byes.items():
        region_prelim_winners = tuple(w for w in preliminary_winners if w.region == region_name)
        r128_teams = tuple(sorted((*region_byes, *region_prelim_winners), key=lambda t: t.seed))
        r128_list.extend(Match(p.team_a, p.team_b, "Round of 128") for p in create_seeded_pairings(r128_teams))
    r128_winners = play_round(tuple(r128_list), "Round of 128")

    # Regional Round of 64.
    r64_list: list[Match] = []
    for region_name in plan.regions:
        region_r128_winners = tuple(w for w in r128_winners if w.region == region_name)
        r64_list.extend(Match(p.team_a, p.team_b, "Round of 64") for p in create_seeded_pairings(region_r128_winners))
    qualified_32 = play_round(tuple(r64_list), "Round of 64")

    current = qualified_32
    for round_name in ("Round of 32", "Round of 16", "Quarterfinal", "Semifinal", "Final"):
        matches = _round_matches_open(rng, current, round_name)
        current = play_round(matches, round_name)

    champion = current[0]
    _show_playoff_bracket_screen(
        screen,
        clock,
        title_font,
        text_font,
        featured,
        round_matches,
        round_winners,
        "Final",
    )
    outcome_lines = [
        "Tournament Complete",
        f"Champion: {_team_rating_line(champion)}",
        "Featured team won the cup" if champion.seed == featured.seed else "Featured team did not win the cup",
    ]

    if not _show_tournament_results_screen(
        screen,
        clock,
        title_font,
        text_font,
        featured,
        round_order,
        round_results,
        start_round_name="Final",
    ):
        pygame.quit()
        return 0

    _show_info_screen(screen, clock, title_font, text_font, outcome_lines)
    pygame.quit()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Play a visual penalty shootout mode.")
    parser.add_argument(
        "--mode",
        choices=("single", "tournament"),
        default="single",
        help="single: one visual shootout. tournament: full featured-team tournament.",
    )
    parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed.")
    parser.add_argument("--featured-seed", type=int, default=1, help="Seed of the team you control.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.mode == "tournament":
        return run_visual_tournament(seed=args.seed, featured_seed=args.featured_seed)
    return run_visual_match(seed=args.seed, featured_seed=args.featured_seed)


if __name__ == "__main__":
    raise SystemExit(main())
