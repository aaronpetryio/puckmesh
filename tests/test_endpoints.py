from extract.endpoints import play_by_play, schedule, seasons, teams

SCHEDULE = {
    "SiteKit": {
        "Schedule": [
            {"game_id": "12", "final": "1"},
            {"game_id": "3", "final": "1"},
            {"game_id": "40", "final": "0"},
        ]
    }
}


def test_final_games_and_ids():
    assert [g["game_id"] for g in schedule.final_games(SCHEDULE)] == ["12", "3"]
    assert play_by_play.final_game_ids(SCHEDULE) == [3, 12]


def test_season_and_team_ids_are_sorted_ints():
    response = {"SiteKit": {"Seasons": [{"season_id": "8"}, {"season_id": "2"}]}}
    assert seasons.season_ids(response) == [2, 8]
    response = {"SiteKit": {"Teamsbyseason": [{"id": "6"}, {"id": "1"}]}}
    assert teams.team_ids(response) == [1, 6]
