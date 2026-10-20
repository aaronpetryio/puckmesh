"""Every game in one season, with scores and status once played."""

NAME = "schedule"


def fetch(client, season_id: int):
    params = {"feed": "modulekit", "view": "schedule", "season_id": season_id}
    return client.get(**params), params
