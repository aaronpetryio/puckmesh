# Plan: PWHL metrics on top of xG

Status: plan signed off. Steps 1–2 (GSAx, finishing) merged; validation query not yet run.
Steps 3–5 built (PR C), waiting on CI; 6–8 to come. See [Decisions](#decisions) for
what needs a yes before each step starts.

Eight metric groups, built in order, each on the ones before it:

1. GSAx (goals saved above expected)
2. Finishing (goals minus xG), raw and shrunk
3. Team shot share, xG share, quality-chance share, raw and score-and-venue adjusted
4. Special teams per 2 minutes
5. PDO and luck
6. Field tilt
7. Team rating (Elo) and season simulation
8. In-game win probability

Groups 1–6 are dbt. Groups 7–8 are Python in a new `ml/forecast/` package, published to
tables the same way `ml/xg/publish.py` does.

## What the data allows (and what we name honestly)

- **xG is for shots on goal only.** The feed has no missed shots, and blocked shots have no
  xG. Shot share uses **shots on goal + blocked**. `fct_games` already calls that
  `shot_attempts` and says in its description that misses aren't recorded; the new models
  reuse that name and description. Nothing is called Corsi or Fenwick.
- **No shifts or ice time.** On-ice skaters are listed only on goals. So everything below is
  per goalie, per shooter, or per team. No individual on-ice share, per-60s, or RAPM.
- **xG covers regular season and playoffs only** (preseason isn't scored; xg-model.md,
  step 3). Every new model leaves preseason out.
- **Unscored shots.** During the season, shots wait for the next scoring run to get xG. Every
  xG-based count below uses only shots that have xG, so goals and xG always cover the same
  shots and GSAx is never skewed by a shot that is counted but not yet scored.
- **Small samples.** Seasons so far: 72, 90 and 120 regular-season games (6, 6 and 8 teams).
  2026-27 adds four expansion teams (12 teams, two conferences). About 30 games per team per
  season. Simple methods, shrinkage, and as few tuned parameters as possible.

## Reused, not re-derived

| Need | Source |
|---|---|
| xG, goals, shots on goal, blocked, quality flag, score state, home/away | `fct_shots` |
| Empty net on goals | `fct_shots.is_empty_net` |
| Skaters per side, penalty timing | `int_shots_enriched`, `int_penalties_timed` |
| Results, OT, shootouts | `fct_games` (`decision`, `winning_team_id`) |
| Attacking side per team per period | `int_shots_enriched`'s `attack_side` CTE (moved into its own model in step 6) |
| Position group, team per season | `fct_player_team_seasons`, `dim_players` |

## Model map

New gold marts (sign-off needed), new intermediate views, and gold columns added to existing
marts. Situations are `all`, `ev`, `pp`, `pk`, always from the row's team's side.

| Model | Layer | Grain | Step | Built by |
|---|---|---|---|---|
| `fct_goalie_games` | mart (new) | goalie × game | 1 | dbt |
| `int_finishing_priors_estimated` | intermediate | position group | 2 | dbt |
| `fct_player_seasons` | mart (new) | player × season | 1, 2 | dbt |
| `fct_player_careers` | mart (new) | player × season type | 1, 2 | dbt |
| `fct_shots.strength_group` | mart (new column) | shot | 3 | dbt |
| `int_score_venue_weights_estimated` | intermediate | score state × venue × situation × measure | 3 | dbt |
| `fct_team_game_situations` | mart (new) | team × game × situation | 3–6 | dbt |
| `fct_team_season_situations` | mart (new) | team × season × situation | 3–6 | dbt |
| `int_strength_intervals_derived` | intermediate | game × stretch of constant manpower | 4 | dbt |
| `int_attack_sides_inferred` | intermediate | game × period × team | 6 | dbt (moved out of `int_shots_enriched`) |
| `int_zone_events_located` | intermediate | play-by-play event | 6 | dbt |
| `ml.team_ratings` → `stg_ml__team_ratings` → `fct_games` (new columns) | source / mart | team × game | 7 | Python |
| `ml.season_projections` → `fct_team_season_projections` | source / mart (new) | team × season × as-of date | 7 | Python |
| `ml.win_probabilities` → `fct_game_win_probabilities` | source / mart (new) | game × moment | 8 | Python |

Why this many and not fewer or more:
- **One mart per grain, not per metric.** GSAx and finishing share a player-season grain, so
  they share `fct_player_seasons`. Shot share, special teams, PDO, luck and field tilt are all
  team × game, so they share `fct_team_game_situations`.
- **Situations are rows, not column suffixes.** A wide team-game row with every measure × for/
  against × four situations would be ~60 columns. As rows, one set of columns (`xg_for`,
  `xg_for_per_2_min`, ...) works for every situation. Special teams then need no columns of
  their own: power-play xG per 2 minutes is `xg_for_per_2_min` on the `pp` row. A PK row's
  `*_for` columns are the shorthanded chances generated.
- **Season and career marts exist because the shrunk numbers can't be summed.** Raw season
  GSAx is a sum of games, but shrunk finishing has to be computed on the season's totals.
  Shares and rates likewise have to be recomputed from summed counts, not averaged.
- **Python outputs get thin marts** so the website still reads gold only (README).

## Step 1: GSAx

**`fct_goalie_games`**: one row per goalie per game played: started, came in, or faced a
shot. Regular season and playoffs.

| Column | Meaning |
|---|---|
| `league_id`, `game_id`, `player_id` | keys (`player_id` → `dim_players`) |
| `season_id`, `season_type`, `game_date` | |
| `team_id`, `opponent_team_id`, `is_home_team` | |
| `is_starter` | in net at 0:00 (`stg_pwhl__goalie_changes`) |
| `shots_faced` | shots on goal at this goalie that have xG (no empty-net goals, penalty shots or shootout attempts) |
| `goals_allowed` | goals among those shots |
| `xg_faced` | sum of xG on those shots |
| `gsax` | `xg_faced - goals_allowed`. Positive is good |
| `gsax_per_100_shots` | `100 * gsax / shots_faced`. Per 100 rather than per shot because per-shot values are like 0.008, hard to read. Same number scaled |

Season and career columns are on `fct_player_seasons` and `fct_player_careers` (step 2).

- **Who the shot counts against:** `fct_shots.goalie_player_id`, the goalie named on the
  shot. A mid-game change splits a game between two goalies.
- **Rescaled xG:** GSAx uses the published (rescaled) xG, per xg-model.md decision 5, so a
  league-wide shift in goal rate doesn't make every goalie look better or worse.

Tests:
- Grain: `unique_combination_of_columns [game_id, player_id]`; `relationships` on
  `player_id`, `game_id`, `team_id`.
- `assert_goalie_gsax_matches_team_xg.sql`: per team-game, summed goalie GSAx equals the
  team's xG against minus goals against on shots at a goalie, from `fct_shots`.
- `assert_goalie_shots_match_shots.sql`: summed `shots_faced` per game equals the game's
  scored shots at a goalie (catches goalies dropped by the join).

## Step 2: Finishing (goals minus xG), with shrinkage

On `fct_player_seasons` (one row per player per season, regular season and playoffs) and
`fct_player_careers` (one row per player per season type: career regular season, career
playoffs). Rows exist for anyone with a shot at a goalie or a goalie game.

| Column | Meaning |
|---|---|
| `league_id`, `player_id`, `season_id`, `season_type` | keys (careers: no `season_id`, plus `seasons_played`) |
| `position_group` | F / D / G, as of that season (latest for careers) |
| `shots_on_goal` | the player's shots at a goalie with xG |
| `goals` | goals on those shots (no empty-net goals) |
| `xg` | sum of xG |
| `goals_above_expected` | `goals - xg` |
| `goals_above_expected_shrunk` | regressed toward the position group's average; see below |
| `shrinkage_weight` | `xg / (xg + prior_xg)`: how much of the player's own record the shrunk value keeps, 0 to 1 |
| `goalie_games`, `shots_faced`, `goals_allowed`, `xg_faced`, `gsax`, `gsax_per_100_shots` | goaltending; null for skaters |
| `gsax_shrunk`, `goalie_shrinkage_weight` | GSAx regressed toward an average goalie, the same way; null for skaters |

**Shrinkage method: gamma-Poisson empirical Bayes (Bühlmann credibility).**
- Model: each shooter has a finishing multiplier θ (goals per xG). Goals ~ Poisson(θ · xG).
  Across shooters, θ varies around the group average m with variance τ².
- Best estimate of θ for a shooter with G goals on X xG:
  θ̂ = (α·m + G) / (α + X), with α = 1/τ².
  Shrunk goals above expected = X · (θ̂ − 1).
- In words: **add α expected goals of league-average finishing to every shooter's record.**
  A shooter with α xG of their own gets half weight on their own record. α is the
  "stabilization point" in xG.
- **α from the data, not tuned by hand (method of moments).** If θ didn't vary, (G − X)² would
  average X (Poisson noise). The excess is true skill:
  τ² = (Σ(G − X)² − ΣX) / ΣX², summed over regular-season player-seasons. If that comes out
  ≤ 0, the data can't tell shooters apart and everyone is shrunk fully to the average. One
  `select` in SQL, no new dependency.
- **Shrink toward the position group (F or D), not the whole league.** Forwards and
  defenders finish differently against pooled xG, so each is shrunk toward its own average.
  m and α are both estimated per group, over all its regular-season player-seasons.
  - *Correction, after the first run:* this plan first said defenders *beat* pooled xG,
    from three defenders in the xG plan's top 15. As a group they score about 8% *below* xG
    (m = 0.92, below). The top-15 defenders were the lucky ones. Shrinking toward the group
    still holds, and matters more: shrinking toward the league's 1.04 would overrate every
    defender.
- **Careers use the same m and α** on career totals. Under the model, skill is fixed, so the
  same formula applies to a bigger sample. That's why careers are their own mart.
- **Why not beta-binomial on shooting %:** it ignores shot quality, which is the point of
  the metric. **Why not a mixed model:** same answer, more machinery, a new dependency.

**Goalies get the same treatment.** Save percentage is at least as noisy as finishing, and
shrinking shooters but not goalies would be inconsistent.
- Each goalie has a multiplier φ (goals allowed per xG faced). Goals allowed ~ Poisson(φ ·
  xG faced).
- φ̂ = (α_G + goals allowed) / (α_G + xG faced), and `gsax_shrunk` = xG faced · (1 − φ̂).
- α_G comes from the same method-of-moments formula, over regular-season goalie-seasons.
  The prior is the average goalie: m_G = pooled goals allowed / xG faced, which rescaled xG
  keeps close to 1.
- Same validation as shooters: does shrunk season-N GSAx per shot predict season N+1 better
  than raw?
- Caveat: there are few goalie-seasons (step 5 of the xG plan had 11 goalies with 500+
  shots), so α_G is estimated less precisely than the shooters' α. The run reports it, and
  the step 2 validation checks it.

`int_finishing_priors_estimated` holds the prior per group, one row each: F and D (shooting,
mean m and α) and G (goaltending, α_G). The numbers are visible and tested, and the season
and career marts read the same values.

Validation (reported here once run): does this season's shrunk estimate predict next
season's goals above expected better than the raw one, or than predicting zero?
- For each player with regular-season shots (or games in net) in two consecutive regular
  seasons, the prediction for season N+1 is next season's xG × (season N's multiplier − 1).
