import unittest
from random import Random
from unittest.mock import patch
from pathlib import Path

from global_knockout_cup import (
    Kick,
    KickEvent,
    GlobalKnockoutCup,
    PenaltyShootoutEngine,
    ShootoutResult,
    Team,
    assign_regions_snake,
    generate_teams,
    get_project_status,
    load_nation_dataset,
)
from tournament_featured_mode import run_featured_tournament


class GlobalKnockoutCupTests(unittest.TestCase):
    def test_fifa_nation_dataset_loads_and_validates(self):
        nations = load_nation_dataset()

        self.assertEqual(len(nations), 211)
        self.assertEqual(len({nation.name for nation in nations}), 211)
        self.assertEqual(len({nation.fifa_code for nation in nations}), 211)
        self.assertTrue(all(nation.flag_code == nation.fifa_code for nation in nations))
        self.assertEqual(len({nation.fifa_rank for nation in nations}), 211)
        self.assertTrue(all(nation.is_playable for nation in nations))
        self.assertEqual(nations[0].name, "Argentina")
        self.assertEqual(nations[-1].fifa_rank, 211)

    def test_generate_teams_uses_fifa_names_when_dataset_exists(self):
        teams = generate_teams(8)

        self.assertEqual(len(teams), 8)
        self.assertEqual(teams[0].name, "Argentina")
        self.assertEqual(teams[1].name, "Spain")
        self.assertNotEqual(teams[0].name, "Nation 1")
        self.assertEqual(teams[0].flag_code, "ARG")
        self.assertEqual(teams[0].fifa_rank, 1)
        self.assertGreaterEqual(teams[0].overall_rating, teams[-1].overall_rating)
        self.assertGreaterEqual(teams[0].shooting_rating, teams[-1].shooting_rating)
        self.assertGreaterEqual(teams[0].reaction_rating, teams[-1].reaction_rating)

    def test_generate_teams_falls_back_when_dataset_missing(self):
        missing_path = str(Path(__file__).resolve().parent / "does_not_exist.csv")
        teams = generate_teams(3, nation_dataset_path=missing_path)

        self.assertEqual([team.name for team in teams], ["Nation 1", "Nation 2", "Nation 3"])
        self.assertEqual([team.fifa_rank for team in teams], [1, 2, 3])
        self.assertGreater(teams[0].penalty_strength, teams[-1].penalty_strength)
        self.assertGreater(teams[0].goalkeeper_rating, teams[-1].goalkeeper_rating)

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

    def test_resolve_kick_timing_quality_influences_outcome(self):
        shooter = Team("Shooter", seed=1, penalty_strength=0.5, goalkeeper_rating=0.5)
        keeper = Team("Keeper", seed=2, penalty_strength=0.5, goalkeeper_rating=0.5)
        engine = PenaltyShootoutEngine(Random(11))

        with patch.object(engine.rng, "random", return_value=0.5):
            low_timing_scored = engine.resolve_kick(
                shooter,
                keeper,
                shot_direction="left",
                keeper_dive="left",
                kick_number_for_shooter=1,
                timing_quality=0.0,
            )
            high_timing_scored = engine.resolve_kick(
                shooter,
                keeper,
                shot_direction="left",
                keeper_dive="left",
                kick_number_for_shooter=1,
                timing_quality=1.0,
            )

        self.assertFalse(low_timing_scored)
        self.assertTrue(high_timing_scored)

    def test_shootout_produces_event_stream(self):
        team_a = Team("A", seed=1)
        team_b = Team("B", seed=2)
        engine = PenaltyShootoutEngine(Random(13))

        result = engine.shootout(
            team_a,
            team_b,
            chooser_a=lambda *_: "left",
            chooser_b=lambda *_: "right",
            timing_chooser_a=lambda *_: 0.8,
            timing_chooser_b=lambda *_: 0.2,
        )

        self.assertEqual(len(result.events), len(result.kicks))
        self.assertGreater(len(result.events), 0)
        self.assertIn(result.events[0].phase, ("resolve",))
        self.assertIsNotNone(result.events[0].timing_quality)
        self.assertIn(result.events[-1].score_a, range(0, 11))
        self.assertIn(result.events[-1].score_b, range(0, 11))

    def test_shootout_uses_custom_keeper_dive_choosers(self):
        team_a = Team("A", seed=1)
        team_b = Team("B", seed=2)
        engine = PenaltyShootoutEngine(Random(17))

        result = engine.shootout(
            team_a,
            team_b,
            chooser_a=lambda *_: "left",
            chooser_b=lambda *_: "right",
            dive_chooser_a=lambda *_: "centre",
            dive_chooser_b=lambda *_: "centre",
        )

        self.assertGreaterEqual(len(result.kicks), 6)
        self.assertTrue(all(event.dive_direction == "centre" for event in result.events))

    def test_tournament_plan_and_progression_sizes_match_spec(self):
        cup = GlobalKnockoutCup(rng=Random(2))
        plan = cup.create_tournament_plan()

        self.assertEqual(len(cup.teams), 211)
        self.assertEqual(len(plan.regional_preliminary), 4)
        self.assertEqual(len(plan.regional_byes), 4)

        all_prelim_matches = tuple(m for matches in plan.regional_preliminary.values() for m in matches)
        all_byes = tuple(t for byes in plan.regional_byes.values() for t in byes)
        self.assertEqual(len(all_prelim_matches), 83)
        self.assertEqual(len(all_byes), 45)

        prelim_seeds = {team.seed for match in all_prelim_matches for team in (match.team_a, match.team_b)}
        self.assertEqual(min(prelim_seeds), 46)
        self.assertEqual(max(prelim_seeds), 211)

        # Each region must produce exactly 8 qualifiers (32 total for Phase 2).
        for region_name, region_byes in plan.regional_byes.items():
            prelim_matches = plan.regional_preliminary[region_name]
            r128_size = len(region_byes) + len(prelim_matches)  # prelim winners + byes
            self.assertEqual(r128_size, 32, msg=f"Region {region_name} should have 32 teams entering R128")

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

    def test_featured_tournament_uses_realtime_for_featured_matches(self):
        calls = {"count": 0}

        def fake_featured_match(*_args, **kwargs):
            calls["count"] += 1
            human_team = kwargs["human_team"]
            ai_team = kwargs["ai_team"]
            return ShootoutResult(
                winner=human_team,
                loser=ai_team,
                score_a=1,
                score_b=0,
                kicks=(Kick(human_team, "left", "right", True),),
                events=(
                    KickEvent(
                        team=human_team,
                        phase="resolve",
                        shot_direction="left",
                        dive_direction="right",
                        timing_quality=0.8,
                        scored=True,
                        score_a=1,
                        score_b=0,
                        message="featured test",
                    ),
                ),
            )

        with patch("tournament_featured_mode.play_realtime_match", side_effect=fake_featured_match):
            outcome = run_featured_tournament(featured_seed=1, auto=True, rng_seed=5)

        self.assertEqual(outcome.champion.seed, 1)
        self.assertEqual(calls["count"], 7)

    def test_featured_tournament_invalid_seed_raises(self):
        with self.assertRaises(ValueError):
            run_featured_tournament(featured_seed=999, auto=True, rng_seed=1)


if __name__ == "__main__":
    unittest.main()
