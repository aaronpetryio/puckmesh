"""Scheduled runs: fetch -> save changed responses -> upload -> load.

daily: seasons; schedule, teams, and rosters for active seasons; play-by-play for final
       games not stored yet plus games from the last few days (late stat corrections).
full:  everything in every season. Catches changes to historical data (corrections,
       new fields added to old games) that a daily run never looks at.
"""

import logging
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from extract import raw
from extract.client import HockeyTechClient, Json
from extract.endpoints import play_by_play, roster, schedule, seasons, teams
from extract.load import load
from extract.state import State
from extract.upload import upload

log = logging.getLogger(__name__)

Mode = Literal["daily", "full"]

# A season is "active" from a month before it starts until two weeks after it ends.
ACTIVE_BEFORE = timedelta(days=30)
ACTIVE_AFTER = timedelta(days=14)
# Re-fetch play-by-play for games this recent, in case of late corrections.
RECENT_GAMES = timedelta(days=3)


def run(client: HockeyTechClient, mode: Mode, today: date | None = None) -> None:
    today = today or datetime.now(UTC).date()
    league = client.league
    state = State.load(league)
    fetched, saved = Counter(), Counter()

    def save(endpoint: str, response: Json, params: dict, **partitions: int) -> None:
        fetched[endpoint] += 1
        if raw.save(league, endpoint, response, params, state, **partitions):
            saved[endpoint] += 1

    seasons_response, params = seasons.fetch(client)
    save(seasons.NAME, seasons_response, params)

    for season in seasons.seasons(seasons_response):
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
        for game in schedule.final_games(schedule_response):
            game_id = int(game["game_id"])
            partitions = {"season_id": season_id, "game_id": game_id}
            is_new = not state.has(play_by_play.NAME, partitions)
            is_recent = game["date_played"] >= recent_cutoff
            if mode == "full" or is_new or is_recent:
                response, params = play_by_play.fetch(client, game_id)
                save(play_by_play.NAME, response, params, **partitions)

    log.info(
        "%s run: fetched %d responses, %d new or changed",
        mode,
        sum(fetched.values()),
        sum(saved.values()),
    )
    for endpoint in sorted(fetched):
        log.info(
            "  %-14s fetched %4d  saved %4d",
            endpoint,
            fetched[endpoint],
            saved[endpoint],
        )

    if sum(saved.values()):
        uploaded, skipped = upload(league)
        log.info("%d uploaded, %d already in the Volume", uploaded, skipped)
        for endpoint, rows in load(league).items():
            if rows:
                log.info("  loaded %d rows into %s", rows, endpoint)


def _is_active(season: Json, today: date) -> bool:
    start = date.fromisoformat(season["start_date"])
    end = date.fromisoformat(season["end_date"])
    return start - ACTIVE_BEFORE <= today <= end + ACTIVE_AFTER
