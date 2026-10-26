"""Every game in one season, with scores and status once played."""

from extract.client import HockeyTechClient, Json

NAME = "schedule"


def fetch(client: HockeyTechClient, season_id: int) -> tuple[Json, dict]:
    params = {"feed": "modulekit", "view": "schedule", "season_id": season_id}
    return client.get(**params), params


def games(response: Json) -> list[Json]:
    return response["SiteKit"]["Schedule"]


def final_games(response: Json) -> list[Json]:
    """Games that have been played: only these have play-by-play."""
    return [g for g in games(response) if g["final"] == "1"]
