import unittest
from random import Random
from unittest.mock import patch

from global_knockout_cup import (
    GlobalKnockoutCup,
    PenaltyShootoutEngine,
    Team,
    assign_regions_snake,
    generate_teams,
    get_project_status,
)


class GlobalKnockoutCupTests(unittest.TestCase):
    def test_shootout_ends_early_when_lead_is_unbeatable(self):
        team_a = Team("A", seed=1, penalty_strength=1.0, goalkeeper_rating=1.0)
        team_b = Team("B", seed=2, penalty_strength=0.0, goalkeeper_rating=0.0)
        engine = PenaltyShootoutEngine(Random(0))

        scripted_results = iter([True, False, True, False, True, False])
        with patch.object(engine, "resolve_kick", side_effect=lambda *args, **kwargs: next(scripted_results)):
            result = engine.shootout(team_a, team_b)

        self.assertEqual(result.winner, team_a)
        self.assertEqual(result.score_a, 3)
        self.assertEqual(result.score_b, 0)
        self.assertEqual(len(result.kicks), 6)

    def test_shootout_goes_to_sudden_death_when_tied_after_five_each(self):
        team_a = Team("A", seed=1)
        team_b = Team("B", seed=2)
        engine = PenaltyShootoutEngine(Random(1))

        # 10 kicks level at 4-4, then both score, then A scores and B misses.
        scripted_results = iter([
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            True,
            True,
            False,
        ])
        with patch.object(engine, "resolve_kick", side_effect=lambda *args, **kwargs: next(scripted_results)):
            result = engine.shootout(team_a, team_b)

        self.assertEqual(result.winner, team_a)
        self.assertEqual(result.score_a, 6)
        self.assertEqual(result.score_b, 5)
        self.assertEqual(len(result.kicks), 14)

    def test_shootout_integration_uses_real_probability_logic(self):
        team_a = Team("A", seed=1, penalty_strength=0.9, goalkeeper_rating=0.8)
        team_b = Team("B", seed=2, penalty_strength=0.4, goalkeeper_rating=0.3)
        engine = PenaltyShootoutEngine(Random(7))

        result = engine.shootout(team_a, team_b)

        self.assertGreaterEqual(len(result.kicks), 6)
        self.assertLessEqual(len(result.kicks), 20)
        self.assertIn(result.winner, (team_a, team_b))
        self.assertEqual(result.winner, team_a)

    def test_tournament_plan_and_progression_sizes_match_spec(self):
        cup = GlobalKnockoutCup(rng=Random(2))
        plan = cup.create_tournament_plan()

        self.assertEqual(len(cup.teams), 211)
        self.assertEqual(len(plan.preliminary_byes), 45)
        self.assertEqual(len(plan.preliminary_matches), 83)
        prelim_seeds = {team.seed for match in plan.preliminary_matches for team in (match.team_a, match.team_b)}
        self.assertEqual(min(prelim_seeds), 46)
        self.assertEqual(max(prelim_seeds), 211)

        outcome = cup.run_tournament()
        self.assertEqual(len(outcome.phase1_qualified_32), 32)
        self.assertEqual(len(outcome.rounds["Round of 32"]), 16)
        self.assertEqual(len(outcome.rounds["Round of 16"]), 8)
        self.assertEqual(len(outcome.rounds["Quarterfinal"]), 4)
        self.assertEqual(len(outcome.rounds["Semifinal"]), 2)
        self.assertEqual(len(outcome.rounds["Final"]), 1)

    def test_snake_region_assignment_follows_expected_pattern(self):
        teams = generate_teams(8)
        regions = assign_regions_snake(teams, ("A", "B", "C", "D"))

        self.assertEqual([team.seed for team in regions["A"]], [1, 8])
        self.assertEqual([team.seed for team in regions["B"]], [2, 7])
        self.assertEqual([team.seed for team in regions["C"]], [3, 6])
        self.assertEqual([team.seed for team in regions["D"]], [4, 5])

    def test_project_status_reports_done_next_and_playability(self):
        status = get_project_status()

        self.assertTrue(status.playable)
        self.assertIn("auto-simulated tournament", status.playability_note)
        self.assertGreaterEqual(len(status.done), 4)
        self.assertGreaterEqual(len(status.next_steps), 3)


if __name__ == "__main__":
    unittest.main()
