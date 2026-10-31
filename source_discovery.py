"""Discover active live streams and recent YouTube VODs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "processed_videos.json"

DEFAULT_CHANNELS = [
    "https://www.youtube.com/@IShowSpeed",
    "https://www.youtube.com/@KaiCenat",
    "https://www.youtube.com/@CaseOh_",
]


def _load_processed() -> set[str]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))

        if isinstance(data, list):
            return {str(item) for item in data}

        if isinstance(data, dict):
            return {
                str(item)
                for item in data.get("video_ids", [])
            }

    except (OSError, json.JSONDecodeError, TypeError):
        pass

    return set()


def save_processed(video_ids: set[str]) -> None:
    STATE_FILE.write_text(
        json.dumps(
            {"video_ids": sorted(video_ids)},
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )


def _channel_url(value: str) -> str:
    """Normalize a channel URL by removing a trailing tab name."""
    value = value.strip().rstrip("/")

    for suffix in ("/videos", "/streams", "/live", "/shorts"):
        if value.endswith(suffix):
            value = value[:-len(suffix)].rstrip("/")

    return value


def _is_upcoming(entry: dict[str, Any]) -> bool:
    status = str(entry.get("live_status") or "").lower()

    return (
        status in {"is_upcoming", "upcoming"}
        or bool(entry.get("release_timestamp"))
        and status != "is_live"
        and not entry.get("is_live")
    )


def _is_live(entry: dict[str, Any]) -> bool:
    status = str(entry.get("live_status") or "").lower()

    return bool(entry.get("is_live")) or status == "is_live"


def discover_sources(
    config: dict[str, Any],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Prefer active live streams, then newest eligible VODs."""

    channels = config.get("discovery_channels") or DEFAULT_CHANNELS

    per_channel = max(
        1,
        int(config.get("discovery_scan_per_channel", 30)),
    )

    min_duration = max(
        60,
        int(config.get("min_source_duration_seconds", 600)),
    )

    max_age_days = max(
        1,
        int(config.get("max_source_age_days", 30)),
    )

    live_capture_seconds = max(
        120,
        int(config.get("live_capture_seconds", 480)),
    )

    processed = _load_processed()
    seen: set[str] = set()
    found: list[dict[str, Any]] = []

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=max_age_days)
    ).strftime("%Y%m%d")

    options = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "extract_flat": True,
        "playlistend": per_channel,
        "extractor_args": {
            "youtube": {
                "player_client": ["default"],
            }
        },
    }

    with YoutubeDL(options) as ydl:
        for raw_channel in channels:
            channel = _channel_url(str(raw_channel))

            if not channel or channel.startswith("#"):
                continue

            for tab in ("live", "streams", "videos"):
                page = f"{channel}/{tab}"

                try:
                    info = ydl.extract_info(
                        page,
                        download=False,
                    )
                except Exception as exc:
                    print(
                        f"Discovery warning for {page}: {exc}",
                        flush=True,
                    )
                    continue

                if not info:
                    continue

                entries = info.get("entries") or []

                if not entries and info.get("id"):
                    entries = [info]

                for entry in entries:
                    if not entry:
                        continue

                    video_id = entry.get("id")

                    if not video_id:
                        continue

                    video_id = str(video_id)

                    if video_id in processed or video_id in seen:
                        continue

                    if _is_upcoming(entry):
                        continue

                    is_live = _is_live(entry)

                    duration = entry.get("duration")

                    if not is_live:
                        if duration is None:
                            continue

                        try:
                            duration = float(duration)
                        except (TypeError, ValueError):
                            continue

                        if duration < min_duration:
                            continue

                    upload_date = str(
                        entry.get("upload_date") or ""
                    )

                    timestamp = entry.get("timestamp")

                    if not upload_date and timestamp:
                        try:
                            upload_date = datetime.fromtimestamp(
                                float(timestamp),
                                tz=timezone.utc,
                            ).strftime("%Y%m%d")
                        except (ValueError, TypeError, OSError):
                            upload_date = ""

                    if not is_live and upload_date:
                        if upload_date < cutoff:
                            continue

                    url = (
                        entry.get("webpage_url")
                        or entry.get("original_url")
                        or entry.get("url")
                    )

                    if not url or not str(url).startswith("http"):
                        url = (
                            "https://www.youtube.com/watch?v="
                            f"{video_id}"
                        )

                    found.append({
                        "id": video_id,
                        "url": str(url),
                        "title": (
                            entry.get("title")
                            or video_id
                        ),
                        "duration": (
                            int(float(duration))
                            if duration is not None
                            else None
                        ),
                        "upload_date": upload_date,
                        "is_live": is_live,
                        "live_capture_seconds": live_capture_seconds,
                        "channel": (
                            entry.get("channel")
                            or entry.get("uploader")
                            or channel
                        ),
                    })

                    seen.add(video_id)

    # LIVE first, then newest VODs.
    found.sort(
        key=lambda item: (
            not item["is_live"],
            item.get("upload_date") or "00000000",
        )
    )

    live_items = [
        item for item in found
        if item["is_live"]
    ]

    vod_items = [
        item for item in found
        if not item["is_live"]
    ]

    vod_items.sort(
        key=lambda item: item.get("upload_date") or "00000000",
        reverse=True,
    )

    found = live_items + vod_items

    cap = int(
        limit
        if limit is not None
        else config.get("max_sources_per_run", 2)
    )

    selected = found[:max(1, cap)]

    print(
        f"Auto-discovery: found {len(found)} eligible source(s); "
        f"selected {len(selected)}.",
        flush=True,
    )

    for item in selected:
        print(
            f"Selected {'LIVE' if item['is_live'] else 'VOD'}: "
            f"{item['title']} | {item['url']}",
            flush=True,
        )

    return selected


def discover_vods(
    config: dict[str, Any],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    return discover_sources(config, limit)