- Lower mean squared error wins. Shrinkage should beat raw clearly; if raw wins, α is wrong.
- **Caveat:** α and m are estimated on every season, season N+1 included, so this check
  is slightly optimistic. With three seasons there is no clean way around that.

Run in the SQL editor, with `<gold>` / `<silver>` replaced by your schemas
(e.g. `dev.dbt_apetry_gold`):

```sql
with regular_seasons as (
    select
        season_id,
        row_number() over (order by start_date) as season_number
    from <silver>.stg_pwhl__seasons
    where season_type = 'regular'
),

player_seasons as (
    select
        player_seasons.*,
        regular_seasons.season_number
    from <gold>.fct_player_seasons as player_seasons
    inner join regular_seasons on player_seasons.season_id = regular_seasons.season_id
),

pairs as (
    -- Multipliers on xG: goals per xG for shooters, goals allowed per xG faced for goalies.
    select
        'shooters' as kind,
        this_season.goals / this_season.xg as raw_multiplier,
        1 + this_season.goals_above_expected_shrunk / this_season.xg as shrunk_multiplier,
        next_season.xg as next_xg,
        next_season.goals - next_season.xg as next_above_expected
    from player_seasons as this_season
    inner join player_seasons as next_season
        on this_season.player_id = next_season.player_id
        and this_season.season_number + 1 = next_season.season_number
    where
        this_season.position_group in ('F', 'D')
        and this_season.xg > 0
        and next_season.xg > 0

    union all

    select
        'goalies' as kind,
        this_season.goals_allowed / this_season.xg_faced as raw_multiplier,
        1 - this_season.gsax_shrunk / this_season.xg_faced as shrunk_multiplier,
        next_season.xg_faced as next_xg,
        next_season.goals_allowed - next_season.xg_faced as next_above_expected
    from player_seasons as this_season
    inner join player_seasons as next_season
        on this_season.player_id = next_season.player_id
        and this_season.season_number + 1 = next_season.season_number
    where
        this_season.xg_faced > 0
        and next_season.xg_faced > 0
)

select
    kind,
    count(*) as player_pairs,
    avg(power(next_above_expected, 2)) as mse_predict_zero,
    avg(power(next_above_expected - next_xg * (raw_multiplier - 1), 2)) as mse_predict_raw,
    avg(power(next_above_expected - next_xg * (shrunk_multiplier - 1), 2)) as mse_predict_shrunk
from pairs
group by kind
```

