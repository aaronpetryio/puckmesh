"""All seasons (regular, preseason, playoffs) the league has defined."""

NAME = "seasons"


def fetch(client):
    params = {"feed": "modulekit", "view": "seasons"}
    return client.get(**params), params


def season_ids(response) -> list[int]:
    return sorted(int(s["season_id"]) for s in response["SiteKit"]["Seasons"])
