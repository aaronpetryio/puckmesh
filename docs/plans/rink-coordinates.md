# Plan: adopt the standard PWHL rink-coordinate convention

Status: draft, awaiting review. Separate from the xG work.

## Problem

`int_shots_enriched` turns HockeyTech's 600 × 300 shot grid into feet with a scale we estimated ourselves: net at x = 550, and 2.81 grid units per foot on both axes. That scale has two problems:

- **It makes the rink too wide.** 2.81 units per foot turns the 300-unit width into 107 ft, but a real rink is 85 ft. Shots near the sides end up on, or past, the boards. Example: the shot at raw (466, 269) comes out at 51.8 ft and 54.8°, on the boards. Under the standard convention it's 47.6 ft and 45.0°, in the faceoff circle.
- **It treats the goal-scoring cluster as the goal line.** Goals cluster at x ≈ 550, so we set the goal line there. But goals are scored a few feet in front of the net. Under the standard convention, the goal line is at x ≈ 567.

A smaller problem: we pick each team's attacking side from where most of its shots were that period, then measure every shot to that net. In the ~1.6% of team-periods with shots at both ends, the minority shots get measured to the far net and come out at 150+ ft.

## What other PWHL researchers do

Every published PWHL source that converts coordinates uses the same mapping:

| Source | Grid → feet | Net | Direction |
|---|---|---|---|
| fastRhockey / sportsdataverse-py [1][2] | `x/3 − 100`, `42.5 − y·85/300` (the grid is the whole 200 × 85 ft rink) | ±89 ft | Home attacks x = 0 all game; distance to the **nearer** net; empty-net shots to the attacking net |
| Isabelle Lefebvre's `pwhl-scraper` [4] | `x/600·2400`, `y/300·1020` (the same mapping, in inches) | — | Away games turned 180° |
| sdvplot-js [5] | Same as fastRhockey | — | — |

What's known about accuracy [3][5]:
- The grid is 600 × 300 with a top-left origin and center ice at (300, 150), confirmed across 320 PWHL games. The AHL, OHL and ECHL use the same grid.
- The grid is stylized, not to scale. End-zone faceoff dots convert to ±66.7 and ±52.3 ft instead of the regulation ±69 ft, so converted feet are approximate.
- Our own faceoff query matches theirs exactly: 17 fixed points, symmetric about center, at x = 100/143/203/247/353/397/457/500.

Nobody publishes a better calibration, so we follow the convention, so our numbers can be compared with everyone else's.

## The convention we adopt

1. **Feet from center ice:** `x_ft = x/3 − 100`, `y_ft = 42.5 − y·85/300`. That's 3 units per foot along the rink and 3.53 across it.
2. **Nets at ±89 ft** (the regulation goal line, 11 ft from the end boards).
3. **Which net a shot is measured to:**
   - The nearer net (`x_ft ≥ 0` → +89, else −89).
   - Except empty-net shots (no goalie, not blocked), which go to the net the shooting team attacks: home → −89, away → +89.
4. **Distance:** `sqrt(dx² + y_ft²)`, where `dx` is the distance from the shot to its net along the rink, toward the net.
5. **Angle:** `atan2(|y_ft|, dx)` in degrees, unchanged in meaning: 0 is straight on, 90 is from the goal line, over 90 is from behind the net.

This gives the same distance and angle as fastRhockey's `hockeytech_shot_distance_angle()`.

## Changes

### 1. `transform/dbt_project.yml` vars

- Remove `rink_net_x` and `rink_units_per_foot`.
- Add `rink_length_ft: 200`, `rink_width_ft: 85` and `rink_goal_line_ft: 89`.
- Keep `rink_length_units`, `rink_width_units`, `rink_center_x` and `rink_center_y`.
- Rewrite the comment to name the convention and link [1] and [3], including that the grid is stylized and the feet are approximate.

### 2. `transform/models/intermediate/int_shots_enriched.sql`

- **Remove the `attack_side` CTE.** The nearer-net rule makes the majority-side check unnecessary, and no other source uses it.
- **Rotation:** rotate a shot 180° when its net is the left one. That's when `x_location < rink_center_x`, or, for empty-net shots, when the shooter is the home team. Every shot then attacks the right-hand net, as today.
- **`x_normalized` / `y_normalized`:** still grid units, after the rotation above. The columns and their units stay the same, so this isn't a gold mart column change.
- **`distance_ft` / `angle_deg`:** compute from the normalized grid values converted to feet with the new vars.
  - `dx = rink_goal_line_ft − (x_normalized / units_per_ft_x − rink_length_ft / 2)`
  - `y_ft = (y_normalized − rink_center_y) / units_per_ft_y`
  - Comments above the non-obvious bits: the nearer-net rule, the empty-net exception, and why the axes have different scales.
