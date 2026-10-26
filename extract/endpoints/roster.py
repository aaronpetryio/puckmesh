"""One team's roster in one season: players, plus the coaching staff as a nested list."""

NAME = "roster"


def fetch(client, season_id: int, team_id: int):
    params = {
        "feed": "modulekit",
        "view": "roster",
        "season_id": season_id,
        "team_id": team_id,
    }
    return client.get(**params), params
