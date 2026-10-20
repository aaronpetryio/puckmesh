"""Teams in one season. Names, logos, and conferences can change between seasons."""

NAME = "teams"


def fetch(client, season_id: int):
    params = {"feed": "modulekit", "view": "teamsbyseason", "season_id": season_id}
    return client.get(**params), params


def team_ids(response) -> list[int]:
    return sorted(int(t["id"]) for t in response["SiteKit"]["Teamsbyseason"])
