"""All seasons (regular, preseason, playoffs) the league has defined."""

from extract.client import HockeyTechClient, Json

NAME = "seasons"


def fetch(client: HockeyTechClient) -> tuple[Json, dict]:
    params = {"feed": "modulekit", "view": "seasons"}
    return client.get(**params), params


def seasons(response: Json) -> list[Json]:
    return response["SiteKit"]["Seasons"]


def season_ids(response: Json) -> list[int]:
    return sorted(int(s["season_id"]) for s in seasons(response))
