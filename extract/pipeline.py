"""Scheduled runs: fetch -> save changed responses -> upload -> load.

daily: seasons; schedule, teams, and rosters for active seasons; play-by-play for final
       games not stored yet plus games from the last few days (late stat corrections).
full:  everything in every season. Catches changes to historical data (corrections,
       new fields added to old games) that a daily run never looks at.
"""

from collections import Counter
from datetime import date, timedelta

from extract import raw
from extract.client import HockeyTechClient
from extract.endpoints import play_by_play, roster, schedule, seasons, teams
from extract.load import load
from extract.state import State
from extract.upload import upload

# A season is "active" from a month before it starts until two weeks after it ends.
ACTIVE_BEFORE = timedelta(days=30)
ACTIVE_AFTER = timedelta(days=14)
# Re-fetch play-by-play for games this recent, in case of late corrections.
RECENT_GAMES = timedelta(days=3)


def run(client: HockeyTechClient, mode: str, today: date | None = None) -> None:
    today = today or date.today()
    league = client.league
    state = State.load(league)
    fetched, saved = Counter(), Counter()

    def save(endpoint, response, params, **partitions):
        fetched[endpoint] += 1
        if raw.save(league, endpoint, response, params, state, **partitions):
            saved[endpoint] += 1

    seasons_response, params = seasons.fetch(client)
    save(seasons.NAME, seasons_response, params)

    for season in seasons_response["SiteKit"]["Seasons"]:
        season_id = int(season["season_id"])
        if mode == "daily" and not _is_active(season, today):
            continue

        schedule_response, params = schedule.fetch(client, season_id)
        save(schedule.NAME, schedule_response, params, season_id=season_id)

        teams_response, params = teams.fetch(client, season_id)
        save(teams.NAME, teams_response, params, season_id=season_id)
        for team_id in teams.team_ids(teams_response):
            response, params = roster.fetch(client, season_id, team_id)
            save(roster.NAME, response, params, season_id=season_id, team_id=team_id)

        recent_cutoff = (today - RECENT_GAMES).isoformat()
        for game in schedule_response["SiteKit"]["Schedule"]:
            if game["final"] != "1":
                continue
            game_id = int(game["game_id"])
            partitions = {"season_id": season_id, "game_id": game_id}
            is_new = not state.has(play_by_play.NAME, partitions)
            is_recent = game["date_played"] >= recent_cutoff
            if mode == "full" or is_new or is_recent:
                response, params = play_by_play.fetch(client, game_id)
                save(play_by_play.NAME, response, params, **partitions)

    print(f"{mode} run: fetched {sum(fetched.values())} responses, {sum(saved.values())} new or changed")
    for endpoint in sorted(fetched):
        print(f"  {endpoint:14} fetched {fetched[endpoint]:4}  saved {saved[endpoint]:4}")

    if sum(saved.values()):
        uploaded, skipped = upload(league)
        print(f"{uploaded} uploaded, {skipped} already in the Volume")
        for endpoint, rows in load(league).items():
            if rows:
                print(f"  loaded {rows} rows into {endpoint}")


def _is_active(season: dict, today: date) -> bool:
    start = date.fromisoformat(season["start_date"])
    end = date.fromisoformat(season["end_date"])
    return start - ACTIVE_BEFORE <= today <= end + ACTIVE_AFTER
