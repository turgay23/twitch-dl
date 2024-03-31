import sys

import click

from twitchdl import twitch
from twitchdl.exceptions import ConsoleError
from twitchdl.output import print_log, print_paged_videos, print_video, print_json, print_video_compact


def videos(
    channel_name: str,
    *,
    all: bool,
    compact: bool,
    games: list[str],
    json: bool,
    limit: int | None,
    pager: int | None,
    sort: twitch.VideosSort,
    type: twitch.VideosType,
):
    game_ids = _get_game_ids(games)

    # Set different defaults for limit for compact display
    limit = limit or (40 if compact else 10)

    # Ignore --limit if --pager or --all are given
    max_videos = sys.maxsize if all or pager else limit

    total_count, generator = twitch.channel_videos_generator(
        channel_name, max_videos, sort, type, game_ids=game_ids)

    if json:
        videos = list(generator)
        print_json({
            "count": len(videos),
            "totalCount": total_count,
            "videos": videos
        })
        return

    if total_count == 0:
        click.echo("No videos found")
        return

    if pager:
        print_paged_videos(generator, pager, total_count)
        return

    count = 0
    for video in generator:
        if compact:
            print_video_compact(video)
        else:
            click.echo()
            print_video(video)
        count += 1

    click.echo()
    click.echo("-" * 80)
    click.echo(f"Videos 1-{count} of {total_count}")

    if total_count > count:
        click.secho(
            "\nThere are more videos. Increase the --limit, use --all or --pager to see the rest.",
            dim=True
        )


def _get_game_ids(names: list[str]) -> list[str]:
    if not names:
        return []

    game_ids = []
    for name in names:
        print_log(f"Looking up game '{name}'...")
        game_id = twitch.get_game_id(name)
        if not game_id:
            raise ConsoleError(f"Game '{name}' not found")
        game_ids.append(int(game_id))

    return game_ids
