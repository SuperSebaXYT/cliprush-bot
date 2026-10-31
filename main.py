
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
            "streamlink", "--hls-duration", str(duration),
            source["url"], "best", "-o",
            str(work_dir / f"{source_id}.mp4"),
        ]
        run_command(command, f"Capturing LIVE: {source['title']}")
        output = work_dir / f"{source_id}.mp4"
        if not output.exists() or output.stat().st_size == 0:
            raise RuntimeError("LIVE capture produced no video file.")
        return output

    # Use the supplied YouTube session cookies first. GitHub Actions secrets
    # are injected at runtime; never print or commit their contents.
    cookie_text = os.environ.get("YOUTUBE_COOKIES", "").strip()
    cookie_file = work_dir / "youtube_cookies.txt"
    cookie_args = []

    if cookie_text:
        cookie_file.write_text(cookie_text, encoding="utf-8")
        cookie_args = ["--cookies", str(cookie_file)]
        print("YouTube cookies found; authenticated download will be tried first.", flush=True)
    else:
        print("YOUTUBE_COOKIES is empty; trying cookie-free clients.", flush=True)

    # Try authenticated mweb first, then alternate clients as fallbacks.
    client_modes = []
    if cookie_args:
        client_modes.append(("mweb with account cookies", "mweb", True))
    client_modes.extend([
        ("android_vr", "android_vr", False),
        ("tv_simply", "tv_simply", False),
        ("mweb without cookies", "mweb", False),
    ])
    format_selectors = [
        "best[ext=mp4]/best",
        "best",
        "bv*+ba/b",
    ]
    last_error = None

    try:
        for mode_name, player_client, use_cookies in client_modes:
            print(f"Starting YouTube download mode: {mode_name}", flush=True)
            for selector in format_selectors:
                print(
                    f"Trying yt-dlp format selector: {selector}",
                    flush=True,
                )
                command = [
                    sys.executable, "-m", "yt_dlp",
                    "--no-playlist",
                    "--retries", "3",
                    "--fragment-retries", "3",
                    "--extractor-retries", "3",
                    "--js-runtimes", "node",
                    "--extractor-args",
                    f"youtube:player_client={player_client}",
                ]
                if use_cookies:
                    command.extend(cookie_args)
                command.extend([
                    "--format", selector,
                    "--merge-output-format", "mp4",
                    "-o", str(output_template),
                    source["url"],
                ])
                try:
                    run_command(
                        command,
                        f"Downloading VOD ({mode_name}): {source['title']}",
                    )
                except Exception as exc:
                    last_error = exc
                    print(
                        f"Download mode '{mode_name}' failed for "
                        f"format '{selector}': {exc}",
                        flush=True,
                    )
                    continue

                candidates = [
                    path for path in work_dir.glob(f"{source_id}.*")
                    if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
                    and path.stat().st_size > 0
                ]
                if candidates:
                    return max(candidates, key=lambda path: path.stat().st_size)
    finally:
        # The cookie file is temporary and must never survive the download attempt.
        try:
            cookie_file.unlink(missing_ok=True)
        except OSError:
            pass

    raise RuntimeError(
        "All YouTube download modes failed. Check whether YOUTUBE_COOKIES "
        "contains a current Netscape-format cookie export. "
        f"Last error: {last_error}"
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


def score_with_groq(candidates: list[dict], config: dict) -> list[dict]:
    """Analyze small batches so long VOD transcripts do not exceed Groq payload limits."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key or not candidates:
        print("Groq boundary selection unavailable; using transcript fallback.", flush=True)
        return []

    import requests

    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    endpoint = "https://api.groq.com/openai/v1/chat/completions"

    # A 30-window request can exceed Groq's HTTP payload limit.
    # Keep each request deliberately small and combine the results locally.
    batch_size = max(1, min(4, int(config.get("groq_batch_size", 3))))
    ranked = []
    successful_batches = 0
    failed_batches = 0

    for batch_number, offset in enumerate(range(0, len(candidates), batch_size), start=1):
        batch = candidates[offset:offset + batch_size]
        compact = [
            {
                "id": i,
                "window_start": round(item["start"], 2),
                "window_end": round(item["end"], 2),
                "transcript": item["context"][:5000],
            }
            for i, item in enumerate(batch)
        ]

        prompt = (
            "You are an expert comedy editor for streamer YouTube Shorts. "
            "For each candidate transcript, decide whether it contains a genuinely funny "
            "complete moment. Find the WHOLE moment: include enough setup before the joke "
            "and the reaction/payoff after it. Do not cut in the middle of a sentence, "
            "joke, argument, or reaction. Do not choose ordinary conversation or hype "
            "without a funny event. Choose precise absolute start and end timestamps in "
            "seconds using the timestamps attached to each transcript line. "
            "The clip may be any length from 12 to 75 seconds; choose the natural length, "
            "not a fixed duration. Score comedy from 0 to 10. If no real funny moment "
            "exists, score below 5.5. Return ONLY valid JSON in this schema: "
            "{\"moments\":[{\"id\":0,\"score\":8.5,\"start\":123.4,"
            "\"end\":158.2,\"reason\":\"short explanation\"}]}. "
            "Only return moments with score at least 5.5. "
            "Candidates:\n" + json.dumps(compact, ensure_ascii=False)
        )

        try:
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You identify genuinely funny streamer moments. Return valid JSON only.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
                timeout=90,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(raw)

            for result in parsed.get("moments", []):
                idx = int(result["id"])
                if idx < 0 or idx >= len(batch):
                    continue

                original = batch[idx]
                score = float(result["score"])
                start_time = max(original["start"], float(result["start"]))
                end_time = min(original["end"], float(result["end"]))
                duration = end_time - start_time

                if score < 5.5 or duration < 12 or duration > 75:
                    continue

                ranked.append({
                    "start": start_time,
                    "end": end_time,
                    "score": score,
                    "text": original["text"],
                    "reason": str(result.get("reason", ""))[:180],
                })

            successful_batches += 1
            print(
                f"Groq batch {batch_number}: analyzed {len(batch)} window(s), "
                f"found {len(parsed.get('moments', []))} candidate moment(s).",
                flush=True,
            )

        except Exception as exc:
            failed_batches += 1
            print(
                f"WARNING: Groq batch {batch_number} failed: {exc}. "
                "Using local transcript scoring for this batch.",
                flush=True,
            )

            # Keep the pipeline useful if Groq is temporarily unavailable.
            # Use a 35-second section around the strongest point in each window.
            for original in batch:
                duration = min(35.0, original["end"] - original["start"])
                if duration < 12:
                    continue
                center = (original["start"] + original["end"]) / 2
                start_time = max(original["start"], center - duration / 2)
                end_time = min(original["end"], start_time + duration)
                ranked.append({
                    "start": start_time,
                    "end": end_time,
                    "score": float(original["score"]),
                    "text": original["text"],
                    "reason": "Local transcript-scoring fallback",
                })

    print(
        f"Groq analysis complete: {successful_batches} successful batch(es), "
        f"{failed_batches} failed batch(es), {len(ranked)} moment(s) returned "
        f"from {len(candidates)} windows using {model}.",
        flush=True,
    )
    return ranked

def select_clips(
    segments: list[dict],
    config: dict,
    video_duration: float,
) -> list[dict]:
    clips_per_source = max(1, int(config.get("clips_per_source", 1)))
    min_duration = int(config.get("min_clip_seconds", 12))
    max_duration = int(config.get("max_clip_seconds", 75))
    window_duration = 90
    window_step = 45

    if not segments:
        return []

    # Analyze overlapping 90-second transcript windows. The AI chooses
    # the actual in/out points, so clips are not forced to a fixed length.
    candidates = []
    window_start = 0.0
    while window_start < video_duration:
        window_end = min(video_duration, window_start + window_duration)
        window_segments = [
            item for item in segments
            if item["end"] > window_start and item["start"] < window_end
        ]
        if window_segments:
            transcript = "\n".join(
                f"[{item['start']:.2f}-{item['end']:.2f}] {item['text']}"
                for item in window_segments
            )
            candidates.append({
                "start": window_start,
                "end": window_end,
                "score": max(score_segment(item) for item in window_segments),
                "text": window_segments[len(window_segments) // 2]["text"],
                "context": transcript,
            })
        window_start += window_step

    # Keep a broad, non-duplicate shortlist for the semantic editor.
    candidates.sort(key=lambda item: item["score"], reverse=True)
    shortlist = []
    for item in candidates:
        if any(
            abs(item["start"] - old["start"]) < window_step
            for old in shortlist
        ):
            continue
        shortlist.append(item)
        if len(shortlist) >= 30:
            break

    if os.environ.get("GROQ_API_KEY", "").strip():
        ranked = score_with_groq(shortlist, config)
    else:
        print(
            "GROQ_API_KEY missing: automatic timing fallback is active, "
            "but semantic full-moment detection is unavailable.",
            flush=True,
        )
        ranked = []
        for item in shortlist:
            center = (item["start"] + item["end"]) / 2
            start_time = max(0, center - 17.5)
            end_time = min(video_duration, start_time + 35)
            ranked.append({
                "start": start_time,
                "end": end_time,
                "score": item["score"],
                "text": item["text"],
            })

    ranked = [
        item for item in ranked
        if min_duration <= item["end"] - item["start"] <= max_duration
    ]
    ranked.sort(key=lambda item: item["score"], reverse=True)

    selected = []
    minimum_score = float(config.get("minimum_humor_score", 5.5))
    for candidate in ranked:
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
        if item.get("reason"):
            print(
                f"Funny moment: {item['reason']} | "
                f"{item['start']:.1f}s-{item['end']:.1f}s "
                f"({item['end'] - item['start']:.1f}s) "
                f"| score {item['score']:.1f}/10",
                flush=True,
            )

    print(
        f"Automatic moment selection: {len(selected)} clip(s), "
        "variable duration.",
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
