from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from faster_whisper import WhisperModel
from source_discovery import (
    discover_sources,
    _load_processed,
    save_processed,
)

ROOT = Path(__file__).resolve().parent


def load_config() -> dict:
    path = ROOT / "config.json"
    if not path.exists():
        raise FileNotFoundError("Nie znaleziono config.json")

    return json.loads(path.read_text(encoding="utf-8"))


def get_manual_sources(limit: int) -> list[dict]:
    path = ROOT / "sources.txt"

    if not path.exists():
        return []

    results = []

    for line in path.read_text(encoding="utf-8").splitlines():
        url = line.strip()

        if not url or url.startswith("#"):
            continue

        match = re.search(
            r"(?:v=|youtu\.be/|/live/)([A-Za-z0-9_-]{11})",
            url,
        )

        video_id = match.group(1) if match else url

        results.append({
            "id": video_id,
            "url": url,
            "title": video_id,
            "is_live": False,
        })

        if len(results) >= limit:
            break

    return results


def get_sources(config: dict) -> list[dict]:
    limit = max(1, int(config.get("max_sources_per_run", 2)))
    sources = []

    if config.get("auto_discovery_enabled", True):
        try:
            sources = discover_sources(config, limit=limit)
        except Exception as exc:
            print(
                f"ERROR: Automatic discovery failed: {exc}",
                flush=True,
            )

    known_ids = {item["id"] for item in sources}

    for item in get_manual_sources(limit):
        if item["id"] not in known_ids and len(sources) < limit:
            sources.append(item)
            known_ids.add(item["id"])

    print(f"Total sources selected: {len(sources)}", flush=True)

    return sources


def run_command(command: list[str], description: str) -> None:
    print(f"\n{description}", flush=True)
    print("COMMAND:", " ".join(command), flush=True)

    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    if result.stdout:
        print(result.stdout[-12000:], flush=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"{description} failed with exit code {result.returncode}"
        )


def download_source(
    source: dict,
    work_dir: Path,
    config: dict,
) -> Path:
    source_id = source["id"]
    output_template = work_dir / f"{source_id}.%(ext)s"

    if source.get("is_live"):
        duration = int(
            source.get(
                "live_capture_seconds",
                config.get("live_capture_seconds", 480),
            )
        )

        command = [
            "streamlink",
            "--hls-duration",
            str(duration),
            source["url"],
            "best",
            "-o",
            str(work_dir / f"{source_id}.mp4"),
        ]

        run_command(command, f"Capturing LIVE: {source['title']}")

        output = work_dir / f"{source_id}.mp4"

        if not output.exists() or output.stat().st_size == 0:
            raise RuntimeError("LIVE capture produced no video file.")

        return output

    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--no-warnings",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "-f",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "-o",
        str(output_template),
    ]

    cookies = os.environ.get("YOUTUBE_COOKIES", "").strip()

    if cookies:
        cookies_path = work_dir / "youtube_cookies.txt"
        cookies_path.write_text(cookies, encoding="utf-8")
        command.extend(["--cookies", str(cookies_path)])
        print("Using YOUTUBE_COOKIES for yt-dlp.", flush=True)
    else:
        print(
            "WARNING: YOUTUBE_COOKIES is not configured. "
            "YouTube may block downloads.",
            flush=True,
        )

    command.append(source["url"])

    run_command(command, f"Downloading VOD: {source['title']}")

    candidates = list(work_dir.glob(f"{source_id}.*"))

    candidates = [
        path for path in candidates
        if path.suffix.lower() in {
            ".mp4", ".mkv", ".webm", ".mov"
        }
        and path.stat().st_size > 0
    ]

    if not candidates:
        raise RuntimeError(
            f"yt-dlp finished but no video file was found for {source_id}"
        )

    return max(candidates, key=lambda path: path.stat().st_size)


def transcribe_video(
    video_path: Path,
    config: dict,
) -> list[dict]:
    model_name = config.get("whisper_model", "small")

    print(f"Loading Whisper model: {model_name}", flush=True)

    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
    )

    language = config.get("language", "en")

    if language == "auto":
        language = None

    segments, info = model.transcribe(
        str(video_path),
        language=language,
        vad_filter=True,
        word_timestamps=True,
    )

    print(
        f"Detected language: {info.language} "
        f"({info.language_probability:.2f})",
        flush=True,
    )

    result = []

    for segment in segments:
        text = segment.text.strip()

        if not text:
            continue

        result.append({
            "start": float(segment.start),
            "end": float(segment.end),
            "text": text,
        })

    print(f"Transcribed segments: {len(result)}", flush=True)

    return result


def score_segment(segment: dict) -> float:
    text = segment["text"].lower()

    score = 0.0

    hooks = [
        "what",
        "why",
        "how",
        "no way",
        "oh my god",
        "wait",
        "bro",
        "crazy",
        "insane",
        "look",
        "listen",
        "impossible",
        "actually",
        "never",
        "help",
        "stop",
    ]

    for hook in hooks:
        if hook in text:
            score += 2.0

    if "?" in text:
        score += 1.5

    if "!" in text:
        score += 1.0

    if len(text.split()) >= 8:
        score += 1.0

    if len(text.split()) <= 2:
        score -= 1.0

    return score