For goalies the "above expected" here is goals allowed minus xG faced, i.e. −GSAx. The sign
doesn't matter for squared error.

**Results** (dev, after PR #21; lower is better):

The priors, from `int_finishing_priors_estimated`:

| Group | Player-seasons | m (goals per xG) | τ² | prior_xg (α) |
|---|---|---|---|---|
| F | 294 | 1.040 | 0.0349 | 29.8 |
| D | 150 | 0.923 | −0.0054 | null: shrunk fully to m |
| G | 49 | 1.019 | 0.0064 | 160.4 |

Next-season prediction:

| Kind | Pairs | MSE, predict 0 | MSE, raw | MSE, shrunk |
|---|---|---|---|---|
| Shooters | 216 | 4.33 | 7.71 | **4.14** |
| Goalies | 23 | 55.9 | **49.4** | 54.4 |

- **Shooters: shrinkage works.** Copying last season's raw finishing is much worse than
  predicting zero, because one season is mostly luck. Shrunk is best, about 5% better than
  zero. Real finishing skill exists among forwards, but it's a weak signal: a forward needs
  about 30 xG of her own before her record counts as much as the average.
- **Defenders: no detectable finishing skill.** τ² is negative, so every defender's shrunk
  value is just the group's −8%. The site should show defenders' raw goals above expected,
  with that note, rather than a shrunk number that carries no individual information.
- **Goalies: raw wins, so α_G looks too large, but only 23 pairs.** The method-of-moments
  estimate weights goalie-seasons by workload already, so backups aren't the cause. A
  likely one: team defense that xG doesn't see (screens, passes), which persists year to
  year with the same goalie and makes raw GSAx repeat without it being her skill.
  - **Decision:** keep the method. Choosing α_G to win this 23-pair check would fit noise.
  - The site shows raw and shrunk GSAx side by side, noting that goalie shrinkage is
    uncertain at this sample size.
  - Re-run this check after 2026-27, which adds a season of pairs.

Tests:
- Grain on both marts.
- `assert_player_seasons_sum_to_careers.sql`: career counts equal the summed seasons.
- `assert_player_seasons_match_shots.sql`: per season, shooting totals equal `fct_shots`
  and goaltending totals equal `fct_goalie_games`.
- `shrinkage_weight` and `goalie_shrinkage_weight` in [0, 1]; every prior α > 0.
- Unit tests: the method-of-moments estimate (`int_finishing_priors_estimated`) and the
  shrinkage formula (`fct_player_seasons`), both on hand-worked rows.

## Step 3: Team shot share, xG share, quality-chance share

**New column `fct_shots.strength_group`**, from the shooting team's side:
- `en` when either net is empty (a pulled goalie), from the pull logic already in
  `int_shots_enriched`.
- Otherwise by **penalty-only** skater counts: `ev` equal, `pp` more, `pk` fewer.
- Why not reuse `strength_state`: it counts the pulled goalie as a skater, so a team on the
  penalty kill that pulls its goalie reads as 5v5. `int_shots_enriched` already has the
  penalty counts; it just doesn't output them.

**`fct_team_game_situations`**: one row per team per game per situation (`all`, `ev`, `pp`,
`pk`). `all` includes everything, empty-net time too; `ev`/`pp`/`pk` leave out shots
with a net empty, so they don't add up to `all`. A team's `pp` row mirrors its opponent's
`pk` row.

| Column | Meaning |
|---|---|
| `league_id`, `game_id`, `team_id`, `situation` | keys |
| `season_id`, `season_type`, `game_date`, `opponent_team_id`, `is_home_team` | |
| `situation_seconds` | time in the situation (step 4); game length for `all`. Not `seconds`, a SQL keyword |
| `shots_on_goal_for` / `_against` | |
| `shot_attempts_for` / `_against` | shots on goal + blocked. Not Corsi: no missed shots |
| `xg_for` / `_against` | |
| `quality_chances_for` / `_against` | shot attempts the league flags `is_quality_chance` (its own location zone; xg-audit.md, 4a) |
| `goals_for` / `_against` | |
| `shots_on_goal_share`, `shot_attempts_share`, `xg_share`, `quality_chance_share` | for / (for + against). Null when both are 0 |
| `*_for_adjusted`, `*_against_adjusted`, `*_share_adjusted` | score-and-venue adjusted, for the same four measures; `ev` and `all` rows only |

**Score-and-venue adjustment (McCurdy's method).**
- Trailing teams shoot more and home teams shoot slightly more. Those effects aren't team
  quality, so raw share flatters teams that trail a lot.
- For each home score state (home trailing 2+, trailing 1, tied, leading 1, leading 2+),
  situation and measure, p = the home team's share of events in that state, across the
  league. The away team's share in the mirrored state is 1 − p ("home up 1" and "away down
  1" are the same moment), so five numbers per situation and measure cover both venues.
- Each event for counts 0.5 / p; each event against counts 0.5 / (1 − p). An average team
  then has an adjusted share of 0.5 in every state.
- Five states, ~4,000 shot attempts each at even strength. Leads of 2+ are pooled because
  3+ goal states are too rare to estimate alone.
- **Neutral sites** (`fct_games.is_neutral_site`, below): no venue effect, so a team's
  expected share is the average of the home and away shares for its score state, which
  leaves only the score adjustment. Neutral games are left out when estimating p.
- **Built as** `int_score_venue_weights_estimated`: one row per situation (`all`, `ev`),
  shooting team's venue (home, away, neutral) and its own score state, with the expected
  share and the weight (0.5 / share) per measure. The mart needs one join per situation,
  and the arithmetic is unit-tested in one place.
- Weights are pooled over all seasons, regular season and playoffs, in
  `int_score_venue_weights_estimated`. Trade-off: a new game slightly changes every past
  adjusted value. Per-season weights would avoid that but have ~5× fewer events per cell.
- **Only `ev` and `all`.** On a power play, time spent there itself depends on the score
  (trailing teams draw more penalties), and PP shares are ~85/15 by design, so an
  adjustment is hard to interpret. `pp`/`pk` adjusted columns are null.

**Neutral sites: new column `fct_games.is_neutral_site`.** The PWHL plays Takeover Tour
games in cities without a team, where one team is listed as home. That team keeps last
change (a rule), but loses the crowd, travel and familiarity, and the off-ice officials
aren't its own.
- **Detection from data we already have:** `stg_pwhl__games.venue_id`. A game is neutral when
  at least `neutral_site_min_home_teams` (2) teams play regular-season or playoff home
  games at its venue that season year.
  - **Why this rule, not the first one.** The first version called a venue neutral when it
    hosted fewer than 3 of the home team's games. CI warned on 35 venues, and the list
    (2024–2027) showed why:
    - Toronto, Montréal and Vancouver each play a game or two a year at a second arena in
      their own city (venues 13, 15, 19 and 27). Those are home games, and the old rule
      called them neutral.
    - Real Takeover Tour stops usually host several teams in a season (venues 9, 23, 32
      and 33 in 2026).
    - The league's "to be announced" Takeover arenas share one venue ID (10), with two
      games each for eight teams in 2026-27.
  - **Known gap:** a one-off Takeover game that hosts a single team counts as home. That's
    roughly one game per team per season, and the venue part of the adjustment is small,
    so it's the better mistake to make than calling second arenas neutral.
  - Only regular-season and playoff games decide which venues are shared, so preseason
    games at practice rinks and college arenas don't count.
- **Built as** `int_game_venues_classified`: one row per game. `fct_games` and the
  score-and-venue weights both read it, so the rule lives in one place.
- **Upgrade if precision matters later:** stage the schedule's venue name, if the raw JSON
  has one, or keep a small seed of Takeover Tour venues.
- Used in step 3 (weights above), step 7 (no home-ice term at neutral sites), and step 8
  (through the pregame rating gap).

Tests:
- Grain `[game_id, team_id, situation]`, `accepted_values` on `situation`.
- `assert_team_shares_sum_to_one.sql`: for every game and measure, the two teams' `ev` and
  `all` shares sum to 1 (raw and adjusted), and team A's `pp` share plus team B's `pk` share
  sum to 1.
- `assert_team_situations_mirror.sql`: each `*_for` equals the opponent's `*_against` in
  the mirrored situation.
- `assert_team_totals_match_games.sql`: `all` shots on goal and shot attempts equal
  `fct_games`' home/away columns; `all` goals equal the final score (minus the shootout +1).
- `assert_team_gsax_matches_goalies.sql` (step 1, from the team side).
- Unit test for the adjustment weights on a tiny hand-built league.

**`fct_team_season_situations`**: one row per team per season per situation. Counts summed
from games, shares and rates recomputed from the sums, plus `games_played`. Tested to sum
back to the game rows.

## Step 4: Special teams beyond PP%

Needs time in each situation, which nothing has today.

**`int_strength_intervals_derived`**: one row per game per stretch of constant manpower:
`start_game_seconds`, `end_game_seconds`, `home_skaters`, `away_skaters` (penalties only, no
goalie pulls). Built from `int_penalties_timed` (starts, and ends: time out or the goal that
ended it), the start of overtime (3-on-3 rules in regular season), and the game's end.
- **Game end:** 3,600 s for regulation; the overtime winner's `game_seconds` for an OT
  decision; 3,600 + 300 for a shootout. New var `regular_season_overtime_seconds: 300`
  (PWHL rulebook: five-minute 3-on-3 overtime). Playoff overtime has no shootout and ends on
  the goal.
- **Same skater rule as `int_shots_enriched`**, applied to time rather than to shots. Two
  copies of the rule could drift apart, so a test checks that each shot's penalty-only
  manpower matches the interval it falls in. A shared macro isn't justified for two models
  (style guide: three or more).
- Known gap: time with a pulled goalie stays in its manpower group. A goalie pull during a PP is rare.

**On `fct_team_game_situations`** (already in the column list): `situation_seconds` and, for every
situation, `goals_for_per_2_min`, `goals_against_per_2_min`, `xg_for_per_2_min`,
`xg_against_per_2_min` (= value × 120 / situation_seconds, null when it is 0).
- Power play: `pp` row, `*_for_per_2_min`.
- Penalty kill: `pk` row, `*_against_per_2_min`.
- Shorthanded chances generated: `pk` row, `shots_on_goal_for`, `xg_for`,
  `quality_chances_for` (and per 2 minutes).
- Why per 2 minutes: a minor is 2 minutes, so "xG per 2 min of PP" reads as "xG per full
  power play", which works at PWHL sample sizes, where per-60 rates mean little.

Tests:
- `assert_strength_intervals_cover_game.sql`: intervals tile each game with no gaps or
  overlaps, from 0 to the game's end.
- `assert_shot_manpower_matches_intervals.sql`: manpower agrees on ≥ 99% of shots.
  Same-second ordering can legitimately differ: a shot in the second a penalty is called
  doesn't count it; an interval does. Threshold set from the first run, like the 45 in
  `assert_pwhl_goal_strength_matches_league`.
- Mirror test: a team's `pp` seconds equal its opponent's `pk` seconds.
- `all` seconds = `ev` + `pp` + `pk` seconds.
- Unit test with a 5-on-3, a PP goal ending one minor, and 4v4.

## Step 5: PDO and luck

On `fct_team_game_situations` / `fct_team_season_situations`, for every situation (`ev` is the
"even strength" number, `all` all situations):

| Column | Meaning |
|---|---|
| `shooting_pct` | goals / shots on goal, on shots at a goalie (no empty-net goals) |
| `save_pct` | 1 − goals against / shots on goal against, same shots |
| `pdo` | `shooting_pct + save_pct`, on a 1.000 scale (league average ≈ 1.000) |
| `goal_diff_above_expected` | (goals for − goals against) − (xG for − xG against), on shots that have xG |

- **Built:** both team marts also carry `empty_net_goals_for` / `_against`, so season PDO can be
  recomputed from summed counts. `goal_diff_above_expected` is additive, so seasons sum it.
- Empty-net goals are left out of PDO and luck in the `all` row: no goalie, no xG. In
  `ev`/`pp`/`pk` they're already excluded. The descriptions say so.
- `ev` includes 4v4 and 3v3 overtime. 3v3 is <2% of shots, so `ev` is close to 5v5, but
  not equal. A separate `5v5` situation is easy to add if you want it.
- Luck, in words: goals that came from finishing and goaltending rather than chances. Over
  a season it is mostly noise and tends back toward 0. Step 5 validation: the
  correlation of first-half and second-half `goal_diff_above_expected`, which should be
  near 0, vs xG differential, which should hold up better.

Tests:
- `pdo` in [0.7, 1.3] as a warning. Single games can fall outside that, so it only flags;
  season rows outside it mean a bug.
- `assert_goal_diff_above_expected_cancels.sql`: per game and situation pair, the two teams'
  `goal_diff_above_expected` sum to 0. One team's luck is the other's bad luck.

## Step 6: Field tilt

**Definition (soccer analogy: each team's share of final-third passes).** A team's
offensive-zone events, each credited to the team that made it:
- its shots on goal and blocked shot attempts in its offensive zone,
- its hits in its offensive zone (forechecking),
- its faceoff wins in its offensive zone.

`field_tilt` = team's offensive-zone events / both teams' offensive-zone events. On
`fct_team_game_situations` and the season mart, `all` rows only (as you described it:
one share per game); null on other rows. Columns: `offensive_zone_events_for` /
`_against`, `field_tilt`.

**Models.**
- `int_attack_sides_inferred`: moves `int_shots_enriched`'s `attack_side` CTE into its own
  model, with no change to its logic. Style guide: a CTE needed by two models becomes a
  model. `int_shots_enriched` then reads it. Its unit test moves with it, and
  `int_shots_enriched`'s output must not change. Checked by an `except` query in CI
  (zero rows).
- `int_zone_events_located`: one row per shot, hit and faceoff, with
  `is_offensive_zone` for the team credited.
  - Shots: x is already turned toward the attacked net.
  - Faceoffs: the 17 fixed dots (rink-coordinates.md). End-zone dots (x = 100/143 and
    457/500) are unambiguous.
  - Hits need a blue line.

**Open item: where the blue line is in grid units.** The 600 × 300 grid is stylized.
Stretched to scale, the blue line (25 ft from center) is at x = 300 ± 75. But a faceoff dot
sits at x = 397, which would then be inside the zone, while real neutral-zone dots are
outside it. So the true line is somewhere from ~375 to ~430.
- Before building, one query settles it: hit and faceoff x distributions, and where shots on
  goal stop. The result goes into a new var, `blue_line_offset_units`, with its evidence in a
  comment.
**Open item: rink (scorekeeper) bias, checked before building.** In the NHL, some arenas'
off-ice officials record hits, blocks and shots more generously for *both* teams. The
venue adjustment in step 3 doesn't catch that, and field tilt counts hits, which are the
most subjective event.
- **The query:** per venue and season, hits, blocked shots and shots on goal per game,
  both teams combined. Compare that with the same teams' games elsewhere, so a hard-hitting
  home team isn't mistaken for a generous scorer.
- **Decision rule, set in advance:**
  - Hits: if any regular venue records them at more than 1.5× or less than 0.67× what the
    same teams record elsewhere, drop hits from field tilt. Shots, blocks and faceoffs
    remain.
  - Shots and blocks: if the bias is that large, record it as a known issue with its
    numbers. It barely moves shares, because both teams in the game are counted by the same
    scorer, but it does inflate counts and per-2-minute rates.
  - Per-venue correction factors are the alternative. With ~15 games per venue per season
    they'd be noisy, so dropping is the default.
- The result and its numbers go in this doc either way.
- Blocked-shot coordinates may be the blocker's spot, not the shooter's (xg-audit.md
  dropped this question). Either way they are in the same zone.

Tests: shares sum to 1 per game; every faceoff dot classifies to exactly one zone;
`int_shots_enriched` unchanged.

## Step 7: Team rating (Elo) and season simulation (Python, `ml/forecast/`)

Sequential (each game's rating depends on the last) and simulation work, awkward in SQL.
Plain modules, unit-tested, like `ml/xg/`:

| Module | Job |
|---|---|
| `data.py` | SQL for games, results, remaining schedule, conferences |
| `elo.py` | ratings game by game; pregame outcome probabilities |
| `simulate.py` | Monte Carlo season; standings with tiebreakers; playoff odds |
| `win_probability.py` | step 8 |
| `evaluate.py` | log loss, Brier, calibration, baselines |
| `publish.py` | create/stage/swap SQL for the three tables, as `ml/xg/publish.py` |
| `__main__.py` | `python -m ml.forecast setup|run|backfill --target dev|prod`; the only warehouse access |

**Parameters: estimated from data at run time, not hard-coded. No model registry.**
- **Two kinds of number.**
  - **Design choices** live in code, reviewed in a PR: the K and carryover grids, λ, the
    shootout-as-half-a-win rule, the moment spacing.
  - **Values measured from data** are estimated by the run itself: home ice, OT rate, goal
    rates, manpower multipliers, β.
- **Measured values come only from completed seasons.** Every run estimates them from
  seasons before the one being scored, so they change once a year, when a season ends.
  That's the same rhythm as xG retraining, but with no manual step. Within a season,
  published numbers move only because new games were played.
- **Visible and auditable.** Each run writes the values it used to `ml.forecast_parameters`:
  name, value, the season it applies to, the seasons it was estimated from, model version.
  Declared as a dbt source, with tests on plausible ranges (e.g. home ice between −100
  and +100 Elo points). A daily run has nothing to log in MLflow.
- **Why no registry, unlike xG:**
  - There's no fitted object to save: the estimates are a few averages and one small
    regression.
  - Recomputing them, and replaying every game, takes seconds and gives the same answer
    each time.
  - xG needed the registry because its fitted pipeline is large and sensitive to the
    scikit-learn version.
- **MLflow tracking stays for experiments.** `notebooks/forecast_evaluation.py` logs each
  candidate (Elo grid, win-probability variants) as a run, as the xG notebooks do. The PR
  that sets a design choice cites the run.

### Elo

- Rating update after each game:
  r ← r + K · M · (S − E).
  - E = 1 / (1 + 10^(−(r_team − r_opp ± H)/400)), the expected result. H is home ice.
  - S = the actual result: 1 win, 0 loss.
  - **Shootouts count as S = 0.5** for both teams: a shootout says the teams were level
    after 65 minutes, and the shootout itself is close to a coin flip. OT wins count
    as wins.
  - M = margin-of-victory multiplier, ln(|goal margin| + 1) × 2.2 / (0.001 · rating gap of
    the winner + 2.2). This is FiveThirtyEight's NHL form. The second factor stops
    favorites' ratings inflating from blowouts. Margin is regulation/OT goals; the shootout +1
    doesn't count.
- New season: r ← 1500 + c · (r − 1500). Rosters turn over, so ratings carry over only part
  of the way. **Expansion teams start at 1500** (league average). There's no data to set
  them lower, and the first ~10 games move them quickly at the K we'll use.
- Playoff games update ratings too, with the same K.
- **Pregame outcome probabilities** (what the simulation needs, under 3-2-1-0):
  - P(win) = E with home ice.
  - P(tied after regulation) = r, the league rate from earlier seasons. Constant, not modeled
    by rating gap: too few OT games (~70 so far) to fit that.
  - Regulation home win = (1 − r)·P(win). OT/SO home win = r · q, where
    q = 0.5 + λ(P(win) − 0.5) and λ = 0.5, set in advance, not tuned: 3v3 and shootouts are
    more random than regulation.
- **Tuning, pre-registered (same discipline as xG):**
  - 2023-24 is warm-up only. Choices are made on 2024-25. 2025-26 (120 games + playoffs)
    is the untouched test.
  - **Measured from data each run, not tuned:**
    - H, from the home win rate in completed seasons, neutral sites excluded
      (H = 400·log10(h / (1 − h))). It is 0 at neutral sites. Last change probably keeps a
      little home advantage there, but there are too few neutral games to measure it.
    - r, from the OT rate.
  - **Tuned, on a small grid:** K ∈ {8, 12, 16, 24, 32} × c ∈ {0.5, 0.67, 0.8, 1.0}, plus one
    yes/no for the MOV multiplier. 20 × 2 = 40 combinations on 90 games is already plenty of
    room to overfit; that's why nothing else is tuned.
  - **One candidate beyond goals:** update on xG margin instead of goal margin (or a blend).
    It's less noisy per game, which matters at 30 games a season. Kept only if 2024-25 log
    loss drops.
- **Metrics:** log loss and Brier on P(home win), and a 3-way log loss on {home regulation
  win, OT/SO, away regulation win}, plus a calibration table (5 bins; more is noise at 120
  games).
  - Baselines: coin flip (0.5), home-ice rate (constant h), and Elo without MOV.
  - Bootstrap 95% intervals by game.
- **Expect the honest result to be modest:** at 120 test games, the standard error of a
  Brier score is ~0.01. That's about the gap between a good rating and the home-ice rate. If
  Elo doesn't beat home-ice by more than its interval, this doc says so, and the website
  shows ratings without claiming predictive skill.

### Season simulation

- 10,000 seasons per run, fixed seed (results reproducible). Each remaining regular-season
  game is drawn from the four pregame outcomes, and points are awarded 3-2-1-0.
- Ratings stay fixed within a simulated season. FiveThirtyEight-style "hot" updates add
  uncertainty, but also code. Check the calibration first; add them only if projections
  come out overconfident.
- **Standings and playoffs per season, from a small config table in `simulate.py`,** each
  with its source:
  - 2024–2026: one table, top 4 qualify.
  - 2026-27: two six-team conferences, top 4 in each. Conference membership comes from
    `dim_teams` / `stg_pwhl__teams` per season.
- **Tiebreakers:** points, then points percentage, then total wins (the league's list,
  partly confirmed: [tiebreaker procedure](https://www.thepwhl.com/en/playoff-tiebreaker-procedure)
  didn't load in full from this session), then random. To verify against the rulebook before
  building. The list lives in one function, unit-tested.
- **Output `ml.season_projections` → `fct_team_season_projections`:** one row per team per
  season per as-of date:
  - `games_played`, `points`, `games_remaining`
  - `projected_points` (mean), `projected_points_p10`, `projected_points_p90`
  - `playoff_probability`, `first_place_probability` (conference first place from 2026-27)
  - `simulations`, `model_version`
  - The daily run writes today's row. `backfill` fills past dates for completed seasons, which
    is what the evaluation uses and what a "playoff odds over time" chart would need.
- **Validation:**
  - Per-game probabilities are checked under Elo (above).
  - With ~20 team-seasons, playoff odds can't be calibrated meaningfully. Instead: mean absolute
    error of projected final points at the season's midpoint, against a "current points
    pace" baseline, for 2024-25 and 2025-26. Reported, with the caveat about sample size.
- Tests (SQL, `transform/tests/`):
  - `assert_projected_points_add_up.sql`: per season and date, summed `projected_points` =
    summed current points + 3 × remaining games. Every game hands out exactly 3 points under
    3-2-1-0.
  - `assert_projected_points_in_range.sql`: current ≤ p10 ≤ mean ≤ p90 ≤ current + 3 ×
    remaining.
  - `assert_playoff_probabilities_sum.sql`: summed `playoff_probability` = playoff spots, per
    season and date.
  - `assert_projection_points_match_games.sql`: current points equal what `fct_games` results
    give. This reconciles Python against SQL.
- Pytest: points per outcome, tiebreak order, conference qualification, a 2-team league
  where one team can't catch up (probability exactly 1), seeded reproducibility.

### Pregame ratings on `fct_games` (new gold columns)

From `ml.team_ratings` (one row per team per game: `rating_before`, `rating_after`,
`win_probability`, `overtime_probability`):
- `fct_games` gains `home_rating_before`, `away_rating_before`,
  `home_win_probability`, `overtime_probability`.
- It's the natural place for "game predictions with tracked accuracy" (README).

## Step 8: In-game win probability

**Model form: a Poisson (Skellam) goal model, not a fitted classifier.**
- From any moment, each team's remaining goals ~ Poisson(rate × remaining time). P(home win)
  = P(home ends ahead) + P(tied) × P(home wins OT/SO).
- Why this over logistic regression on game states:
  - Game states within a game are heavily correlated, so ~400 games is a small sample
    for a classifier, and it can learn odd shapes near the end of games.
  - The Poisson form gets the end of a game right by construction: no time left, the
    score decides.
  - It has ~5 parameters, each explainable.
  - Skellam probabilities are a sum of Poisson terms in numpy (scipy is already installed for
    xG): nothing new to install.
- **Rates** (all measured each run from completed seasons and written to
  `ml.forecast_parameters`; see "Parameters" in step 7):
  - League goal rate per second.
  - × team strength from pregame Elo: λ_home / λ_away = exp(β · rating gap with home ice). β
    comes from a Poisson regression of final scores on the pregame gap (scikit-learn's
    `PoissonRegressor`).
  - × manpower multipliers (PP / PK / 4v4 / 3v3) for the penalty time left at that moment,
    from `int_strength_intervals_derived`.
- **OT:**
  - Regular season: 3v3 for 5 min. P(home scores first in OT) from the 3v3 rates, and q (as
    in step 7) for the shootout if nobody does.
  - Playoffs: sudden-death 5v5, P(home first) = λ_home / (λ_home + λ_away).
- **xG so far, only if it helps:** blend the pregame rate with each team's xG pace so far
  (a gamma-Poisson update, the same idea as step 2: the pregame rate counts as n₀ minutes of
  evidence). It's kept only if 2024-25 log loss drops.
- **Known gap: goalie pulls.** Trailing teams pull the goalie late, which raises both teams'
  scoring. The model ignores that at first. The calibration check in the last 3 minutes shows
  whether it matters. If it does, a late-game, trailing-by-1-or-2 rate bump is the fix.
- **Moments:** every 30 s of game time, plus just after each goal, for final games.
  `ml.win_probabilities` → `fct_game_win_probabilities`: `game_id`, `moment_number`,
  `game_seconds`, `period`, `home_goals`, `away_goals`, `home_skaters`, `away_skaters`,
  `home_win_probability`, `model_version`. About 250 rows per game.
- **Evaluation:**
  - On 2025-26, sampling one moment per minute per game, so every game counts equally.
  - Log loss and Brier overall and by period. Calibration in 10 bins.
  - Baselines: home-ice rate at every moment, and **score-and-time only**: the same Poisson
    model with equal team rates and no manpower.
  - Choices made on 2024-25, as in step 7.
- Tests:
  - Pytest: P = 1 or 0 at the final horn with a lead; tied at 0:00 equals pregame; symmetry
    (swapping teams gives 1 − P); OT and shootout paths; probabilities in [0, 1].
  - SQL: the last moment of every final game agrees with the winner; the first moment equals
    `fct_games.home_win_probability`.

## Evaluation numbers (to fill in)

I can't run anything against the warehouse from a cloud session. The numbers come from:
- `notebooks/forecast_evaluation.py` (Elo, simulation, win probability), run by hand in
  Databricks like the xG notebooks;
- the step 2 and step 5 queries, run in the SQL editor.

Results go into this doc, in tables like xg-model.md's, before steps 7 and 8 publish
anything.

| Check | Baseline | Result |
|---|---|---|
| Finishing: next-season MSE, raw vs shrunk | zero | — |
| Elo: log loss / Brier, P(home win), 2025-26 | home-ice rate | — |
| Elo: 3-way log loss | historical frequencies | — |
| Projections: midseason points MAE | points pace | — |
| Win probability: log loss / Brier, 2025-26 | score-and-time only | — |

## Build order: PRs and commits

One PR at a time, each merged before the next (workflow.md: don't stack PRs). One commit
per metric group. Each PR runs pre-commit, pytest and CI's `dbt` job, and gets a cheap-model
review of its diff, before I report it done.

| PR | Commits | Waits on |
|---|---|---|
| A | this plan | your sign-off |
| B | 1 GSAx; 2 finishing | A |
| C | 3 shot/xG share (+ `strength_group`); 4 special teams; 5 PDO and luck | B |
| D | 6 field tilt (blue-line query first) | C |
| E | 7 Elo + simulation, `ml/forecast/`, notebook, sources, marts | D, plus the pipeline decision below |
| F | 8 win probability | E |

## Decisions

These are "ask before" items in CLAUDE.md.

1. **New gold marts and grains:**
   - `fct_goalie_games` (goalie × game)
   - `fct_player_seasons` (player × season)
   - `fct_player_careers` (player × season type)
   - `fct_team_game_situations` (team × game × situation)
   - `fct_team_season_situations` (team × season × situation)
   - `fct_team_season_projections` (team × season × as-of date)
   - `fct_game_win_probabilities` (game × moment)
2. **New columns on existing marts:**
   - `fct_shots.strength_group`
   - `fct_games.is_neutral_site` (agreed)
   - `fct_games.home_rating_before`, `away_rating_before`, `home_win_probability`,
     `overtime_probability`
3. **New Python-written tables** in the existing `ml` schema: `team_ratings`,
   `season_projections`, `win_probabilities`, `forecast_parameters`. Dev first, prod when
   step 7 ships.
4. **Pipeline change (step 7):**
   - After the xG steps, `python -m ml.forecast run`, then
     `dbt build --select stg_ml__team_ratings+ stg_ml__season_projections+ stg_ml__win_probabilities+`.
   - CI gains `python -m ml.forecast setup --target dev`, so the sources exist.
   - No schedule change, but it is the workflow.
5. **No new dependencies.** numpy, pandas, scipy and scikit-learn are already in use by
   `ml/xg/`.
6. **Method choices to confirm:**
   - shrink finishing toward the position group (not the whole league), and shrink GSAx
     toward an average goalie;
   - score adjustment only for `ev`/`all`;
   - GSAx per 100 shots;
   - shootouts as half a win in Elo;
   - field tilt on `all` only.

## Open questions

- **"Tagged":** I read this as dbt tags, so the new work can be built with
  `--select tag:metrics`. Proposal: `tags: [metrics]` on every new dbt model, and
  `[forecast]` on the ones fed by `ml/forecast/`. If you meant git tags or GitHub labels,
  say which.
- **Blue line** in grid units (step 6): settled by a query before that step.
- **Rink bias** in hits (step 6): settled by a query before that step. It decides whether
  hits stay in field tilt.
- **Tiebreakers** past "total wins": verify against the rulebook before step 7.

## More data from HockeyTech? (suggestions, not in this plan)

Nothing above needs a new endpoint. Two would help later:
- **Standings endpoint:** a reconciliation test of our computed points and tiebreaks against
  the league's own table.
- **Shift feed (`gameshifts`):** ice time and on-ice players for every event. It's the only
  way to on-ice xG, per-60 rates, or RAPM. Coverage is patchy (xg-model.md, step 2).
