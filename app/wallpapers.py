"""Wallpaper uploads: every file is checked and re-encoded before anyone's browser sees it.

- The type comes from the file's first bytes, never its name.
- Still images (PNG, JPEG, WebP) -> WebP, at most 3840x2160, metadata dropped (e.g. where a
  photo was taken), with Pillow's image-bomb limits.
- Animated GIF/WebP -> animated WebP, at most 1280 px and 300 frames.
- Videos (MP4, WebM) -> WebM (VP9), muted, at most 1920x1080, 30 fps and 60 seconds, via ffmpeg.
  ffmpeg is told the exact input format and may only read the local file: no playlists, no
  URLs, no other files (the classic ways a crafted "video" makes ffmpeg fetch or leak things).
Every wallpaper also gets a small still poster (for previews and reduced motion).
"""

import io
import json
import os
import shutil
import subprocess
import tempfile
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, ImageSequence

MAX_UPLOAD = 60 * 1024 * 1024
MAX_IMAGE_UPLOAD = 25 * 1024 * 1024
MAX_PIXELS = 40_000_000  # per frame, checked before decoding
STILL_MAX = (3840, 2160)
ANIM_MAX_SIDE = 1280
ANIM_MAX_FRAMES = 300
ANIM_MAX_TOTAL_PIXELS = 300_000_000
VIDEO_MAX_INPUT_SECONDS = 300
VIDEO_SECONDS = 60
POSTER_WIDTH = 480  # previews of pictures
STILL_POSTER = (1920, 1080)  # animations and videos: also the still shown when motion is off

# Pillow's own guard: refuse absurd images instead of decoding them.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
warnings.simplefilter("error", Image.DecompressionBombWarning)


class WallpaperError(Exception):
    """A file we won't use; the message is safe to show."""


@dataclass
class Processed:
    kind: str  # image | animated | video
    data: bytes
    ext: str  # webp | webm
    mime: str
    poster: bytes  # webp
    width: int
    height: int
    duration_ms: int | None = None


