# Plan: adopt the standard PWHL rink-coordinate convention

Status: draft, awaiting review. Separate from the xG work.

## Problem

`int_shots_enriched` turns HockeyTech's 600 × 300 shot grid into feet with a scale we estimated ourselves: net at x = 550, and 2.81 grid units per foot on both axes. That scale has two problems:

- **It makes the rink too wide.** 2.81 units per foot turns the 300-unit width into 107 ft, but a real rink is 85 ft. Shots near the sides end up on, or past, the boards. Example: the shot at raw (466, 269) comes out at 51.8 ft and 54.8°, on the boards. Under the standard convention it's 47.6 ft and 45.0°, in the faceoff circle.
- **It treats the goal-scoring cluster as the goal line.** Goals cluster at x ≈ 550, so we set the goal line there. But goals are scored a few feet in front of the net. Under the standard convention, the goal line is at x ≈ 567.

A smaller problem: we pick each team's attacking side from where most of its shots were that period, then measure every shot to that net. In the ~1.6% of team-periods with shots at both ends, the minority shots get measured to the far net and come out at 150+ ft.

On top of the geometry, the mart gives shot positions only in grid units (`x_normalized` / `y_normalized`). The grid isn't to scale, so those can't be drawn on a rink as-is. We want shots we can plot.

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
   - Except empty-net shots (no goalie, not blocked). A team shooting from its own end at an empty net is shooting at the far net, so these go to the net the shooting team attacks. Which net that is depends on step 0 below.
4. **Rotation:** shots measured to the −89 net are rotated 180° (`x → −x`, `y → −y`), so every shot attacks the +89 net. It's a rotation, not a mirror, so the shooter's left stays on the left.
5. **Distance:** `sqrt((89 − x_ft)² + y_ft²)`, using the rotated `x_ft` and `y_ft`.
6. **Angle:** `atan2(|y_ft|, 89 − x_ft)` in degrees, unchanged in meaning: 0 is straight on, 90 is from the goal line, over 90 is from behind the net.

This gives the same distance and angle as fastRhockey's `hockeytech_shot_distance_angle()`.

## Step 0: check that home teams always attack left

fastRhockey assumes the home team attacks the left net (x < 300) in every period, at every rink. Its evidence is an internal doc that isn't public. Our own data partly backs it up: `int_shots_enriched` already notes that home shots are mostly drawn toward the left net, but about 1.6% of team-periods are mixed. HockeyTech data is entered by scorers at each arena, so a rink, a season or a period could follow a different habit.

Under this plan the assumption only matters for empty-net shots. Every other shot uses the nearer net. Still, check it before relying on it.

**Query 1: how often the rule holds, by rink, season and period.** Shots with a goalie in net only, since empty-net shots can legitimately come from the far end. Expect high but not 100% agreement: some real shots come from beyond center ice.

```sql
with shots as (
    select
        game_id,
        period,
        is_home_team,
        x_location
    from <your_dev_schema>.stg_pwhl__shots
    where shot_result != 'blocked'
        and goalie_player_id is not null
),

games as (
    select
        game_id,
        season_id,
        venue_id
    from <your_dev_schema>.stg_pwhl__games
),

checked as (
    select
        games.venue_id,
        games.season_id,
        shots.period,
        (shots.x_location < 300) = shots.is_home_team as is_on_expected_side
    from shots
    inner join games on shots.game_id = games.game_id
)

select
    venue_id,
    season_id,
    period,
    count(*) as shots,
    round(avg(case when is_on_expected_side then 1.0 else 0.0 end), 3) as share_on_expected_side
from checked
group by venue_id, season_id, period
order by share_on_expected_side
```

**Query 2: game-periods where the rule is reversed.** If the home team is mostly on the right in a period, the rule failed there and isn't just noise.

