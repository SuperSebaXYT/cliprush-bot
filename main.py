import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from faster_whisper import WhisperModel
from source_discovery import discover_sources, _load_processed, save_processed

ROOT = Path(__file__).resolve().parent

def run(cmd):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), check=True)

def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

def get_manual_sources(limit):
    path = ROOT / "sources.txt"
    if not path.exists():
        return []
    return [x.strip() for x in path.read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.strip().startswith("#")][:limit]


def get_sources(cfg):
    limit = int(cfg.get("max_sources_per_run", 2))
    sources = []
    if cfg.get("auto_discovery_enabled", False):
        sources.extend(discover_sources(cfg, limit=limit))
    existing_urls = {item["url"] for item in sources}
    if len(sources) < limit:
        for url in get_manual_sources(limit):
            if url not in existing_urls:
                sources.append({"url": url, "is_live": False, "id": url})
                existing_urls.add(url)
            if len(sources) >= limit:
                break
    return sources[:limit]

def download_source(source, work_dir, cfg):
    url = source["url"]
    template = work_dir / "source.%(ext)s"
    if source.get("is_live"):
        # Record only a bounded live segment, rather than waiting for a broadcast that may run for hours.
        duration = max(120, int(source.get("live_capture_seconds") or cfg.get("live_capture_seconds", 480)))
        hh, rem = divmod(duration, 3600); mm, ss = divmod(rem, 60)
        duration_arg = f"{hh:02d}:{mm:02d}:{ss:02d}"
        run(["streamlink", "--hls-duration", duration_arg, url, "best", "-o", str(work_dir / "source.ts")])
    else:
        run([sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings",
             "-f", "bv*+ba/b", "--merge-output-format", "mp4", "-o", str(template), url])
    candidates = [p for p in sorted(work_dir.glob("source.*"))
                  if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".ts"} and p.stat().st_size > 0]
    if not candidates:
        raise RuntimeError("No source video was found after download/recording.")
    return candidates[0]

def probe_duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)], text=True).strip()
    return float(out)

def normalize_text(text):
    return re.sub(r"\s+", " ", text.lower()).strip()

def score_segment(text, avg_words):
    t = normalize_text(text)
    if len(t) < 35:
        return -3
    hooks = ["what", "no way", "oh my god", "insane", "crazy", "bro", "wait", "help", "finally",
             "lets go", "let's go", "unbelievable", "holy", "wtf", "clutch", "win", "lost",
             "nie", "co", "serio", "niemożliwe", "wygra", "przegra", "masakra"]
    score = min(len(t) / 90, 2.0) + min(avg_words / 3.0, 2.0)
    score += sum(1.25 for phrase in hooks if phrase in t)
    score += 0.5 if "?" in text or "!" in text else 0
    score -= 1.0 if len(t) > 550 else 0
    return score

def transcribe(path, cfg):
    model = WhisperModel(cfg.get("whisper_model", "small"), device="cpu", compute_type="int8")
    language = cfg.get("language", "auto")
    segments, info = model.transcribe(str(path), language=None if language == "auto" else language, vad_filter=True)
    return list(segments), info