def sniff(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head[4:8] == b"ftyp":
        return "mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    return None


PIL_FORMAT = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP", "gif": "GIF"}


def have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def process(data: bytes) -> Processed:
    kind = sniff(data[:16])
    if kind is None:
        raise WallpaperError(
            "Not a picture or video we take: use PNG, JPEG, WebP, GIF, MP4 or WebM."
        )
    if kind in ("mp4", "webm"):
        return _video(data, kind)
    if len(data) > MAX_IMAGE_UPLOAD:
        raise WallpaperError(f"Pictures can be at most {MAX_IMAGE_UPLOAD // 1024 // 1024} MB.")
    try:
        # Only the decoder for the type it says it is: Pillow's many other decoders (TIFF, EPS,
        # PDF...) never see an upload, whatever bugs they have.
        im = Image.open(io.BytesIO(data), formats=[PIL_FORMAT[kind]])
        if im.format.lower() != ("jpeg" if kind == "jpeg" else kind):
            raise WallpaperError("The file doesn't match its own type.")
        w, h = im.size
        if w * h > MAX_PIXELS or w < 16 or h < 16:
            raise WallpaperError("That picture is too big (or too small) to use.")
        if getattr(im, "is_animated", False) and im.n_frames > 1:
            return _animated(im)
        return _still(im)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise WallpaperError("That picture is too big to use.") from None
    except WallpaperError:
        raise
    except Exception:  # truncated, corrupt or hostile: never show the decoder's message
        raise WallpaperError("That file couldn't be read as a picture.") from None


def _poster(im: Image.Image, size=(POSTER_WIDTH, POSTER_WIDTH * 2)) -> bytes:
    p = im.convert("RGB")
    p.thumbnail(size)
    out = io.BytesIO()
    p.save(out, "WEBP", quality=75)
    return out.getvalue()


def _still(im: Image.Image) -> Processed:
    im = ImageOps.exif_transpose(im)  # honour the camera's rotation, then drop all metadata
    im.load()
    im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
    im.thumbnail(STILL_MAX)
    out = io.BytesIO()
    im.save(out, "WEBP", quality=85, method=4)
    return Processed("image", out.getvalue(), "webp", "image/webp", _poster(im), *im.size)


def _animated(im: Image.Image) -> Processed:
    w, h = im.size
    if im.n_frames > ANIM_MAX_FRAMES:
        raise WallpaperError(f"Animations can have at most {ANIM_MAX_FRAMES} frames.")
    if im.n_frames * w * h > ANIM_MAX_TOTAL_PIXELS:
        raise WallpaperError("That animation is too big to use; try a smaller or shorter one.")
    frames, durations = [], []
    for frame in ImageSequence.Iterator(im):
        f = frame.convert("RGBA")
        f.thumbnail((ANIM_MAX_SIDE, ANIM_MAX_SIDE))
        frames.append(f)
        durations.append(max(20, int(frame.info.get("duration", 100) or 100)))
    out = io.BytesIO()
    frames[0].save(out, "WEBP", save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, quality=75, method=4)  # fmt: skip
    still = _poster(frames[0], STILL_POSTER)
    w, h = frames[0].size
    return Processed("animated", out.getvalue(), "webp", "image/webp", still, w, h, sum(durations))


# Exact demuxer for each sniffed type: ffmpeg never guesses (so a "video" can't turn out to be
# a playlist pointing at other files or URLs).
DEMUXER = {"mp4": "mov", "webm": "matroska"}
SAFE_INPUT = ["-protocol_whitelist", "file", "-hide_banner", "-loglevel", "error"]
SCALE = (
    "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
)
LONGEST = f"Videos can be at most {VIDEO_MAX_INPUT_SECONDS // 60} minutes long."


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise WallpaperError("That video took too long to process.") from None


def _video(data: bytes, kind: str) -> Processed:
    if not have_ffmpeg():
        raise WallpaperError(
            "Video wallpapers need ffmpeg on the server (sudo apt install ffmpeg). Pictures work."
        )
    if len(data) > MAX_UPLOAD:
        raise WallpaperError(f"Videos can be at most {MAX_UPLOAD // 1024 // 1024} MB.")
    with tempfile.TemporaryDirectory(prefix="wallpaper-") as tmp:
        src = os.path.join(tmp, f"in.{kind}")
        dst = os.path.join(tmp, "out.webm")
        poster = os.path.join(tmp, "poster.png")
        with open(src, "wb") as f:
            f.write(data)
        fmt = DEMUXER[kind]
        entries = "stream=codec_type,width,height:format=duration"
        probe = _run(
            ["ffprobe", *SAFE_INPUT, "-f", fmt, "-show_entries", entries, "-of", "json", src], 20
        )
        try:
            info = json.loads(probe.stdout or b"{}")
            video = next(s for s in info.get("streams", []) if s.get("codec_type") == "video")
            duration = float(info.get("format", {}).get("duration") or 0)
        except (ValueError, StopIteration):
            raise WallpaperError("That file couldn't be read as a video.") from None
        if probe.returncode != 0 or not video.get("width"):
            raise WallpaperError("That file couldn't be read as a video.")
        if video["width"] * video["height"] > MAX_PIXELS:
            raise WallpaperError("That video's picture is too big to use.")
        if duration > VIDEO_MAX_INPUT_SECONDS:
            raise WallpaperError(
                f"Videos can be at most {VIDEO_MAX_INPUT_SECONDS // 60} minutes long."
            )
        enc = _run(["ffmpeg", "-nostdin", *SAFE_INPUT, "-f", fmt, "-i", src,
                    "-map", "0:v:0", "-an", "-sn", "-dn", "-map_metadata", "-1",
                    "-t", str(VIDEO_SECONDS), "-fpsmax", "30",
                    "-vf", SCALE,
                    "-c:v", "libvpx-vp9", "-crf", "36", "-b:v", "0", "-row-mt", "1",
                    "-deadline", "good", "-cpu-used", "4", "-pix_fmt", "yuv420p", "-threads", "2",
                    "-f", "webm", dst], 300)  # fmt: skip
        if enc.returncode != 0 or not os.path.exists(dst):
            raise WallpaperError("That video couldn't be converted.")
        _run(
            ["ffmpeg", *SAFE_INPUT, "-f", "matroska", "-i", dst, "-frames:v", "1", "-y", poster], 30
        )
        try:
            still = Image.open(poster, formats=["PNG"])  # ffmpeg wrote a PNG
            still.load()
        except Exception:
            raise WallpaperError("That video couldn't be converted.") from None
        with open(dst, "rb") as f:
            out = f.read()
        ms = int(min(duration, VIDEO_SECONDS) * 1000)
        w, h = still.size
        return Processed("video", out, "webm", "video/webm", _poster(still, STILL_POSTER), w, h, ms)
