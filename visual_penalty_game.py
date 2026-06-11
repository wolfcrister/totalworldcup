from __future__ import annotations

import argparse
from dataclasses import dataclass
from random import Random

import pygame

from global_knockout_cup import Direction, GlobalKnockoutCup, Match, PenaltyShootoutEngine, Team, clamp, create_seeded_pairings

WIDTH = 960
HEIGHT = 540
FPS = 60

BG = (18, 74, 46)
PITCH_LINE = (220, 235, 220)
GOAL_COLOR = (240, 240, 240)
BALL_COLOR = (250, 250, 250)
BALL_SHADOW = (120, 120, 120)
KEEPER_COLOR = (240, 180, 40)
TEXT_COLOR = (245, 245, 245)
ACCENT = (50, 200, 255)
GOOD = (60, 220, 90)
BAD = (230, 80, 80)

DIRECTION_ORDER: tuple[Direction, ...] = ("left", "centre", "right")


@dataclass
class ShotAnimation:
    shooter: Team
    goalkeeper: Team
    shot_direction: Direction
    keeper_dive: Direction
    timing_quality: float
    scored: bool
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
        self.finished = False
        self.winner: Team | None = None

        self.current_phase = "player_direction"
        self.player_is_shooting = True
        self.selection_index = 1
        self.timing_value = 0.0
        self.timing_direction = 1.0
        self.selected_timing = 0.5
        self._pending_shot_direction: Direction = "centre"
        self.phase_clock = 0.0
        self.scene_complete = False

        self.player_dive_choice: Direction = "centre"
        self.current_animation: ShotAnimation | None = None
        self.last_message = "Press LEFT/RIGHT then ENTER to pick your shot direction"

    def _balanced_team(self, team: Team) -> Team:
        # Compress extremes so visual matches remain dramatic even with large seed gaps.
        blend = 0.55
        return Team(
            name=team.name,
            seed=team.seed,
            region=team.region,
            penalty_strength=clamp(0.5 + (team.penalty_strength - 0.5) * blend, 0.0, 1.0),
            goalkeeper_rating=clamp(0.5 + (team.goalkeeper_rating - 0.5) * blend, 0.0, 1.0),
        )

    def _map_index_to_direction(self, idx: int) -> Direction:
        return DIRECTION_ORDER[max(0, min(2, idx))]

    def _sample_ai_shot_direction(self, team: Team) -> Direction:
        weights = [0.34, 0.32, 0.34]
        if team.penalty_strength > 0.65:
            weights = [0.38, 0.24, 0.38]
        return self.rng.choices(DIRECTION_ORDER, weights=weights, k=1)[0]

    def _sample_ai_dive_direction(self, team: Team) -> Direction:
        weights = [0.33, 0.34, 0.33]
        if team.goalkeeper_rating > 0.65:
            weights = [0.36, 0.28, 0.36]
        return self.rng.choices(DIRECTION_ORDER, weights=weights, k=1)[0]

    def _sample_ai_timing(self, team: Team) -> float:
        base = 0.5 + (team.penalty_strength - 0.5) * 0.20
        jitter = self.rng.uniform(-0.20, 0.20)
        return clamp(base + jitter, 0.0, 1.0)

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

    def _finalize_player_shot(self, shot_direction: Direction, timing_quality: float) -> None:
        self.taken_player += 1
        keeper_dive = self._sample_ai_dive_direction(self.ai_team)
        keeper_read = shot_direction == keeper_dive
        scored = self._resolve_visual_kick(
            shooter=self._engine_player_team,
            goalkeeper=self._engine_ai_team,
            shot_direction=shot_direction,
            keeper_dive=keeper_dive,
            kick_number_for_shooter=self.taken_player,
            timing_quality=timing_quality,
        )
        self.score_player += int(scored)

        self.current_animation = ShotAnimation(
            shooter=self.player_team,
            goalkeeper=self.ai_team,
            shot_direction=shot_direction,
            keeper_dive=keeper_dive,
            timing_quality=timing_quality,
            scored=scored,
            kick_index=self.taken_player,
            is_player_shot=True,
        )
        self.phase_clock = 0.0
        self.current_phase = "animate_shot"
        self.last_message = "GOAL" if scored else "SAVED"

    def _finalize_ai_shot(self, keeper_dive: Direction) -> None:
        self.taken_ai += 1
        ai_direction = self._sample_ai_shot_direction(self._engine_ai_team)
        ai_timing = self._sample_ai_timing(self._engine_ai_team)
        keeper_read = ai_direction == keeper_dive
        scored = self._resolve_visual_kick(
            shooter=self._engine_ai_team,
            goalkeeper=self._engine_player_team,
            shot_direction=ai_direction,
            keeper_dive=keeper_dive,
            kick_number_for_shooter=self.taken_ai,
            timing_quality=ai_timing,
        )
        self.score_ai += int(scored)

        self.current_animation = ShotAnimation(
            shooter=self.ai_team,
            goalkeeper=self.player_team,
            shot_direction=ai_direction,
            keeper_dive=keeper_dive,
            timing_quality=ai_timing,
            scored=scored,
            kick_index=self.taken_ai,
            is_player_shot=False,
        )
        self.phase_clock = 0.0
        self.current_phase = "animate_shot"
        self.last_message = "AI SCORED" if scored else "YOU SAVED"

    def _resolve_visual_kick(
        self,
        shooter: Team,
        goalkeeper: Team,
        shot_direction: Direction,
        keeper_dive: Direction,
        kick_number_for_shooter: int,
        timing_quality: float,
    ) -> bool:
        # Visual mode is a pure guessing game: right read saves, wrong read scores.
        if shot_direction == keeper_dive:
            return False
        return True

    def _next_phase_after_animation(self) -> None:
        self._check_finish()
        if self.finished:
            self.current_phase = "finished"
            self.last_message = "You win the shootout" if self.winner == self.player_team else "AI wins the shootout"
            return

        self.player_is_shooting = not self.player_is_shooting
        self.selection_index = 1
        if self.player_is_shooting:
            self.current_phase = "player_direction"
            self.last_message = "Your shot. Pick direction: LEFT/CENTRE/RIGHT, then ENTER"
        else:
            self.current_phase = "ai_dive"
            self.last_message = "AI is shooting. Pick dive: LEFT/DOWN/RIGHT, then ENTER"

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
                self.selection_index = min(2, self.selection_index + 1)
            elif event.key == pygame.K_DOWN and self.current_phase == "ai_dive":
                self.selection_index = 1
            elif event.key == pygame.K_RETURN:
                direction = self._map_index_to_direction(self.selection_index)
                if self.current_phase == "player_direction":
                    self.current_phase = "player_timing"
                    self.timing_value = 0.0
                    self.timing_direction = 1.0
                    self.last_message = "Press SPACE to lock timing"
                    self._pending_shot_direction = direction
                else:
                    self.player_dive_choice = direction
                    self._finalize_ai_shot(self.player_dive_choice)

        elif self.current_phase == "player_timing" and event.key == pygame.K_SPACE:
            self.selected_timing = self.timing_value
            self._finalize_player_shot(self._pending_shot_direction, self.selected_timing)

    def update(self, dt: float) -> None:
        if self.current_phase == "player_timing":
            self.timing_value += dt * self.timing_direction * 1.4
            if self.timing_value >= 1.0:
                self.timing_value = 1.0
                self.timing_direction = -1.0
            elif self.timing_value <= 0.0:
                self.timing_value = 0.0
                self.timing_direction = 1.0

        if self.current_phase == "animate_shot":
            self.phase_clock += dt
            if self.phase_clock >= 1.0:
                self._next_phase_after_animation()

    def _draw_pitch(self, screen: pygame.Surface) -> None:
        screen.fill(BG)
        pygame.draw.rect(screen, PITCH_LINE, (80, 100, WIDTH - 160, HEIGHT - 180), width=3)
        pygame.draw.rect(screen, GOAL_COLOR, (WIDTH // 2 - 150, 90, 300, 28), width=4)
        pygame.draw.rect(screen, PITCH_LINE, (WIDTH // 2 - 220, 118, 440, 90), width=2)

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

        goal_center_x = WIDTH // 2
        goal_y = 104
        start_x = WIDTH // 2
        start_y = HEIGHT - 110

        target_x = self._direction_x(shot.shot_direction, goal_center_x, 120)
        ball_x = int(start_x + (target_x - start_x) * progress)
        ball_y = int(start_y + (goal_y - start_y) * progress)

        keeper_x = self._direction_x(shot.keeper_dive, goal_center_x, 120)
        keeper_y = 120

        pygame.draw.circle(screen, BALL_SHADOW, (ball_x + 2, ball_y + 2), 10)
        pygame.draw.circle(screen, BALL_COLOR, (ball_x, ball_y), 10)

        pygame.draw.rect(screen, KEEPER_COLOR, (keeper_x - 18, keeper_y, 36, 24), border_radius=4)

    def _draw_selection(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        if self.current_phase not in ("player_direction", "ai_dive"):
            return

        labels = ["LEFT", "CENTRE", "RIGHT"]
        base_x = WIDTH // 2 - 180
        y = HEIGHT - 60
        for idx, label in enumerate(labels):
            color = ACCENT if idx == self.selection_index else TEXT_COLOR
            text = font.render(label, True, color)
            screen.blit(text, (base_x + idx * 160, y))

    def _draw_timing_meter(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        if self.current_phase != "player_timing":
            return

        x = WIDTH // 2 - 220
        y = HEIGHT - 80
        w = 440
        h = 20
        pygame.draw.rect(screen, (40, 40, 40), (x, y, w, h))

        green_x = x + int(w * 0.4)
        green_w = int(w * 0.2)
        pygame.draw.rect(screen, GOOD, (green_x, y, green_w, h))

        cursor_x = x + int(self.timing_value * w)
        pygame.draw.rect(screen, BALL_COLOR, (cursor_x - 3, y - 6, 6, h + 12))

        help_text = font.render("Press SPACE", True, TEXT_COLOR)
        screen.blit(help_text, (x, y - 30))

    def _draw_hud(self, screen: pygame.Surface, font: pygame.font.Font, small_font: pygame.font.Font) -> None:
        title = font.render(f"{self.player_team.name} vs {self.ai_team.name}", True, TEXT_COLOR)
        subtitle = small_font.render(self.title, True, TEXT_COLOR)
        score = font.render(f"{self.score_player} - {self.score_ai}", True, TEXT_COLOR)
        rounds = small_font.render(
            f"Kicks: You {self.taken_player} / AI {self.taken_ai}",
            True,
            TEXT_COLOR,
        )
        status_color = GOOD if "win" in self.last_message.lower() or "goal" in self.last_message.lower() else BAD
        if self.current_phase in ("player_direction", "player_timing", "ai_dive"):
            status_color = TEXT_COLOR
        status = small_font.render(self.last_message, True, status_color)

        screen.blit(title, (20, 18))
        screen.blit(subtitle, (20, 56))
        screen.blit(score, (WIDTH - 160, 18))
        screen.blit(rounds, (20, 84))
        screen.blit(status, (20, HEIGHT - 34))

        if self.current_phase == "finished":
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 120))
            screen.blit(overlay, (0, 0))
            message = "YOU WIN" if self.winner == self.player_team else "AI WINS"
            msg_text = font.render(message, True, TEXT_COLOR)
            hint_text = small_font.render("Press ENTER or ESC to quit", True, TEXT_COLOR)
            screen.blit(msg_text, (WIDTH // 2 - msg_text.get_width() // 2, HEIGHT // 2 - 20))
            screen.blit(hint_text, (WIDTH // 2 - hint_text.get_width() // 2, HEIGHT // 2 + 26))

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
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
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

        screen.fill(BG)
        header = title_font.render(lines[0], True, TEXT_COLOR)
        screen.blit(header, (WIDTH // 2 - header.get_width() // 2, 120))

        y = 200
        for line in lines[1:]:
            text = text_font.render(line, True, TEXT_COLOR)
            screen.blit(text, (WIDTH // 2 - text.get_width() // 2, y))
            y += 42

        hint = text_font.render("Press ENTER or SPACE", True, ACCENT)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 80))
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

        screen.fill(BG)
        header = title_font.render("Select Your Team", True, TEXT_COLOR)
        screen.blit(header, (WIDTH // 2 - header.get_width() // 2, 40))

        help_text = text_font.render("UP/DOWN to move, ENTER to confirm, PAGEUP/PAGEDOWN to jump", True, ACCENT)
        screen.blit(help_text, (WIDTH // 2 - help_text.get_width() // 2, 86))

        y = 130
        for idx in range(page_start, page_end):
            team = ordered[idx]
            is_selected = idx == selected_idx
            color = ACCENT if is_selected else TEXT_COLOR
            marker = ">" if is_selected else " "
            row = text_font.render(f"{marker} {team.seed:>3}. {team.name}", True, color)
            screen.blit(row, (220, y))
            y += 21

        page_label = text_font.render(
            f"Showing {page_start + 1}-{page_end} of {len(ordered)} teams",
            True,
            TEXT_COLOR,
        )
        screen.blit(page_label, (WIDTH // 2 - page_label.get_width() // 2, HEIGHT - 34))
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

    def short_name(team_name: str, max_len: int = 14) -> str:
        if len(team_name) <= max_len:
            return team_name
        return team_name[: max_len - 1] + "."

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return True

        screen.fill(BG)
        title = title_font.render("Playoff Tree", True, TEXT_COLOR)
        subtitle = text_font.render(f"Current Round: {round_title}", True, ACCENT)
        featured_label = text_font.render(f"Featured Team: {featured_team.name}", True, TEXT_COLOR)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 12))
        screen.blit(subtitle, (WIDTH // 2 - subtitle.get_width() // 2, 54))
        screen.blit(featured_label, (WIDTH // 2 - featured_label.get_width() // 2, 84))

        y_top = 130
        y_bottom = HEIGHT - 48
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
                color = ACCENT if team.seed == featured_team.seed else TEXT_COLOR
                name_text = text_font.render(short_name(team.name), True, color)
                screen.blit(name_text, (x, y - 8))

            label = text_font.render(round_name.replace("Round of ", "R"), True, TEXT_COLOR)
            screen.blit(label, (x, 108))
            positions_by_col.append(col_positions)

        # Draw connector lines between rounds for a bracket feel.
        for col_idx in range(len(columns) - 1):
            left_col = positions_by_col[col_idx]
            right_col = positions_by_col[col_idx + 1]
            if not left_col or not right_col:
                continue
            for pair_idx in range(min(len(right_col), len(left_col) // 2)):
                left_a = left_col[pair_idx * 2]
                left_b = left_col[pair_idx * 2 + 1]
                right = right_col[pair_idx]

                x1 = left_a[0] + 160
                x2 = right[0] - 8
                y1 = left_a[1]
                y2 = left_b[1]
                ym = right[1]

                pygame.draw.line(screen, PITCH_LINE, (x1, y1), (x1 + 18, y1), 1)
                pygame.draw.line(screen, PITCH_LINE, (x1, y2), (x1 + 18, y2), 1)
                pygame.draw.line(screen, PITCH_LINE, (x1 + 18, y1), (x1 + 18, y2), 1)
                pygame.draw.line(screen, PITCH_LINE, (x1 + 18, ym), (x2, ym), 1)

        if "Final" in round_winners and round_winners["Final"]:
            champion = round_winners["Final"][0]
            champ_text = text_font.render(f"Champion: {champion.name}", True, GOOD)
            screen.blit(champ_text, (WIDTH // 2 - champ_text.get_width() // 2, HEIGHT - 24))
        else:
            hint = text_font.render("Press ENTER/SPACE to continue", True, ACCENT)
            screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 24))

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
            lines.append(
                f"{result.round_name}: {'W' if won else 'L'} "
                f"{result.score_a}-{result.score_b}"
            )
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
                return "Status: champion" if round_results["Final"][0].winner.seed == featured_team.seed else "Status: eliminated"
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
        lines: list[str] = []
        for margin, result, loser in upsets[:3]:
            lines.append(
                f"+{margin} {result.winner.name} over {loser.name}"
            )
        return lines

    round_idx = next((idx for idx, name in enumerate(round_order) if name == start_round_name), 0)
    row_offset = 0
    rows_per_page = 12

    def short_name(name: str, max_len: int = 16) -> str:
        if len(name) <= max_len:
            return name
        return name[: max_len - 1] + "."

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

        screen.fill(BG)
        title = title_font.render("Tournament Results", True, TEXT_COLOR)
        round_label = text_font.render(f"Round: {active_round}", True, ACCENT)
        help_line = text_font.render("LEFT/RIGHT round  UP/DOWN scroll  ENTER continue", True, TEXT_COLOR)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 16))
        screen.blit(round_label, (WIDTH // 2 - round_label.get_width() // 2, 62))
        screen.blit(help_line, (WIDTH // 2 - help_line.get_width() // 2, 90))

        divider_x = 620
        pygame.draw.line(screen, PITCH_LINE, (divider_x, 120), (divider_x, HEIGHT - 26), 1)

        y = 130
        if not results:
            pending = text_font.render("No results yet for this round.", True, TEXT_COLOR)
            screen.blit(pending, (60, y + 80))
        else:
            visible = results[row_offset : row_offset + rows_per_page]
            for result in visible:
                featured_row = result.team_a.seed == featured_team.seed or result.team_b.seed == featured_team.seed
                row_color = ACCENT if featured_row else TEXT_COLOR
                row_text = (
                    f"{result.match_number:>2}/{result.total_matches:<2} "
                    f"{short_name(result.team_a.name):<16} {result.score_a}-{result.score_b} "
                    f"{short_name(result.team_b.name):<16} W: {short_name(result.winner.name, 14)}"
                )
                rendered = text_font.render(row_text, True, row_color)
                screen.blit(rendered, (36, y))
                y += 26

            page = text_font.render(
                f"Showing {row_offset + 1}-{min(len(results), row_offset + rows_per_page)} of {len(results)}",
                True,
                TEXT_COLOR,
            )
            screen.blit(page, (36, HEIGHT - 56))

        panel_x = 640
        panel_y = 128
        panel_title = text_font.render("Timeline", True, GOOD)
        screen.blit(panel_title, (panel_x, panel_y))

        status_text = text_font.render(featured_status_line(), True, TEXT_COLOR)
        screen.blit(status_text, (panel_x, panel_y + 28))

        path_header = text_font.render("Featured Path", True, ACCENT)
        screen.blit(path_header, (panel_x, panel_y + 62))
        path_y = panel_y + 88
        for line in featured_path_lines():
            rendered = text_font.render(short_name(line, 28), True, TEXT_COLOR)
            screen.blit(rendered, (panel_x, path_y))
            path_y += 22

        upset_header = text_font.render("Biggest Upsets", True, ACCENT)
        screen.blit(upset_header, (panel_x, path_y + 12))
        upset_y = path_y + 38
        for line in biggest_upset_lines():
            rendered = text_font.render(short_name(line, 30), True, TEXT_COLOR)
            screen.blit(rendered, (panel_x, upset_y))
            upset_y += 22

        final_results = round_results.get("Final", ())
        if final_results:
            champion = final_results[0].winner
            champion_line = text_font.render(f"Champion so far: {champion.name}", True, GOOD)
            screen.blit(champion_line, (WIDTH // 2 - champion_line.get_width() // 2, HEIGHT - 28))

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
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
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
            f"You control: {featured.name} (seed {featured.seed})",
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
                        f"{player_team.name} vs {ai_team.name}",
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
    preliminary_winners = play_round(plan.preliminary_matches, "Preliminary Round")

    phase1_128_teams = tuple(sorted((*plan.preliminary_byes, *preliminary_winners), key=lambda t: t.seed))
    round_128 = _round_matches_seeded(phase1_128_teams, "Round of 128")
    round_64_teams = play_round(round_128, "Round of 128")

    round_64 = _round_matches_seeded(round_64_teams, "Round of 64")
    qualified_32 = play_round(round_64, "Round of 64")

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
        f"Champion: {champion.name} (seed {champion.seed})",
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
