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
