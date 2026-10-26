"""Every event in one game (shots, goals, penalties, faceoffs, ...), with rink coordinates."""

NAME = "play_by_play"


def fetch(client, game_id: int):
    params = {"feed": "gc", "tab": "pxpverbose", "game_id": game_id, "lang_code": "en"}
    return client.get(**params), params


def final_game_ids(schedule_response) -> list[int]:
    """Games with play-by-play to fetch: unplayed games have none."""
    return sorted(
        int(g["game_id"])
        for g in schedule_response["SiteKit"]["Schedule"]
        if g["final"] == "1"
    )
