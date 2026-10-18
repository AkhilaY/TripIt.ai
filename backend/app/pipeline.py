import asyncio
import logging
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from .config import Settings
from .jobs import JobStore
from .library import Library
from .llm import ClaudeError, ClaudeService
from .media import (
    DownloadedReel,
    DownloadFailed,
    clean_error,
    download_reel,
    extract_audio,
    extract_frames,
    fetch_oembed,
    platform_for,
)
from .models import JobStatus, ReelMetadata
from .transcribe import transcribe

log = logging.getLogger(__name__)

UPLOAD_PREFIX = "upload:"


class JobFailed(Exception):
    """A failure with a message meant for the person who shared the reel."""


class Pipeline:
    def __init__(self, settings: Settings, store: JobStore, claude: ClaudeService, library: Library,
                 uploads_dir: Optional[Path] = None):
        self.settings = settings
        self.store = store
        self.claude = claude
        self.library = library
        # Screenshots wait here until their import succeeds (so a failed one can be retried).
        self.uploads = uploads_dir or Path(settings.database_path).parent / "uploads"
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
        self.on_finished = None  # optional callback(job) after an import finishes or fails

    def save_upload(self, images: list[bytes]) -> str:
        """Stores screenshots for an import; returns the job's URL ("upload:<token>")."""
        token = uuid.uuid4().hex
        folder = self.uploads / token
        folder.mkdir(parents=True, exist_ok=True)
        for i, data in enumerate(images, start=1):
            (folder / f"{i:02d}.jpg").write_bytes(data)
        return UPLOAD_PREFIX + token

    def _upload_folder(self, url: str) -> Optional[Path]:
        token = url[len(UPLOAD_PREFIX):]
        return self.uploads / token if re.fullmatch(r"[0-9a-f]{32}", token) else None

    async def run(self, job_id: str, url: str, shared_text: Optional[str]) -> None:
        async with self._semaphore:
            try:
                await self._run(job_id, url, shared_text)
            except (ClaudeError, JobFailed) as e:
                self.store.update(job_id, status=JobStatus.failed, message=str(e))
            except Exception:
                log.exception("Job %s failed", job_id)
                self.store.update(job_id, status=JobStatus.failed, message="Something went wrong processing this reel")
        if self.on_finished:
            try:
                await self.on_finished(self.store.get(job_id))
            except Exception:
                log.exception("Finished-import callback failed for %s", job_id)

    def _download_error(self, url: str, reason: str) -> str:
        message = f"Couldn't download this reel: {reason}."
        if platform_for(url) == "instagram" and not (self.settings.ytdlp_cookies or self.settings.ytdlp_cookies_file):
            message += " Instagram needs a logged-in session: add the YTDLP_COOKIES secret and redeploy."
        elif "private" in reason.lower() or "login" in reason.lower():
            message += " The reel may be private or need a login."
        return message

    async def _run(self, job_id: str, url: str, shared_text: Optional[str]) -> None:
        if url.startswith(UPLOAD_PREFIX):
            await self._run_upload(job_id, url, shared_text)
            return
        warnings: list[str] = []
        with tempfile.TemporaryDirectory(prefix="tripit-") as tmp:
            workdir = Path(tmp)

            self.store.update(job_id, status=JobStatus.downloading, message="Downloading reel")
            try:
                reel = await asyncio.to_thread(download_reel, url, workdir, self.settings)
            except Exception as e:
                reason = e.reason if isinstance(e, DownloadFailed) else clean_error(str(e))
                log.warning("Download failed for %s: %s", url, reason)
                # Fall back to the caption from the platform's embed API, or text shared with the link.
                metadata = await asyncio.to_thread(fetch_oembed, url)
                if metadata is None and not shared_text:
                    raise JobFailed(self._download_error(url, reason)) from e
                warnings.append(f"Couldn't download the post ({reason}), so only the caption was used. "
                                "Places shown only in the video or slides may be missing.")
                reel = DownloadedReel(metadata=metadata or ReelMetadata(platform=platform_for(url), url=url))
            self.store.update(job_id, reel=reel.metadata)

            transcript = None
            frames: list[tuple[str, Path]] = [
                (f"Slide {i}", p) for i, p in enumerate(reel.image_paths[: self.settings.max_frames], start=1)
            ]
            if reel.video_path:
                video = reel.video_path
                self.store.update(job_id, status=JobStatus.transcribing, message="Listening to the audio")
                audio = await asyncio.to_thread(extract_audio, video, workdir)
                if audio:
                    try:
                        transcript = await asyncio.to_thread(transcribe, audio, self.settings)
                    except Exception:
                        log.exception("Transcription failed")
                        warnings.append("Couldn't transcribe the audio.")
                video_frames = await asyncio.to_thread(extract_frames, video, workdir, self.settings)
                frames = (frames + [(f"Frame at {s:.0f}s", p) for s, p in video_frames])[: self.settings.max_frames]
            elif not reel.image_paths:
                warnings.append("Only the caption was available; places mentioned in the video may be missing.")

            self.store.update(job_id, status=JobStatus.analyzing, message="Finding places")
            result = await self.claude.extract_places(reel.metadata, shared_text, transcript, frames)

            # Status stays "analyzing" while pinning so older clients that only know the original statuses work.
            # Saved inside the temp dir block so frames Claude picked as place photos can be kept.
            self.store.update(job_id, result=result, message="Pinning places on the map")
            trip_id, reel_id, added = await self.library.save_extraction(
                reel.metadata, result, progress=lambda msg: self.store.update(job_id, message=msg),
                images=dict(frames),
            )

        self._finish(job_id, len(result.places), added, warnings, trip_id, reel_id)

    async def _run_upload(self, job_id: str, url: str, note: Optional[str]) -> None:
        folder = self._upload_folder(url)
        files = sorted(folder.glob("*.jpg")) if folder and folder.is_dir() else []
        if not files:
            raise JobFailed("These screenshots are no longer on the server. Add them again.")
        frames = [(f"Screenshot {i}", p) for i, p in enumerate(files[: self.settings.max_frames], start=1)]
        metadata = ReelMetadata(platform="screenshot", url=url, caption=note)
        self.store.update(job_id, reel=metadata, status=JobStatus.analyzing, message="Reading your screenshots")
        result = await self.claude.extract_places(metadata, None, None, frames)
        self.store.update(job_id, result=result, message="Pinning places on the map")
        trip_id, reel_id, added = await self.library.save_extraction(
            metadata, result, progress=lambda msg: self.store.update(job_id, message=msg),
            images=dict(frames), photo_attribution="From your screenshot",
        )
        shutil.rmtree(folder, ignore_errors=True)
        self._finish(job_id, len(result.places), added, [], trip_id, reel_id)

    def _finish(self, job_id: str, found: int, added: int, warnings: list[str], trip_id, reel_id) -> None:
        message = f"Found {found} place{'s' if found != 1 else ''}"
        if found and added < found:
            message += f" ({found - added} already saved)"
        self.store.update(
            job_id, status=JobStatus.done, message=message, warnings=warnings,
            trip_id=trip_id, reel_id=reel_id, added_places=added,
        )
