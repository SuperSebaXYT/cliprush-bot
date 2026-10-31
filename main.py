
from __future__ import annotations

import json
import os
import re
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


def run_command(
    command: list[str],
    description: str,
) -> None:
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

    cookies_path = work_dir / "youtube_cookies.txt"
    cookies = os.environ.get("YOUTUBE_COOKIES", "").strip()

    cookie_args = []

    if cookies:
        cookies_path.write_text(cookies, encoding="utf-8")
        cookie_args = ["--cookies", str(cookies_path)]
        print("Using YOUTUBE_COOKIES for yt-dlp.", flush=True)
    else:
        print(
            "WARNING: YOUTUBE_COOKIES is not configured. "
            "YouTube may block downloads.",
            flush=True,
        )

    # Najpierw próbujemy pojedynczego formatu.
    # Potem standardowego połączenia obrazu i dźwięku.
    format_selectors = [
        "best[ext=mp4]/best",
        "best",
        "bv*+ba/b",
    ]

    last_error = None

    try:
        for selector in format_selectors:
            print(
                f"Trying yt-dlp format selector: {selector}",
                flush=True,
            )

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
                "--extractor-retries",
                "3",
                "--js-runtimes",
                "node",
                "--format",
                selector,
                "--merge-output-format",
                "mp4",
                "-o",
                str(output_template),
            ]

            command.extend(cookie_args)
            command.append(source["url"])

            try:
                run_command(
                    command,
                    f"Downloading VOD: {source['title']}",
                )
            except Exception as exc:
                last_error = exc
                print(
                    f"Format selector failed: {selector}. "
                    f"Trying next option.",
                    flush=True,
                )

                # Capture the formats yt-dlp can actually see. This makes
                # YouTube client / cookie / PO-token failures diagnosable.
                diagnostic_command = [
                    sys.executable,
                    "-m",
                    "yt_dlp",
                    "--no-playlist",
                    "--no-warnings",
                    "--list-formats",
                    "--js-runtimes",
                    "node",
                ]
                diagnostic_command.extend(cookie_args)
                diagnostic_command.append(source["url"])

                try:
                    run_command(
                        diagnostic_command,
                        f"Diagnosing available formats: {source['title']}",
                    )
                except Exception as diagnostic_error:
                    print(
                        f"Format diagnostic failed: {diagnostic_error}",
                        flush=True,
                    )
                continue

            candidates = [
                path
                for path in work_dir.glob(f"{source_id}.*")
                if path.suffix.lower() in {
                    ".mp4",
                    ".mkv",
                    ".webm",
                    ".mov",
                }
                and path.stat().st_size > 0
            ]

            if candidates:
                return max(
                    candidates,
                    key=lambda path: path.stat().st_size,
                )

        raise RuntimeError(
            f"All yt-dlp format selectors failed. Last error: {last_error}"
        )

    finally:
        if cookies_path.exists():
            try:
                cookies_path.unlink()
            except OSError:
                print(
                    "WARNING: Could not remove temporary cookies file.",
                    flush=True,
                )


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
    """Fallback score used when the semantic humor model is unavailable."""
    text = segment["text"].lower()
    words = re.findall(r"[a-z']+", text)
    score = 0.0

    reaction_phrases = [
        "no way", "oh my god", "what the hell", "what the fuck",
        "are you serious", "you gotta be kidding", "bro what",
        "i'm dead", "im dead", "that's crazy", "thats crazy",
        "get out", "shut up", "i can't", "i cannot",
        "what just happened", "did you see that",
    ]
    laugh_terms = [
        "haha", "hahaha", "lol", "lmao", "laughing",
        "funny", "joke", "kidding", "bruh",
    ]
    surprise_terms = [
        "insane", "crazy", "wild", "unbelievable", "impossible",
        "screaming", "scream", "bro", "nah", "wait",
    ]
    flat_terms = [
        "welcome back", "today we're", "make sure to subscribe",
        "don't forget to like", "sponsor", "check out",
    ]

    for phrase in reaction_phrases:
        if phrase in text:
            score += 3.0
    for term in laugh_terms:
        if term in text:
            score += 2.5
    for term in surprise_terms:
        if term in words:
            score += 0.8

    if "?" in text or "!" in text:
        score += 0.8
    if len(words) >= 7:
        score += 0.5
    if len(words) <= 2:
        score -= 1.0
    if any(term in text for term in flat_terms):
        score -= 3.0

    return score