- **Why the logic stays in this model:** the geometry is enrichment, which is what intermediate models are for. Marts and future models read the result from one place.

### 3. Tests

- **dbt unit tests** on `int_shots_enriched`, in `_intermediate__models.yml`. They mock `stg_pwhl__shots`, `stg_pwhl__goals` and `stg_pwhl__games` and lock in the formulas. dbt 1.10 supports them. Unit tests check SQL logic against hand-worked inputs, which data tests can't do.

  | Case | Raw (x, y) | Shooter | Expected distance / angle |
  |---|---|---|---|
  | Away shot, faceoff circle (the example above) | (466, 269) | away, goalie in net | 47.6 ft / 45.0° |
  | The same spot from the other end | (134, 31) | home, goalie in net | 47.6 ft / 45.0° |
  | From behind the net | (590, 120) | away, goalie in net | 11.4 ft / 132.0° |
  | Empty-net shot from its own half | (450, 150) | home, no goalie | 139.0 ft / 0.0° |
  | Center ice | (300, 150) | away, goalie in net | 89.0 ft / 0.0° |

- **Data tests:**
  - Keep the range tests on `distance_ft` and `angle_deg`.
  - Add a tighter range test for shots with a goalie in net: they can never be more than ~98.6 ft from the nearer net (`sqrt(89² + 42.5²)`). Use `dbt_utils.accepted_range` with a `where` config and a 99 ft maximum.

### 4. Documentation

- Update the descriptions that mention `rink_net_x` or "approximate scale": `_intermediate__models.yml` (model, `distance_ft`, `angle_deg`) and `_marts__models.yml` (`x_normalized`, `distance_ft`, `angle_deg`).
- Add a row to the README decision log: "Rink coordinates follow the fastRhockey / sportsdataverse convention", with the reason (comparability; no better calibration exists) and when to revisit (HockeyTech publishes a scale, or someone calibrates one).

## Verification

**Without a warehouse** (cloud session): `pre-commit run --all-files` and `python -m pytest`.

**With a warehouse** (run locally):

1. `dotenv -f ../.env run -- dbt build --select int_shots_enriched+` builds the model, `fct_shots`, and their tests, including the unit tests.
2. Spot-check the example shot: raw (466, 269) should now read 47.6 ft and 45.0°.
3. Before and after, compare the goal-rate-by-distance curve. Goals should fall off smoothly with distance, with no pile-up at 150+ ft.
4. Optional cross-check against fastRhockey's published per-shot `shot_distance` for two or three games [6]. This is a one-off manual check, not a new dependency.

## Out of scope

- The xG model and its plan (on `claude/modest-feynman-1c94al`).
- Power-play strength state, and whether `is_quality_chance` gives away the outcome.
- Converting `x_normalized` / `y_normalized` to feet, or adding feet columns. That would change gold mart columns, so it needs a separate ask.
- Using faceoff coordinates to calibrate the scale. They're fixed marker positions, not true geometry.

## Open questions

1. Keep `x_normalized` / `y_normalized` in grid units (recommended, no mart change), or switch the mart to feet coordinates as a separate change?
2. Is the 99 ft maximum for shots with a goalie in net right, or should it warn instead of fail at first?

## Sources

1. fastRhockey `R/hockeytech_analytics.R` (grid → feet, nearer-net distance, empty-net rule): <https://github.com/sportsdataverse/fastRhockey/blob/main/R/hockeytech_analytics.R>
2. sportsdataverse-py `hockeytech/_analytics.py` (Python port): <https://github.com/sportsdataverse/sportsdataverse-py/blob/main/sportsdataverse/hockeytech/_analytics.py>
3. fastRhockey PR #73, "raw coordinates are on a 600x300 canvas" (probe across 320 PWHL games and other leagues, faceoff grid): <https://github.com/sportsdataverse/fastRhockey/pull/73>. See also PR #75, the rotation fix: <https://github.com/sportsdataverse/fastRhockey/pull/75>
4. IsabelleLefebvre97/pwhl-scraper (goal heatmap example, 600 → 2400 in, 300 → 1020 in): <https://github.com/IsabelleLefebvre97/pwhl-scraper>
5. sdvplot-js PR #31 (canvas is stylized; end-zone dots at ±66.7 and ±52.3 ft): <https://github.com/sportsdataverse/sdvplot-js/pull/31>
6. fastRhockey release notes (`load_pwhl_xg_pbp()`, per-shot distances): <https://cran.nics.utk.edu/cran/web/packages/fastRhockey/news/news.html>
7. sportsdataverse-py PR #729 (empty-net shots measured to the attacking net): <https://github.com/sportsdataverse/sportsdataverse-py/pull/729>

Caveat: [3] and [5] were merged without human review, and the "validated on 320 PWHL games" note for the nearer-net rule points to an internal doc that isn't public.