```sql
with shots as (
    select
        game_id,
        period,
        x_location
    from <your_dev_schema>.stg_pwhl__shots
    where shot_result != 'blocked'
        and goalie_player_id is not null
        and is_home_team
),

by_period as (
    select
        game_id,
        period,
        count(*) as home_shots,
        avg(case when x_location < 300 then 1.0 else 0.0 end) as share_left
    from shots
    group by game_id, period
)

select *
from by_period
where share_left < 0.5
order by game_id, period
```

**What we do with the answer:**
- **If the rule holds everywhere:** query 1 near 1.0 for every rink, season and period, and query 2 empty or a few one-offs. Then empty-net shots use home → −89, away → +89, as fastRhockey does.
- **If it fails somewhere** (a rink, a season, or whole periods): empty-net shots use the side the same team attacked in that game-period, taken from its shots with a goalie in net. That's today's `attack_side` logic, kept only for this case. Fall back to home/away when there aren't any.

## Changes

### 1. `transform/dbt_project.yml` vars

- Remove `rink_net_x` and `rink_units_per_foot`.
- Add `rink_length_ft: 200`, `rink_width_ft: 85` and `rink_goal_line_ft: 89`.
- Keep `rink_length_units`, `rink_width_units`, `rink_center_x` and `rink_center_y`.
- Rewrite the comment to name the convention and link [1] and [3], including that the grid is stylized and the feet are approximate.

### 2. `transform/models/intermediate/int_shots_enriched.sql`

- **`attack_side` CTE:** remove it, or keep it only for empty-net shots, depending on step 0.
- **New columns `x_ft` / `y_ft`:** the shot position in feet from center ice, rotated so every shot attacks the net at +89 ft. Positive `y_ft` is the top of HockeyTech's grid, as in fastRhockey.
- **`distance_ft` / `angle_deg`:** computed from `x_ft` and `y_ft`.
- **Drop `x_normalized` / `y_normalized`.** `x_ft` / `y_ft` replace them, and `x_location` / `y_location` keep the raw grid values.
- Comments above the non-obvious bits: the nearer-net rule, the empty-net exception, and why the two axes have different scales.
- **Why the logic stays in this model:** the geometry is enrichment, which is what intermediate models are for. Marts and future models read the result from one place.

### 3. `transform/models/marts/fct_shots.sql`

**Gold mart column change, approved.** `x_normalized` / `y_normalized` become `x_ft` / `y_ft`. Same grain, same everything else.

