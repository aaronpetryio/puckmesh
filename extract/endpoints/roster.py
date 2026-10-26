"""One team's roster in one season: players, and the coaching staff in a nested list."""

from extract.client import HockeyTechClient, Json

NAME = "roster"


def fetch(client: HockeyTechClient, season_id: int, team_id: int) -> tuple[Json, dict]:
    params = {
        "feed": "modulekit",
        "view": "roster",
        "season_id": season_id,
        "team_id": team_id,
    }
    return client.get(**params), params


def entries(response: Json) -> list[Json]:
    """Roster entries: one per player, plus one holding the coaching staff."""
    return response["SiteKit"]["Roster"]
