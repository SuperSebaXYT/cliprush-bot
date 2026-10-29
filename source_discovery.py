"""Discover active live streams and recent VODs from configured YouTube channels."""
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
        return set(data if isinstance(data, list) else data.get("video_ids", []))
    except (OSError, json.JSONDecodeError, TypeError):
        return set()

def save_processed(video_ids: set[str]) -> None:
    STATE_FILE.write_text(json.dumps({"video_ids": sorted(video_ids)}, indent=2) + "\n", encoding="utf-8")

def discover_sources(config: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
    """Prefer active live streams, then recent VODs. Upcoming streams are skipped."""
    channels = config.get("discovery_channels") or DEFAULT_CHANNELS
    per_channel = max(1, int(config.get("discovery_scan_per_channel", 30)))
    min_duration = max(60, int(config.get("min_source_duration_seconds", 600)))
    max_age_days = max(1, int(config.get("max_source_age_days", 30)))
    live_capture_seconds = max(120, int(config.get("live_capture_seconds", 480)))
    processed = _load_processed()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y%m%d")
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    options = {"skip_download": True, "quiet": True, "no_warnings": True, "ignoreerrors": True,
               "playlistend": per_channel, "extractor_args": {"youtube": {"player_client": ["default"]}}}
    with YoutubeDL(options) as ydl:
        for channel in channels:
            channel = str(channel).strip().rstrip("/")
            if not channel or channel.startswith("#"):
                continue
            # Check live endpoint first so active broadcasts are not buried beneath uploads.
            for tab in ("live", "streams", "videos"):
                page = f"{channel}/{tab}"
                try:
                    info = ydl.extract_info(page, download=False)
                except Exception as exc:
                    print(f"Discovery warning for {page}: {exc}", flush=True)
                    continue
                # The /live endpoint can resolve directly to one video instead of a playlist.
                entries = (info or {}).get("entries") or ([info] if (info or {}).get("id") else [])
                for entry in entries:
                    if not entry:
                        continue
                    video_id = entry.get("id")
                    if not video_id or video_id in processed or video_id in seen:
                        continue
                    live_status = str(entry.get("live_status") or "").lower()
                    is_live = bool(entry.get("is_live")) or live_status == "is_live"
                    if live_status in {"is_upcoming", "upcoming"} or entry.get("release_timestamp") and not is_live and live_status == "is_upcoming":
                        continue
                    duration = entry.get("duration")
                    # Active broadcasts often have no known duration; allow them and record a bounded sample.
                    if not is_live and (duration is None or float(duration) < min_duration):
                        continue
                    upload_date = str(entry.get("upload_date") or "")
                    if not is_live and upload_date and upload_date < cutoff:
                        continue
                    url = entry.get("webpage_url") or entry.get("url")
                    if not url or not str(url).startswith("http"):
                        url = f"https://www.youtube.com/watch?v={video_id}"
                    found.append({"id": video_id, "url": url, "title": entry.get("title") or video_id,
                                  "duration": int(float(duration)) if duration else None,
                                  "upload_date": upload_date, "is_live": is_live,
                                  "live_capture_seconds": live_capture_seconds,
                                  "channel": entry.get("channel") or entry.get("uploader") or channel})
                    seen.add(video_id)
    # Active lives first, then newest VODs. Keep live sources eligible for later runs until successfully handled.
    found.sort(key=lambda x: (not x["is_live"], x.get("upload_date") or "00000000"), reverse=False)
    cap = int(limit if limit is not None else config.get("max_sources_per_run", 2))
    selected = found[:max(1, cap)]
    print(f"Auto-discovery: found {len(found)} eligible source(s); selected {len(selected)}.", flush=True)
    for item in selected:
        print(f"Selected {'LIVE' if item['is_live'] else 'VOD'}: {item['title']} | {item['url']}", flush=True)
    return selected

# Backwards-compatible name for any existing imports.
def discover_vods(config: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
    return discover_sources(config, limit)