**Why feet for plotting:**
- Rink-drawing tools work in feet with center ice at (0, 0) and the nets at ±89: sportyR in R, `hockey-rink` in Python, or a hand-drawn rink on the website. Feet columns line up with them as-is.
- Grid units are stretched (2:1 instead of the rink's 2.35:1), so they plot slightly off.

### 4. Tests

- **dbt unit tests** on `int_shots_enriched`, in `_intermediate__models.yml`. They mock `stg_pwhl__shots`, `stg_pwhl__goals` and `stg_pwhl__games` and lock in the formulas. dbt 1.10 supports them. Unit tests check SQL logic against hand-worked inputs, which data tests can't do.

  | Case | Raw (x, y) | Shooter | Expected x_ft, y_ft | Expected distance / angle |
  |---|---|---|---|---|
  | Away shot, faceoff circle (the example above) | (466, 269) | away, goalie in net | 55.3, −33.7 | 47.6 ft / 45.0° |
  | The same spot from the other end | (134, 31) | home, goalie in net | 55.3, −33.7 | 47.6 ft / 45.0° |
  | From behind the net | (590, 120) | away, goalie in net | 96.7, 8.5 | 11.4 ft / 132.0° |
  | Empty-net shot from its own half | (450, 150) | home, no goalie | −50.0, 0.0 | 139.0 ft / 0.0° |
  | Center ice | (300, 150) | away, goalie in net | 0.0, 0.0 | 89.0 ft / 0.0° |

  The empty-net case assumes the home/away rule. If step 0 sends us to the per-period rule, its fixture needs other shots by the same team in that period.

- **Data tests:**
  - Keep the range tests on `distance_ft` and `angle_deg`.
  - Add ranges on `x_ft` (−100 to 100) and `y_ft` (−42.5 to 42.5): every shot inside the rink.
  - Add a tighter range test for shots with a goalie in net: they can never be more than ~98.6 ft from the nearer net (`sqrt(89² + 42.5²)`). Use `dbt_utils.accepted_range` with a `where` config and a 99 ft maximum.

### 5. Documentation

- Update the descriptions that mention `rink_net_x` or "approximate scale" in `_intermediate__models.yml`.
- In `_marts__models.yml`, replace the `x_normalized` / `y_normalized` entries with `x_ft` / `y_ft`. Say that they're approximate feet from center ice, that the attacking net is at +89, and that they're ready to plot on a standard rink.
- Add a row to the README decision log: "Rink coordinates follow the fastRhockey / sportsdataverse convention", with the reason (comparability; no better calibration exists) and when to revisit (HockeyTech publishes a scale, or someone calibrates one).

## Verification

**Without a warehouse** (cloud session): `pre-commit run --all-files` and `python -m pytest`.

**With a warehouse** (run locally):

1. Step 0's two queries, before the change.
2. `dotenv -f ../.env run -- dbt build --select int_shots_enriched+` builds the model, `fct_shots`, and their tests, including the unit tests.
3. Spot-check the example shot: raw (466, 269) should now read x_ft 55.3, y_ft −33.7, 47.6 ft and 45.0°.
4. Plot a season's goals using `x_ft` / `y_ft` on a standard rink. They should cluster in front of the +89 net.
5. Before and after, compare the goal-rate-by-distance curve. Goals should fall off smoothly with distance, with no pile-up at 150+ ft.
6. Optional cross-check against fastRhockey's published per-shot `shot_distance` for two or three games [6]. This is a one-off manual check, not a new dependency.

## Out of scope

- The xG model and its plan (on `claude/modest-feynman-1c94al`).
- Power-play strength state, and whether `is_quality_chance` gives away the outcome.
- Using faceoff coordinates to calibrate the scale. They're fixed marker positions, not true geometry.
- Feet coordinates for other events (hits, faceoffs, penalties). Shots only for now.

## Open questions

1. Is the 99 ft maximum for shots with a goalie in net right, or should it warn instead of fail at first?

## Sources

1. fastRhockey `R/hockeytech_analytics.R` (grid → feet, nearer-net distance, empty-net rule): <https://github.com/sportsdataverse/fastRhockey/blob/main/R/hockeytech_analytics.R>
2. sportsdataverse-py `hockeytech/_analytics.py` (Python port): <https://github.com/sportsdataverse/sportsdataverse-py/blob/main/sportsdataverse/hockeytech/_analytics.py>
3. fastRhockey PR #73, "raw coordinates are on a 600x300 canvas" (probe across 320 PWHL games and other leagues, faceoff grid): <https://github.com/sportsdataverse/fastRhockey/pull/73>. See also PR #75, the rotation fix: <https://github.com/sportsdataverse/fastRhockey/pull/75>
4. IsabelleLefebvre97/pwhl-scraper (goal heatmap example, 600 → 2400 in, 300 → 1020 in): <https://github.com/IsabelleLefebvre97/pwhl-scraper>
5. sdvplot-js PR #31 (canvas is stylized; end-zone dots at ±66.7 and ±52.3 ft): <https://github.com/sportsdataverse/sdvplot-js/pull/31>
6. fastRhockey release notes (`load_pwhl_xg_pbp()`, per-shot distances): <https://cran.nics.utk.edu/cran/web/packages/fastRhockey/news/news.html>
7. sportsdataverse-py PR #729 (empty-net shots measured to the attacking net): <https://github.com/sportsdataverse/sportsdataverse-py/pull/729>

Caveat: [3] and [5] were merged without human review, and the "validated on 320 PWHL games" note for the nearer-net rule points to an internal doc that isn't public.
