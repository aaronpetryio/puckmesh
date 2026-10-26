"""Teams in one season. Names, logos, and conferences can change between seasons."""

from extract.client import HockeyTechClient, Json

NAME = "teams"


def fetch(client: HockeyTechClient, season_id: int) -> tuple[Json, dict]:
    params = {"feed": "modulekit", "view": "teamsbyseason", "season_id": season_id}
    return client.get(**params), params


def team_ids(response: Json) -> list[int]:
    return sorted(int(t["id"]) for t in response["SiteKit"]["Teamsbyseason"])