def score_with_gemini(candidates: list[dict]) -> list[dict]:
    """Rank transcript windows for comedy using Gemini when an API key exists."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or not candidates:
        print("Gemini humor ranking unavailable; using transcript fallback.", flush=True)
        return candidates

    import requests

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    compact = [
        {"id": i, "transcript": item["context"][:1800]}
        for i, item in enumerate(candidates)
    ]
    prompt = (
        "You are ranking short streamer VOD moments for genuinely funny YouTube Shorts. "
        "Score each transcript from 0 to 10 for comedy potential. Reward an actual joke, "
        "unexpected absurdity, funny argument, sharp punchline, embarrassing mishap, "
        "or a strong comedic reaction. Do NOT reward generic hype words, ordinary "
        "conversation, greetings, repeated profanity, or a question by itself. "
        "Prefer a complete setup-payoff moment with enough context. "
        "Return ONLY valid JSON: {\"scores\":[{\"id\":0,\"score\":0,\"reason\":\"short reason\"}]}. "
        "Score these candidates:\n" + json.dumps(compact, ensure_ascii=False)
    )

    try:
        response = requests.post(
            endpoint,
            params={"key": api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            },
            timeout=45,
        )
        response.raise_for_status()
        body = response.json()
        raw = body["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(raw)
        scores = {
            int(item["id"]): item
            for item in parsed.get("scores", [])
            if "id" in item and "score" in item
        }
        for i, candidate in enumerate(candidates):
            result = scores.get(i)
            if result:
                candidate["score"] = float(result["score"])
                candidate["reason"] = str(result.get("reason", ""))[:180]
        print(
            f"Gemini humor ranking scored {len(scores)}/{len(candidates)} candidates.",
            flush=True,
        )
    except Exception as exc:
        print(f"WARNING: Gemini humor ranking failed: {exc}; using fallback scores.", flush=True)

    return candidates


def select_clips(
    segments: list[dict],
    config: dict,
    video_duration: float,
) -> list[dict]:
    clips_per_source = max(1, int(config.get("clips_per_source", 1)))
    target_duration = int(config.get("clip_duration_seconds", 35))
    min_duration = int(config.get("min_clip_seconds", 20))
    max_duration = int(config.get("max_clip_seconds", 55))

    candidates = []
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

        context = " ".join(
            item["text"]
            for item in segments
            if item["end"] > start - 8 and item["start"] < end + 8
        )
        candidates.append({
            "start": start,
            "end": end,
            "score": score_segment(segment),
            "text": segment["text"],
            "context": context,
        })

    # Remove near-duplicate candidate windows before calling the model.
    candidates.sort(key=lambda item: item["score"], reverse=True)
    shortlist = []
    for item in candidates:
        if any(
            abs(item["start"] - old["start"]) < target_duration * 0.55
            for old in shortlist
        ):
            continue
        shortlist.append(item)
        if len(shortlist) >= 24:
            break

    shortlist = score_with_gemini(shortlist)
    shortlist.sort(key=lambda item: item["score"], reverse=True)

    selected = []
    minimum_score = float(config.get("minimum_humor_score", 5.5))
    for candidate in shortlist:
        if candidate["score"] < minimum_score:
            continue
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

    for item in selected:
        item.pop("context", None)
        if item.get("reason"):
            print(
                f"Humor pick: {item['reason']} (score {item['score']:.1f}/10)",
                flush=True,
            )

    print(
        f"Humor selector: {len(selected)} clip(s) passed "
        f"minimum score {minimum_score:.1f}/10.",
        flush=True,
    )
    return sorted(selected, key=lambda item: item["start"])

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
