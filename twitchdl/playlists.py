"""
Parse and manipulate m3u8 playlists.
"""

from dataclasses import dataclass
from os.path import splitext
from pathlib import Path
from typing import Generator, Iterable, List, Optional, OrderedDict, Set, Tuple
from urllib.parse import urlparse

import click
import m3u8

from twitchdl import utils
from twitchdl.output import bold, dim, print_table


@dataclass
class Playlist:
    name: str
    group_id: str
    resolution: Optional[str]
    url: str
    is_source: bool


@dataclass
class Vod:
    index: int
    """Ordinal number of the VOD in the playlist"""
    path: str
    """Path part of the VOD URL"""
    duration: float
    """Segment duration in seconds"""
    filename: str
    """File name to which to download the VOD"""


def parse_playlists(playlists_m3u8: str) -> List[Playlist]:
    def _parse(source: str) -> Generator[Playlist, None, None]:
        document = load_m3u8(source)

        for p in document.playlists:
            resolution = (
                "x".join(str(r) for r in p.stream_info.resolution)
                if p.stream_info.resolution
                else None
            )

            media = p.media[0]
            is_source = media.group_id == "chunked"
            yield Playlist(media.name, media.group_id, resolution, p.uri, is_source)

    playlists = list(_parse(playlists_m3u8))
    return sorted(playlists, key=_playlist_key)


def load_m3u8(playlist_m3u8: str) -> m3u8.M3U8:
    return m3u8.loads(playlist_m3u8)


def enumerate_vods(document: m3u8.M3U8) -> Generator[Vod, None, None]:
    for index, segment in enumerate(document.segments):
        assert segment.uri is not None
        assert segment.duration is not None
        _, ext = splitext(urlparse(segment.uri).path)
        filename = f"{index:05d}{ext}"
        yield Vod(index, segment.uri, segment.duration, filename)


def filter_vods(
    vods: Iterable[Vod],
    start: Optional[int] = None,
    end: Optional[int] = None,
) -> Tuple[List[Vod], Optional[float], Optional[float]]:
    filtered_vods: List[Vod] = []
    vod_start = 0

    # VODs are typically 10 seconds long, if the VODs don't align with the
    # requested start/end time, we'll need to tell ffmpeg to crop off bits from
    # the start or the end of the video.
    crop_start = None
    crop_end = None

    for vod in vods:
        vod_end = vod_start + vod.duration

        if start and start > vod_start and start < vod_end:
            crop_start = start - vod_start

        if end and end > vod_start and end < vod_end:
            crop_end = vod_end - end

        start_condition = not start or vod_end > start
        end_condition = not end or vod_start < end
        if start_condition and end_condition:
            filtered_vods.append(vod)

        vod_start = vod_end

    crop_duration = None
    if crop_end:
        total_duration = sum(v.duration for v in filtered_vods)
        crop_duration = total_duration - (crop_start or 0) - crop_end

    return filtered_vods, crop_start, crop_duration


def make_join_playlist(
    playlist: m3u8.M3U8,
    vods: List[Vod],
    targets: List[Path],
) -> m3u8.Playlist:
    """
    Make a modified playlist which references downloaded VODs
    Keep only the downloaded segments and skip the rest
    """
    org_segments = playlist.segments.copy()

    path_map = OrderedDict(zip([v.path for v in vods], targets))
    playlist.segments.clear()
    for segment in org_segments:
        if segment.uri in path_map:
            segment.uri = str(path_map[segment.uri].name)
            playlist.segments.append(segment)

    return playlist


def select_playlist(playlists: List[Playlist], quality: Optional[str]) -> Playlist:
    return (
        select_playlist_by_name(playlists, quality)
        if quality is not None
        else select_playlist_interactive(playlists)
    )


def select_playlist_by_name(playlists: List[Playlist], quality: str) -> Playlist:
    if quality == "source":
        for playlist in playlists:
            if playlist.is_source:
                return playlist
        raise click.ClickException("Source quality not found, please report an issue on github.")

    for playlist in playlists:
        if playlist.name == quality or playlist.group_id == quality:
            return playlist

    available = ", ".join([p.name for p in playlists])
    msg = f"Quality '{quality}' not found. Available qualities are: {available}"
    raise click.ClickException(msg)


def select_playlist_interactive(playlists: List[Playlist]) -> Playlist:
    playlists = sorted(playlists, key=_playlist_key)

    rows = [
        [
            f"{n + 1})",
            bold(playlist.name),
            dim(playlist.group_id),
            dim(playlist.resolution or ""),
        ]
        for n, playlist in enumerate(playlists)
    ]

    click.echo()
    print_table(rows, headers=["#", "Name", "Group ID", "Resolution"])

    default = 1
    for index, playlist in enumerate(playlists):
        if playlist.is_source:
            default = index + 1

    no = utils.read_int("\nChoose quality", min=1, max=len(playlists) + 1, default=default)
    playlist = playlists[no - 1]
    return playlist


MAX = 1_000_000


def _playlist_key(playlist: Playlist) -> int:
    """Attempt to sort playlists so that source quality is on top, audio only
    is on bottom and others are sorted descending by resolution."""
    if playlist.is_source:
        return 0

    if playlist.group_id == "audio_only":
        return MAX

    try:
        return MAX - int(playlist.name.split("p")[0])
    except Exception:
        pass

    return MAX


def get_init_sections(playlist: m3u8.M3U8) -> Set[str]:
    # TODO: we're ignoring initi_section.base_uri and bytes
    return set(
        segment.init_section.uri
        for segment in playlist.segments
        if segment.init_section is not None and segment.init_section.uri is not None
    )
