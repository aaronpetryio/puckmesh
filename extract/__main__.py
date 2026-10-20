"""Command line entry point.

    python -m extract seasons
    python -m extract schedule --season 8 [--season 9 ...]
    python -m extract schedule --all
    python -m extract upload
    python -m extract load
"""

import argparse

from dotenv import load_dotenv

from extract import raw
from extract.client import LEAGUES, HockeyTechClient
from extract.endpoints import schedule, seasons


def cmd_seasons(client: HockeyTechClient, args) -> None:
    response, params = seasons.fetch(client)
    path = raw.save(client.league, seasons.NAME, response, params)
    print(f"{len(seasons.season_ids(response))} seasons -> {path or 'unchanged, not saved'}")


def cmd_schedule(client: HockeyTechClient, args) -> None:
    if args.all:
        response, _ = seasons.fetch(client)
        season_ids = seasons.season_ids(response)
    else:
        season_ids = args.season
    for season_id in season_ids:
        response, params = schedule.fetch(client, season_id)
        path = raw.save(client.league, schedule.NAME, response, params, season_id=season_id)
        print(f"season {season_id}: {len(response['SiteKit']['Schedule'])} games -> {path or 'unchanged, not saved'}")


def cmd_upload(client: HockeyTechClient, args) -> None:
    from extract.upload import upload

    uploaded, skipped = upload(client.league)
    print(f"{uploaded} uploaded, {skipped} already in the Volume")


def cmd_load(client: HockeyTechClient, args) -> None:
    from extract.load import load

    for endpoint, rows in load(client.league).items():
        print(f"{endpoint}: {rows} new rows")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="python -m extract")
    parser.add_argument("--league", default="pwhl", choices=sorted(LEAGUES))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seasons", help="pull the season list").set_defaults(func=cmd_seasons)

    p = sub.add_parser("schedule", help="pull the schedule for one or more seasons")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--season", type=int, action="append", help="season_id (repeatable)")
    group.add_argument("--all", action="store_true", help="every season the API lists")
    p.set_defaults(func=cmd_schedule)

    sub.add_parser("upload", help="copy new local raw files to the Volume").set_defaults(func=cmd_upload)
    sub.add_parser("load", help="COPY INTO raw tables from the Volume").set_defaults(func=cmd_load)

    args = parser.parse_args()
    args.func(HockeyTechClient(args.league), args)


if __name__ == "__main__":
    main()
