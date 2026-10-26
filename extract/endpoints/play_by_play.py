"""Every event in one game (shots, goals, penalties, faceoffs, ...) with coordinates."""

from extract.client import HockeyTechClient, Json
from extract.endpoints import schedule

NAME = "play_by_play"


def fetch(client: HockeyTechClient, game_id: int) -> tuple[Json, dict]:
    params = {"feed": "gc", "tab": "pxpverbose", "game_id": game_id, "lang_code": "en"}
    return client.get(**params), params


def events(response: Json) -> list[Json]:
    return response["GC"]["Pxpverbose"]


def final_game_ids(schedule_response: Json) -> list[int]:
    """Games with play-by-play to fetch: unplayed games have none."""
    return sorted(int(g["game_id"]) for g in schedule.final_games(schedule_response))
