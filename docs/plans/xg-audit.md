# xG step 1: data audit

Queries for step 1 of the [xG plan](xg-model.md). Run them in the Databricks SQL editor against your dev schemas.

- `fct_shots` is a gold mart: `dev.dbt_apetry_gold`.
- Staging and base models are in silver: `dev.dbt_apetry_silver`.

Already settled, so not repeated here: the coordinate scale and the swapped-end periods ([rink-coordinates.md](rink-coordinates.md)).

## How to send results

1. Run query 0 first. If it fails or shows nulls, rebuild dev on `main` (`dotenv -f ../.env run -- dbt build --select fct_shots+` from `transform/`), then continue.
2. Run each query. Copy the result grid with its headers: select all in the grid, then copy, which gives tab-separated text.
3. Paste them all into one chat message, in any order.
   - Each result starts with a `query` column (`1a`, `4c`, ...), so the tables label themselves.
   - If a query fails, paste the error instead.

Alternatively, paste them into [Results](#results) at the bottom and commit, so the output stays next to the queries.

Every query returns aggregates only, under ~50 rows, with rates rounded to 3 decimals.

Definitions used throughout:

- **Shot at a goalie:** an unblocked shot with a goalie in net (`is_unblocked and not is_empty_net`). This is the xG model's population.
- **Goal rate:** goals / shots at a goalie.

## 0. Preflight: does dev have the coordinate fix?

`x_ft` only exists after the fix (PR #11). If this errors on `x_ft`, or `missing_distance` isn't close to 0, rebuild dev first.

```sql
select
    '0' as query,
    count(*) as shots,
    count_if(is_unblocked) as unblocked_shots,
    count_if(is_unblocked and distance_ft is null) as missing_distance,
    round(min(x_ft), 1) as min_x_ft,
    round(max(x_ft), 1) as max_x_ft
from dev.dbt_apetry_gold.fct_shots
```

## 1. Volume

### 1a. Shots and goals per season

How much data the model has, and the goal rate per season. Expect a goal rate around 0.08–0.10 for shots on goal; a season far off that suggests a data problem.

```sql
with shots as (
    select
        season_id,
        season_type,
        shot_result,
        is_goal,
        is_unblocked,
        is_empty_net
    from dev.dbt_apetry_gold.fct_shots
),

seasons as (
    select
        season_id,
        season_name
    from dev.dbt_apetry_silver.stg_pwhl__seasons
),

per_season as (
    select
        season_id,
        season_type,
        count(*) as shots,
        count_if(shot_result = 'blocked') as blocked_shots,
        count_if(is_unblocked) as unblocked_shots,
        count_if(is_goal) as goals,
        count_if(is_empty_net) as empty_net_shots,
        count_if(is_empty_net and is_goal) as empty_net_goals,
        count_if(is_unblocked and not is_empty_net) as shots_at_goalie,
        count_if(is_goal and not is_empty_net) as goals_at_goalie
    from shots
    group by season_id, season_type
)

select
    '1a' as query,
    per_season.season_id,
    seasons.season_name,
    per_season.season_type,
    per_season.shots,
    per_season.blocked_shots,
    per_season.unblocked_shots,
    per_season.goals,
    per_season.empty_net_shots,
    per_season.empty_net_goals,
    per_season.shots_at_goalie,
    per_season.goals_at_goalie,
    round(per_season.goals_at_goalie / nullif(per_season.shots_at_goalie, 0), 3) as goal_rate
from per_season
left join seasons on per_season.season_id = seasons.season_id
order by per_season.season_id
```

### 1b. Do goals and goal shots agree?

Checks whether every goal event has a shot marked as a goal, matched on `goal_id`. Penalty-shot goals are left out because they're a separate event type. Goals with no matching shot would make the goal rate too low.

- `goal_events` should equal `shots_marked_goal`.
- `goal_events_without_shot` should be 0.
- `goal_shots_without_goal_id` counts shots marked as goals only because their description contains "goal" (see 4a).

```sql
with goals as (
    select
        season_id,
        game_id,
        goal_id
    from dev.dbt_apetry_silver.stg_pwhl__goals
    where not coalesce(is_penalty_shot, false)
),

goal_shots as (
    select
        season_id,
        game_id,
        goal_id
    from dev.dbt_apetry_gold.fct_shots
    where is_goal
),

goals_matched as (
    select
        goals.season_id,
        -- Distinct, in case two shots carry the same goal_id.
        count(distinct goals.game_id, goals.goal_id) as goal_events,
        count_if(goal_shots.goal_id is null) as goal_events_without_shot
    from goals
    left join goal_shots
        on goals.game_id = goal_shots.game_id
        and goals.goal_id = goal_shots.goal_id
    group by goals.season_id
),

shots_counted as (
    select
        season_id,
        count(*) as shots_marked_goal,
        count_if(goal_id is null) as goal_shots_without_goal_id
    from goal_shots
    group by season_id
)

select
    '1b' as query,
    coalesce(goals_matched.season_id, shots_counted.season_id) as season_id,
    coalesce(goals_matched.goal_events, 0) as goal_events,
    coalesce(shots_counted.shots_marked_goal, 0) as shots_marked_goal,
    coalesce(goals_matched.goal_events_without_shot, 0) as goal_events_without_shot,
    coalesce(shots_counted.goal_shots_without_goal_id, 0) as goal_shots_without_goal_id
from goals_matched
full outer join shots_counted on goals_matched.season_id = shots_counted.season_id
order by season_id
```

## 2. Missing coordinates

Shots with no location, or a `(0, 0)` placeholder, per season and result. Without a location, a shot has no distance or angle.

```sql
select
    '2' as query,
    season_id,
    shot_result,
    count(*) as shots,
    count_if(x_location is null or y_location is null) as missing_xy,
    count_if(x_location = 0 and y_location = 0) as zero_xy,
    count_if(distance_ft is null) as missing_distance
from dev.dbt_apetry_gold.fct_shots
group by season_id, shot_result
order by season_id, shot_result
```

## 3. Shot types

Which shot types exist and how often each scores. `looks_like_tip` flags types that mention tips, deflections, or redirects. If none do, tips aren't recorded, and a tip shows up as an ordinary shot from close in.

```sql
with shots as (
    select
        shot_type,
        is_goal
    from dev.dbt_apetry_gold.fct_shots
    where is_unblocked and not is_empty_net
),

totals as (
    select count(*) as all_shots
    from shots
),

per_type as (
    select
        shot_type,
        count(*) as shots_at_goalie,
        count_if(is_goal) as goals
    from shots
    group by shot_type
)

select
    '3' as query,
    per_type.shot_type,
    per_type.shots_at_goalie,
    round(per_type.shots_at_goalie / totals.all_shots, 3) as share_of_shots,
    per_type.goals,
    round(per_type.goals / per_type.shots_at_goalie, 3) as goal_rate,
    coalesce(lower(per_type.shot_type) rlike 'tip|deflect|redirect', false) as looks_like_tip
from per_type
cross join totals
order by per_type.shots_at_goalie desc
```

## 4. Does `is_quality_chance` give away the outcome?

`stg_pwhl__shots` reads both the quality flag (`ilike 'quality%'`) and part of the goal detection (`ilike '%goal%'`) from the same field, `shot_quality_description`. If the league fills that field in after it knows the result, the flag leaks the outcome. In that case it can be a benchmark only, never a feature.

### 4a. What the field actually holds

Every raw value, and whether the event also carries a `game_goal_id`.

```sql
with events as (
    select
        event_type,
        event:shot_quality_description::string as shot_quality_description,
        nullif(event:game_goal_id::string, '') is not null as has_game_goal_id
    from dev.dbt_apetry_silver.base_pwhl__play_by_play_events
    where event_type in ('shot', 'blocked_shot')
)

select
    '4a' as query,
    event_type,
    shot_quality_description,
    has_game_goal_id,
    count(*) as events
from events
group by event_type, shot_quality_description, has_game_goal_id
order by event_type, events desc
```

### 4b. Goal rate, flagged vs not

`share_of_goals` is the share of all goals at a goalie that fall in each group. A row with an empty `is_quality_chance` means the description was missing; 4c counts those as unflagged. If flagged shots hold nearly every goal (say over 0.9) while being a minority of shots, the flag is probably set after the fact.

```sql
with shots as (
    select
        is_quality_chance,
        is_goal
    from dev.dbt_apetry_gold.fct_shots
    where is_unblocked and not is_empty_net
),

totals as (
    select
        count(*) as all_shots,
        count_if(is_goal) as all_goals
    from shots
),

per_flag as (
    select
        is_quality_chance,
        count(*) as shots_at_goalie,
        count_if(is_goal) as goals
    from shots
    group by is_quality_chance
)

select
    '4b' as query,
    per_flag.is_quality_chance,
    per_flag.shots_at_goalie,
    round(per_flag.shots_at_goalie / totals.all_shots, 3) as share_of_shots,
    per_flag.goals,
    round(per_flag.goals / totals.all_goals, 3) as share_of_goals,
    round(per_flag.goals / per_flag.shots_at_goalie, 3) as goal_rate
from per_flag
cross join totals
order by per_flag.is_quality_chance
```

### 4c. By distance band

This is the deciding check.

- **An honest flag** is about where the shot came from. Its share should drop with distance, and within a band, flagged and unflagged shots should score at fairly similar rates.
- **A leaky flag** follows the result. Far-out shots that happened to score get flagged, so `goal_rate_flagged` stays high even at 45–70 ft and 70+ ft.

```sql
with shots as (
    select
        -- A missing description counts as not flagged (4b shows how many there are).
        coalesce(is_quality_chance, false) as is_quality_chance,
        is_goal,
        case
            when distance_ft < 10 then 1
            when distance_ft < 20 then 2
            when distance_ft < 30 then 3
            when distance_ft < 45 then 4
            when distance_ft < 70 then 5
            else 6
        end as band_order,
        case
            when distance_ft < 10 then '00-10 ft'
            when distance_ft < 20 then '10-20 ft'
            when distance_ft < 30 then '20-30 ft'
            when distance_ft < 45 then '30-45 ft'
            when distance_ft < 70 then '45-70 ft'
            else '70+ ft'
        end as distance_band
    from dev.dbt_apetry_gold.fct_shots
    where
        is_unblocked
        and not is_empty_net
        and distance_ft is not null
),

per_band as (
    select
        band_order,
        distance_band,
        count(*) as shots_at_goalie,
        count_if(is_goal) as goals,
        count_if(is_quality_chance) as flagged_shots,
        count_if(is_quality_chance and is_goal) as flagged_goals,
        count_if(not is_quality_chance) as unflagged_shots,
        count_if(not is_quality_chance and is_goal) as unflagged_goals
    from shots
    group by band_order, distance_band
)

select
    '4c' as query,
    distance_band,
    shots_at_goalie,
    goals,
    round(goals / shots_at_goalie, 3) as goal_rate,
    round(flagged_shots / shots_at_goalie, 3) as flagged_share,
    round(flagged_goals / nullif(goals, 0), 3) as flagged_share_of_goals,
    round(flagged_goals / nullif(flagged_shots, 0), 3) as goal_rate_flagged,
    round(unflagged_goals / nullif(unflagged_shots, 0), 3) as goal_rate_unflagged
from per_band
order by band_order
```

## Findings (from the results below)

- **Sample.** 26,544 shots in all; 19,376 at a goalie with 1,614 goals (8.3%). Regular season plus playoffs, which is the training set: 18,022 shots at a goalie and 1,476 goals.
- **Preseason is left out of training.** The 2024 preseason recorded no blocked shots, and preseason goal rates run high (0.097–0.112). Its scoring looks different from the regular season, and it's only ~1,350 shots.
- **Goals reconcile exactly** (1b), and **no shot is missing coordinates** (2).
- **Empty-net shots: only 9 in three seasons, all goals.** That's far too few. Most empty-net goals probably still carry a `goalie_id`, so `is_empty_net` is undercounted. Query 5a checks this against the goals' own `is_empty_net` flag. It matters for the training filter and for goalie pulls in strength state.
- **Shot type.**
  - Tips are recorded: 3.9% of shots, scoring at 13.6%, the highest rate of any type.
  - "Default" is 33% of shots, effectively unknown, and scores above average (9.4%). Keep it as its own category. Query 5b checks whether it clusters in certain seasons.
- **`is_quality_chance` doesn't give away the outcome. It's a location zone.**
  - Within 30 ft, ~70–75% of shots are flagged.
  - From 30–45 ft, about half are.
  - Beyond 45 ft, essentially none. Of 189 goals from beyond 45 ft, only 1 was flagged, so far-out goals aren't flagged after the fact.
  - Blocked shots carry the flag too ("Quality blocked"), which fits a rule based on location.
  - Within a distance band, flagged shots score more because the unflagged ones are the wide-angle shots at the same distance.
  - **Verdict:** not leakage, but redundant with distance and angle. Not a feature; a benchmark: "how much better than the league's own zone is the model?"

## 5. Follow-ups

Prompted by the results above, and input to the strength-state model. Same routine: paste the results back.

### 5a. Empty-net goals: shots vs goal events

`goal_events_empty_net` is the league's own flag on the goal. If it's far above `shots_empty_net`, `fct_shots.is_empty_net` misses most empty nets. `goalie_pulls` counts goalie changes with nobody coming in.

```sql
with goals as (
    select
        season_id,
        count(*) as goal_events,
        count_if(is_empty_net) as goal_events_empty_net
    from dev.dbt_apetry_silver.stg_pwhl__goals
    where not coalesce(is_penalty_shot, false)
    group by season_id
),

shots as (
    select
        season_id,
        count_if(is_goal and is_empty_net) as shots_empty_net
    from dev.dbt_apetry_gold.fct_shots
    group by season_id
),

pulls as (
    select
        season_id,
        count_if(goalie_in_player_id is null) as goalie_pulls,
        count(*) as goalie_changes
    from dev.dbt_apetry_silver.stg_pwhl__goalie_changes
    group by season_id
)

select
    '5a' as query,
    goals.season_id,
    goals.goal_events,
    goals.goal_events_empty_net,
    shots.shots_empty_net,
    pulls.goalie_pulls,
    pulls.goalie_changes
from goals
left join shots on goals.season_id = shots.season_id
left join pulls on goals.season_id = pulls.season_id
order by goals.season_id
```

### 5b. "Default" shot type by season

```sql
select
    '5b' as query,
    season_id,
    count(*) as shots_at_goalie,
    count_if(shot_type = 'Default') as default_type_shots,
    round(count_if(shot_type = 'Default') / count(*), 3) as default_share
from dev.dbt_apetry_gold.fct_shots
where is_unblocked and not is_empty_net
group by season_id
order by season_id
```

### 5c. Players on the ice at goals

Goals list the players on the ice for each side (`plus` / `minus`). If those lists are complete, they give the real skater counts at every goal, a much stronger test for strength state than the power-play flags alone.
- -1 or empty means the list is missing.
- The counts may include the goalie; the 5v5 rows will show which.
- The `is_overtime` rows show whether overtime is played 3-on-3.

```sql
with goals as (
    select
        season_id,
        is_power_play,
        is_short_handed,
        is_empty_net,
        period > 3 as is_overtime,
        size(on_ice_for_player_ids) as players_for,
        size(on_ice_against_player_ids) as players_against
    from dev.dbt_apetry_silver.stg_pwhl__goals
    where not coalesce(is_penalty_shot, false)
)

select
    '5c' as query,
    is_overtime,
    is_power_play,
    is_short_handed,
    is_empty_net,
    players_for,
    players_against,
    count(*) as goals
from goals
group by is_overtime, is_power_play, is_short_handed, is_empty_net, players_for, players_against
order by goals desc
```

### 5d. Penalty profile

Which penalty lengths and classes exist, and which ones the league marks as creating a power play (`is_power_play_penalty`). This decides how strength state treats misconducts, coincidental penalties, and double minors.

```sql
select
    '5d' as query,
    penalty_class,
    penalty_minutes,
    is_power_play_penalty,
    is_penalty_shot,
    is_bench_penalty,
    count(*) as penalties
from dev.dbt_apetry_silver.stg_pwhl__penalties
group by penalty_class, penalty_minutes, is_power_play_penalty, is_penalty_shot, is_bench_penalty
order by penalties desc
```

## Results

Paste each query's output below, as copied from the results grid.

### 0

```text
query	shots	unblocked_shots	missing_distance	min_x_ft	max_x_ft
0	26544	19385	0	-69.7	97.7
```

### 1a

```text
query	season_id	season_name	season_type	shots	blocked_shots	unblocked_shots	goals	empty_net_shots	empty_net_goals	shots_at_goalie	goals_at_goalie	goal_rate
1a	1	2024 Regular Season	regular	5083	925	4158	341	1	1	4157	340	0.082
1a	2	2024 Preseason	preseason	594	0	594	59	0	0	594	59	0.099
1a	3	2024 Playoffs	playoffs	1082	318	764	44	2	2	762	42	0.055
1a	4	2024-25 Preseason	preseason	474	136	338	38	0	0	338	38	0.112
1a	5	2024-25 Regular Season	regular	6986	2072	4914	441	2	2	4912	439	0.089
1a	6	2025 Playoffs	playoffs	1114	357	757	58	0	0	757	58	0.077
1a	7	2025-26 Preseason	preseason	576	154	422	41	0	0	422	41	0.097
1a	8	2025-26 Regular Season	regular	9584	2873	6711	549	3	3	6708	546	0.081
1a	9	2026 Playoffs	playoffs	1051	324	727	52	1	1	726	51	0.07
```

### 1b

```text
query	season_id	goal_events	shots_marked_goal	goal_events_without_shot	goal_shots_without_goal_id
1b	1	341	341	0	0
1b	2	59	59	0	0
1b	3	44	44	0	0
1b	4	38	38	0	0
1b	5	441	441	0	0
1b	6	58	58	0	0
1b	7	41	41	0	0
1b	8	549	549	0	0
1b	9	52	52	0	0
```

### 2

```text
query	season_id	shot_result	shots	missing_xy	zero_xy	missing_distance
2	1	blocked	925	0	0	0
2	1	goal	341	0	0	0
2	1	on_net	3817	0	0	0
2	2	goal	59	0	0	0
2	2	on_net	535	0	0	0
2	3	blocked	318	0	0	0
2	3	goal	44	0	0	0
2	3	on_net	720	0	0	0
2	4	blocked	136	0	0	0
2	4	goal	38	0	0	0
2	4	on_net	300	0	0	0
2	5	blocked	2072	0	0	0
2	5	goal	441	0	0	0
2	5	on_net	4473	0	0	0
2	6	blocked	357	0	0	0
2	6	goal	58	0	0	0
2	6	on_net	699	0	0	0
2	7	blocked	154	0	0	0
2	7	goal	41	0	0	0
2	7	on_net	381	0	0	0
2	8	blocked	2873	0	0	0
2	8	goal	549	0	0	0
2	8	on_net	6162	0	0	0
2	9	blocked	324	0	0	0
2	9	goal	52	0	0	0
2	9	on_net	675	0	0	0
```

### 3

```text
query	shot_type	shots_at_goalie	share_of_shots	goals	goal_rate	looks_like_tip
3	Wrist	8307	0.429	577	0.069	false
3	Default	6400	0.33	603	0.094	false
3	Snap	1886	0.097	169	0.09	false
3	Backhand	1172	0.06	101	0.086	false
3	Slap	855	0.044	61	0.071	false
3	Tip	756	0.039	103	0.136	true
```

### 4a

```text
query	event_type	shot_quality_description	has_game_goal_id	events
4a	blocked_shot	Non quality blocked	false	4971
4a	blocked_shot	Quality blocked	false	2188
4a	shot	Non quality on net	false	9557
4a	shot	Quality on net	false	8205
4a	shot	Quality goal	true	1137
4a	shot	Non quality goal	true	486
```

### 4b

```text
query	is_quality_chance	shots_at_goalie	share_of_shots	goals	share_of_goals	goal_rate
4b	false	10036	0.518	479	0.297	0.048
4b	true	9340	0.482	1135	0.703	0.122
```

### 4c

```text
query	distance_band	shots_at_goalie	goals	goal_rate	flagged_share	flagged_share_of_goals	goal_rate_flagged	goal_rate_unflagged
4c	00-10 ft	1957	325	0.166	0.711	0.778	0.182	0.127
4c	10-20 ft	4322	554	0.128	0.749	0.816	0.14	0.094
4c	20-30 ft	3445	309	0.09	0.744	0.887	0.107	0.04
4c	30-45 ft	4596	237	0.052	0.466	0.654	0.072	0.033
4c	45-70 ft	4434	167	0.038	0	0	0	0.038
4c	70+ ft	622	22	0.035	0.002	0.045	1	0.034
```

### 5a

```text
```

### 5b

```text
```

### 5c

```text
```

### 5d

```text
```
