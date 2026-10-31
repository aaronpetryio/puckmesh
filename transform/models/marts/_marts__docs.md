{% docs league_id %}
League the row belongs to (`pwhl`). Every model carries it so leagues can be unioned.
{% enddocs %}

{% docs season_id %}
The league's season ID. Preseason, regular season, and playoffs are separate seasons.
{% enddocs %}

{% docs season_type %}
`regular`, `preseason`, or `playoffs`.
{% enddocs %}

{% docs game_id %}
The league's game ID.
{% enddocs %}

{% docs team_id %}
The league's team ID. Stable across seasons, even when the team's name or code changes.
{% enddocs %}

{% docs player_id %}
The league's player ID.
{% enddocs %}

{% docs team_code %}
Short team code as of that season (`BOS`, `MTL`). Codes change between seasons.
{% enddocs %}

{% docs team_name %}
Team name as of that season. Names change between seasons (PWHL Boston became the
Boston Fleet).
{% enddocs %}

{% docs position %}
Position as the API reports it: F, D, G, C, LW, RW, LD, or RD.
{% enddocs %}

{% docs position_group %}
F, D, or G.
{% enddocs %}

{% docs first_season_id %}
Earliest season, by season start date.
{% enddocs %}

{% docs last_season_id %}
Most recent season, by season start date.
{% enddocs %}

{% docs event_index %}
Position of the event in the game's play-by-play, starting at 0. Events are in time order.
{% enddocs %}

{% docs period %}
1-3 regulation, 4 and up overtime.
{% enddocs %}

{% docs period_seconds %}
Seconds elapsed in the period.
{% enddocs %}

{% docs game_seconds %}
Seconds elapsed in the game. Overtime counts from 3600, whatever the overtime length.
{% enddocs %}

{% docs scored_shots_on_goal %}
Shots on goal at a goalie that have xG: no empty-net goals, penalty shots or shootout
attempts, and no shots still waiting for the next xG scoring run.
{% enddocs %}

{% docs finishing_goals %}
Goals on those shots. Leaves out empty-net and penalty-shot goals, so it can be lower than
the player's official goal total.
{% enddocs %}

{% docs goals_above_expected %}
goals minus xg: goals scored beyond what an average shooter would score on the same shots.
Mostly luck over a single season at PWHL sample sizes; see goals_above_expected_shrunk.
{% enddocs %}

{% docs goals_above_expected_shrunk %}
goals_above_expected regressed toward the average for the player's position group (F or D):
the player's record plus prior_xg expected goals of average finishing, from
int_finishing_priors_estimated (docs/plans/metrics.md, step 2). Null for goalies.
{% enddocs %}

{% docs shrinkage_weight %}
xg / (xg + prior_xg), 0 to 1: how much of the player's own record the shrunk value keeps.
0 when the data shows no finishing skill spread in the group. Null for goalies.
{% enddocs %}

{% docs goalie_games %}
Games played in net (started, came in, or faced a shot), from fct_goalie_games. Null for
players who never played in net.
{% enddocs %}

{% docs gsax %}
Goals saved above expected: xg_faced minus goals_allowed. Positive means fewer goals allowed
than an average goalie would on the same shots. Null for players who never played in net.
{% enddocs %}

{% docs gsax_shrunk %}
gsax regressed toward an average goalie: the goalie's record plus prior_xg expected goals of
average goaltending, from int_finishing_priors_estimated (docs/plans/metrics.md, step 2).
{% enddocs %}

{% docs goalie_shrinkage_weight %}
xg_faced / (xg_faced + prior_xg), 0 to 1: how much of the goalie's own record gsax_shrunk
keeps. 0 when the data shows no goaltending skill spread.
{% enddocs %}

{% docs situation %}
all, ev, pp or pk, from this row's team's side: ev both teams have the same number of
skaters from penalties, pp this team has more (power play), pk fewer (penalty kill). Shots
with either net empty count only in all, so ev + pp + pk don't add up to all: don't sum
across situations. A team's pp row mirrors its opponent's pk row.
{% enddocs %}

{% docs shot_attempts_team %}
Shots on goal plus blocked shots. Not Corsi: the API doesn't record missed shots.
{% enddocs %}

{% docs score_venue_adjusted %}
Score-and-venue adjusted: each event weighted by 0.5 / the league's expected share for the
shooting team's venue and score state, from int_score_venue_weights_estimated, so an average
team comes out at 0.5 in every state (docs/plans/metrics.md, step 3). Neutral sites use
score only. all and ev rows only; null for pp and pk.
{% enddocs %}
