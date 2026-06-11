from __future__ import annotations

import argparse

from visual_penalty_game import run_visual_match, run_visual_tournament


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple launcher for Total World Cup visual modes.")
    parser.add_argument(
        "--single",
        action="store_true",
        help="Play one visual shootout match.",
    )
    parser.add_argument(
        "--featured-seed",
        type=int,
        default=1,
        help="Seed of the team you control (default: 1).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional RNG seed for reproducible sessions.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.single:
        return run_visual_match(seed=args.seed, featured_seed=args.featured_seed)
    return run_visual_tournament(seed=args.seed, featured_seed=args.featured_seed)


if __name__ == "__main__":
    raise SystemExit(main())
