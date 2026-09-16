"""Optional Whisper/yt-dlp transcript generation with explicit failures."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from threading import Lock
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

logger = logging.getLogger(__name__)


def youtube_video_id(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/") or None
    if parsed.hostname and parsed.hostname.endswith("youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith(("/embed/", "/shorts/")):
            return parsed.path.split("/")[2] or None
    return None


def _audio_path(source_url: str, workdir: Path) -> Path:
    output = workdir / "audio.%(ext)s"
    if shutil.which("yt-dlp"):
        subprocess.run(
            [
                "yt-dlp", "--no-playlist", "-x", "--audio-format", "wav",
                "-o", str(output), source_url,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        files = list(workdir.glob("audio.*"))
        if files:
            return files[0]
    if youtube_video_id(source_url):
        raise RuntimeError("yt-dlp is required to download YouTube audio.")
    suffix = Path(urlparse(source_url).path).suffix or ".mp4"
    destination = workdir / f"source{suffix}"
    with urlopen(source_url, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return destination


def generate_transcript(source_url: str) -> list[dict]:
    """Generate normalized timestamped segments.

    Optional dependencies are loaded only when this operation is requested.
    Missing yt-dlp/Whisper raises a clear RuntimeError for the route to report.
    """
    video_id = youtube_video_id(source_url)
    if video_id:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            fetched = YouTubeTranscriptApi().fetch(video_id)
            return [
                {
                    "start": round(float(item.start), 2),
                    "end": round(float(item.start + item.duration), 2),
                    "text": str(item.text).strip(),
                }
                for item in fetched
                if str(item.text).strip()
            ]
        except (ImportError, AttributeError, TypeError, ValueError, OSError) as exc:
            logger.info("YouTube transcript fallback unavailable: %s", exc)

    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "Whisper is not installed. Install openai-whisper to generate transcripts."
        ) from exc

    with tempfile.TemporaryDirectory(prefix="capacity-connect-transcript-") as folder:
        audio = _audio_path(source_url, Path(folder))
        result = whisper.load_model("base").transcribe(str(audio))
    return [
        {
            "start": round(float(segment["start"]), 2),
            "end": round(float(segment["end"]), 2),
            "text": str(segment["text"]).strip(),
        }
        for segment in result.get("segments", [])
        if str(segment.get("text", "")).strip()
    ]


def parse_segments(raw: str | None) -> list[dict]:
    if not raw:
        return []
    value = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError("Transcript must be a JSON list.")
    segments = []
    for item in value:
        start, end = float(item["start"]), float(item["end"])
        text = str(item["text"]).strip()
        if start < 0 or end < start or not text:
            raise ValueError("Each transcript segment requires valid start, end, and text.")
        segments.append({"start": round(start, 2), "end": round(end, 2), "text": text})
    return segments
TRANSCRIPTION_PROGRESS: dict[int, dict] = {}
TRANSCRIPTION_PROGRESS_LOCK = Lock()


def set_transcription_progress(video_id: int, status: str, progress: int) -> None:
    with TRANSCRIPTION_PROGRESS_LOCK:
        TRANSCRIPTION_PROGRESS[video_id] = {
            "status": status, "progress": max(0, min(100, progress))
        }


def transcription_progress(video_id: int) -> dict:
    with TRANSCRIPTION_PROGRESS_LOCK:
        return TRANSCRIPTION_PROGRESS.get(
            video_id, {"status": "pending", "progress": 0}
        ).copy()
