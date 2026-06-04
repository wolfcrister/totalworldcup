# totalworldcup

Minimal MVP tournament simulation for the **Global Knockout Cup** concept.

## Included

- 211 generated national teams with seed, penalty strength, and goalkeeper rating
- Snake-seeded regional assignment across Germany, England/UK, France, and Spain
- Phase 1 knockout flow: Preliminary (166 teams), Round of 128, Round of 64
- Open redraw at the last 32 teams, then fixed rounds to a champion
- Penalty-shootout match engine with:
  - alternating kicks
  - early finish when comeback becomes impossible
  - sudden death after 5-5 kick sets
- Manual control hooks for team shot-direction choice
- Auto-simulated tournament progression

## Run tests

```bash
python -m unittest discover -s tests -q
```