def select_clips(
    segments: list[dict],
    config: dict,
    video_duration: float,
) -> list[dict]:
    clips_per_source = max(
        1,
        int(config.get("clips_per_source", 2)),
    )

    target_duration = int(
        config.get("clip_duration_seconds", 35)
    )

    min_duration = int(
        config.get("min_clip_seconds", 20)
    )

    max_duration = int(
        config.get("max_clip_seconds", 55)
    )

    windows = []

    for segment in segments:
        center = (segment["start"] + segment["end"]) / 2

        start = max(0, center - target_duration / 2)
        end = min(video_duration, start + target_duration)

        if end - start < min_duration:
            continue

        if end - start > max_duration:
            end = start + max_duration

        if end > video_duration:
            end = video_duration
            start = max(0, end - target_duration)

        if end - start < min_duration:
            continue

        windows.append({
            "start": start,
            "end": end,
            "score": score_segment(segment),
            "text": segment["text"],
        })

    windows.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    selected = []

    for candidate in windows:
        overlaps = any(
            not (
                candidate["end"] <= existing["start"]
                or candidate["start"] >= existing["end"]
            )
            for existing in selected
        )

        if overlaps:
            continue

        selected.append(candidate)

        if len(selected) >= clips_per_source:
            break

    selected.sort(key=lambda item: item["start"])

    return selected


def create_srt(
    segments: list[dict],
    clip_start: float,
    clip_end: float,
    output_path: Path,
) -> None:
    def timestamp(seconds: float) -> str:
        milliseconds = int(seconds * 1000)

        hours = milliseconds // 3600000
        milliseconds %= 3600000

        minutes = milliseconds // 60000
        milliseconds %= 60000

        secs = milliseconds // 1000
        milliseconds %= 1000

        return (
            f"{hours:02}:{minutes:02}:{secs:02},"
            f"{milliseconds:03}"
        )

    lines = []
    index = 1

    for segment in segments:
        start = max(segment["start"], clip_start)
        end = min(segment["end"], clip_end)

        if end <= start:
            continue

        lines.extend([
            str(index),
            f"{timestamp(start - clip_start)} --> "
            f"{timestamp(end - clip_start)}",
            segment["text"],
            "",
        ])

        index += 1

    output_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def render_clip(
    video_path: Path,
    clip: dict,
    segments: list[dict],
    output_path: Path,
    config: dict,
) -> None:
    start = float(clip["start"])
    duration = float(clip["end"] - clip["start"])

    srt_path = output_path.with_suffix(".srt")

    create_srt(
        segments,
        start,
        float(clip["end"]),
        srt_path,
    )

    subtitle_path = str(srt_path.resolve())
    subtitle_path = subtitle_path.replace("\\", "/")
    subtitle_path = subtitle_path.replace(":", "\\:")

    video_filter = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"subtitles='{subtitle_path}'"
    )

    command = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start),
        "-i",
        str(video_path),
        "-t",
        str(duration),
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    run_command(command, f"Rendering {output_path.name}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg did not create the output clip.")


def upload_to_youtube(
    video_path: Path,
    config: dict,
) -> None:
    if not config.get("publish", False):
        print("Publishing disabled. Keeping clip as artifact.", flush=True)
        return

    token_json = os.environ.get("YOUTUBE_TOKEN_JSON", "").strip()

    if not token_json:
        raise RuntimeError(
            "publish=true but YOUTUBE_TOKEN_JSON is missing."
        )

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    credentials = Credentials.from_authorized_user_info(
        json.loads(token_json),
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
    )

    title_prefix = config.get("title_prefix", "ClipRush")
    title = f"{title_prefix} | {video_path.stem}"

    description = config.get("description", "")
    tags = config.get("tags", [])
    privacy = config.get("privacy_status", "private")

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": str(config.get("category_id", "20")),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = request.execute()

    print(
        f"Uploaded to YouTube: {response.get('id')}",
        flush=True,
    )


def main() -> None:
    config = load_config()

    output_dir = ROOT / config.get("output_dir", "output")
    work_dir = ROOT / config.get("work_dir", "work")

    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    sources = get_sources(config)

    if not sources:
        print(
            "No eligible sources discovered and no manual source URLs configured.",
            flush=True,
        )
        return

    processed = _load_processed()

    for source in sources:
        source_id = source["id"]

        print(
            f"\nProcessing {'LIVE' if source.get('is_live') else 'VOD'}: "
            f"{source.get('title', source_id)}",
            flush=True,
        )

        try:
            video_path = download_source(
                source,
                work_dir,
                config,
            )

            import subprocess

            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            video_duration = float(probe.stdout.strip())

            segments = transcribe_video(
                video_path,
                config,
            )

            clips = select_clips(
                segments,
                config,
                video_duration,
            )

            if not clips:
                print(
                    f"No suitable clips found for {source_id}.",
                    flush=True,
                )
                continue

            for index, clip in enumerate(clips, start=1):
                output_path = output_dir / (
                    f"{source_id}_clip_{index}.mp4"
                )

                render_clip(
                    video_path,
                    clip,
                    segments,
                    output_path,
                    config,
                )

                upload_to_youtube(
                    output_path,
                    config,
                )

            if not source.get("is_live"):
                processed.add(source_id)
                save_processed(processed)

        except Exception as exc:
            print(
                f"ERROR processing {source_id}: {exc}",
                flush=True,
            )

        finally:
            for path in work_dir.glob(f"{source_id}.*"):
                try:
                    path.unlink()
                except OSError:
                    pass

    print("\nClipping pipeline finished.", flush=True)


if __name__ == "__main__":
    main()