def choose_windows(segments, duration, cfg):
    target = int(cfg["clip_duration_seconds"])
    min_len = int(cfg["min_clip_seconds"])
    max_len = int(cfg["max_clip_seconds"])
    step = max(5, target // 3)
    windows = []
    start = 0
    while start + min_len < duration:
        end = min(duration, start + target)
        chosen = [s for s in segments if s.end > start and s.start < end]
        text = " ".join(s.text.strip() for s in chosen).strip()
        words = sum(len(s.text.split()) for s in chosen)
        if end - start >= min_len and text:
            windows.append({"start": start, "end": min(end, start + max_len),
                            "text": text, "score": score_segment(text, words / max(end-start, 1))})
        start += step
    selected = []
    for item in sorted(windows, key=lambda x: x["score"], reverse=True):
        if all(item["end"] <= old["start"] or item["start"] >= old["end"] for old in selected):
            selected.append(item)
        if len(selected) >= int(cfg["clips_per_source"]):
            break
    return sorted(selected, key=lambda x: x["start"])

def make_srt(text, out_path, duration):
    words = text.split() or ["Highlight"]
    chunks = [" ".join(words[i:i+6]) for i in range(0, len(words), 6)]
    step = duration / max(len(chunks), 1)
    def stamp(sec):
        ms = int(max(0, sec) * 1000)
        h, rem = divmod(ms, 3600000); m, rem = divmod(rem, 60000); s, ms = divmod(rem, 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
    lines = []
    for i, chunk in enumerate(chunks):
        lines += [str(i+1), f"{stamp(i*step)} --> {stamp(min(duration, (i+1)*step))}", chunk, ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")

def render_clip(source, item, dest):
    start, end = float(item["start"]), float(item["end"])
    duration = end - start
    srt = dest.with_suffix(".srt")
    make_srt(item["text"], srt, duration)
    sub = str(srt.resolve()).replace("\\", "/").replace(":", r"\:")
    vf = f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,subtitles='{sub}':force_style='FontName=Arial,FontSize=18,Outline=2,Shadow=1,Alignment=2,MarginV=170'"
    run(["ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(source), "-t", f"{duration:.2f}",
         "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest)])
    srt.unlink(missing_ok=True)

def upload(path, cfg, index):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    raw = os.environ.get("YOUTUBE_TOKEN_JSON")
    if not raw:
        raise RuntimeError("publish=true but GitHub Secret YOUTUBE_TOKEN_JSON is missing.")
    creds = Credentials.from_authorized_user_info(json.loads(raw), ["https://www.googleapis.com/auth/youtube.upload"])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    service = build("youtube", "v3", credentials=creds, cache_discovery=False)
    prefix = cfg.get("title_prefix", "ClipRush").strip()
    title = f"{prefix} Highlight #{index} #Shorts".strip()[:100]
    body = {"snippet": {"title": title, "description": cfg.get("description", "") + "\n\n#Shorts",
             "tags": cfg.get("tags", ["shorts", "highlights"]), "categoryId": str(cfg.get("category_id", "20"))},
            "status": {"privacyStatus": cfg.get("privacy_status", "private"), "selfDeclaredMadeForKids": False}}
    response = service.videos().insert(part="snippet,status", body=body,
        media_body=MediaFileUpload(str(path), mimetype="video/mp4", resumable=True)).execute()
    print("Uploaded video ID:", response.get("id"), flush=True)

def main():
    cfg = load_config()
    work_root = ROOT / cfg.get("work_dir", "work")
    out_root = ROOT / cfg.get("output_dir", "output")
    work_root.mkdir(exist_ok=True); out_root.mkdir(exist_ok=True)
    sources = get_sources(cfg)
    if not sources:
        print("No eligible VODs discovered and no manual source URLs configured.")
        return
    processed = _load_processed()
    index = 0
    for source_i, source_info in enumerate(sources, 1):
        url = source_info["url"]
        work = work_root / f"source_{source_i}"
        work.mkdir(parents=True, exist_ok=True)
        try:
            video = download_source(source_info, work, cfg)
            duration = probe_duration(video)
            segments, _ = transcribe(video, cfg)
            for item in choose_windows(segments, duration, cfg):
                index += 1
                dest = out_root / f"clip_{source_i}_{index}.mp4"
                render_clip(video, item, dest)
                dest.with_suffix(".json").write_text(json.dumps({"source_url": url, **item},
                    ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Rendered {dest}; score={item['score']:.2f}", flush=True)
                if cfg.get("publish", False):
                    upload(dest, cfg, index)
            # Mark the source only after the full source pipeline succeeds, preventing repeats.
            video_id = str(source_info.get("id") or (url.split("v=", 1)[1].split("&", 1)[0] if "v=" in url else url.rstrip("/").split("/")[-1]))
            # A live stream is revisited on the next scheduled run, so don't permanently mark it processed.
            if not source_info.get("is_live"):
                processed.add(video_id)
                save_processed(processed)
        except Exception as exc:
            print(f"ERROR processing {url}: {exc}", file=sys.stderr, flush=True)
            raise
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print("Pipeline complete.")

if __name__ == "__main__":
    main()
