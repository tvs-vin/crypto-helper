"""8a: wallpaper processing (real Pillow and ffmpeg) and the wallpapers API."""

import io
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import wallpapers as wp
from tests.conftest import H
from tests.wallet_helpers import user_with

needs_ffmpeg = pytest.mark.skipif(not wp.have_ffmpeg(), reason="ffmpeg isn't installed")
UP = {**H, "Content-Type": "application/octet-stream"}


def png(w=800, h=450, color=(30, 60, 120)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def gif(frames=6, size=(320, 180)) -> bytes:
    fr = [Image.new("RGB", size, (i * 30 % 255, 80, 140)) for i in range(frames)]
    b = io.BytesIO()
    fr[0].save(b, "GIF", save_all=True, append_images=fr[1:], duration=90, loop=0)
    return b.getvalue()


def mp4(tmp_path, seconds=2, size="640x360") -> bytes:
    out = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
         f"testsrc=size={size}:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
         "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-metadata", "title=secret-title", str(out)],
        check=True,
    )  # fmt: skip
    return out.read_bytes()


# ---- processing ------------------------------------------------------------------------------


def test_still_is_reencoded_resized_and_stripped():
    b = io.BytesIO()
    im = Image.new("RGB", (5000, 2500), (200, 100, 50))
    exif = im.getexif()
    exif[0x8825] = {2: (40.0, 26.0, 46.0)}  # GPS
    exif[0x010F] = "Camera Maker"
    im.save(b, "JPEG", exif=exif)
    p = wp.process(b.getvalue())
    assert p.kind == "image" and p.ext == "webp" and p.mime == "image/webp"
    out = Image.open(io.BytesIO(p.data))
    assert out.format == "WEBP" and out.size == (3840, 1920)  # within 3840x2160, same shape
    assert not out.info.get("exif") and len(out.getexif()) == 0  # location and camera gone
    assert Image.open(io.BytesIO(p.poster)).size[0] <= wp.POSTER_WIDTH


def test_camera_rotation_is_applied_before_stripping():
    b = io.BytesIO()
    im = Image.new("RGB", (600, 300), (10, 10, 10))
    exif = im.getexif()
    exif[0x0112] = 6  # "rotate 90°"
    im.save(b, "JPEG", exif=exif)
    assert wp.process(b.getvalue()).width == 300  # portrait after rotation


def test_animated_gif_becomes_animated_webp():
    p = wp.process(gif(frames=8))
    out = Image.open(io.BytesIO(p.data))
    assert p.kind == "animated" and out.format == "WEBP" and out.n_frames == 8
    assert p.duration_ms == 8 * 90


def test_animation_limits(monkeypatch):
    monkeypatch.setattr(wp, "ANIM_MAX_FRAMES", 5)
    with pytest.raises(wp.WallpaperError, match="at most 5 frames"):
        wp.process(gif(frames=6))


@needs_ffmpeg
def test_video_is_reencoded_muted_and_stripped(tmp_path):
    p = wp.process(mp4(tmp_path))
    assert p.kind == "video" and p.ext == "webm" and p.mime == "video/webm"
    assert (p.width, p.height) == (640, 360) and 1500 <= p.duration_ms <= 2500
    out = tmp_path / "out.webm"
    out.write_bytes(p.data)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name:format_tags",
         "-of", "default=nw=1", str(out)], capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert "codec_name=vp9" in probe and "audio" not in probe  # muted
    assert "secret-title" not in probe  # metadata dropped
    assert Image.open(io.BytesIO(p.poster)).size == (640, 360)  # full-size still


@needs_ffmpeg
def test_long_videos_are_trimmed(tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "VIDEO_SECONDS", 1)
    assert wp.process(mp4(tmp_path, seconds=3)).duration_ms <= 1100


def _png_header_only(w: int, h: int) -> bytes:
    """A well-formed PNG that claims to be w x h but carries almost no data (the shape of an
    "image bomb"): the size has to be refused before anything is decoded."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" * 16)) + chunk(b"IEND", b""))  # fmt: skip


@pytest.mark.parametrize(
    "data, message",
    [
        (b"just some text, not a picture at all" * 4, "Not a picture or video"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "couldn't be read"),
        (_png_header_only(60000, 60000), "too big"),
        (_png_header_only(8, 8), "or too small"),
        (b"\xff\xd8\xff\xe0" + b"garbage" * 30, "couldn't be read"),
        (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200, "couldn't be read as a video"),
    ],
)
def test_bad_files_are_refused_without_echoing(data, message):
    if b"ftyp" in data and not wp.have_ffmpeg():
        pytest.skip("ffmpeg isn't installed")
    with pytest.raises(wp.WallpaperError, match=message) as e:
        wp.process(data)
    assert "PIL" not in str(e.value) and "Traceback" not in str(e.value)


@needs_ffmpeg
def test_a_playlist_dressed_as_a_video_reads_nothing(tmp_path):
    """The classic ffmpeg trick: a "video" that is really a playlist pointing at local files.
    The demuxer is forced and only the input file may be read, so nothing else is opened.
    (A stand-in file is the target: never a real system file.)"""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-CONTENT\n")
    playlist = (
        b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom\n"
        b"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:10.0,\n" + f"file://{secret}\n".encode()
        + b"#EXT-X-ENDLIST\n"
    )  # fmt: skip
    with pytest.raises(wp.WallpaperError):
        wp.process(playlist)
    hls = b"#EXTM3U\n#EXTINF:10.0,\n" + f"file://{secret}\n".encode()
    with pytest.raises(wp.WallpaperError, match="Not a picture or video"):
        wp.process(hls)


def test_files_are_judged_by_their_bytes_not_names():
    # A PNG renamed .mp4 is a PNG; a type mismatch inside is refused.
    assert wp.sniff(png()[:16]) == "png"
    jpeg = io.BytesIO()
    Image.new("RGB", (64, 64)).save(jpeg, "JPEG")
    fake = b"\x89PNG\r\n\x1a\n" + jpeg.getvalue()
    with pytest.raises(wp.WallpaperError):
        wp.process(fake)


# ---- the API ---------------------------------------------------------------------------------


def upload(c, data, name="Mine"):
    return c.post(f"/api/wallpapers?name={name}", content=data, headers=UP)


def test_list_has_the_builtins(logged_in):
    data = logged_in.get("/api/wallpapers").json()
    keys = [w["key"] for w in data["builtin"]]
    assert "builtin:aurora" in keys and "builtin:drift" in keys
    for w in data["builtin"]:
        web = Path(__file__).parents[1] / "app/web"
        assert (web / w["url"].removeprefix("/static/")).is_file()
        assert (web / w["poster"].removeprefix("/static/")).is_file()


def test_upload_needs_sign_in_and_the_csrf_header(app, logged_in):
    assert (
        TestClient(app).post("/api/wallpapers?name=x", content=png(), headers=UP).status_code == 401
    )
    r = logged_in.post("/api/wallpapers?name=x", content=png(),
                       headers={"Content-Type": "application/octet-stream"})  # fmt: skip
    assert r.status_code == 403  # no X-Requested-With


def test_upload_serve_and_privacy(app, logged_in):
    r = upload(logged_in, png())
    assert r.status_code == 201, r.text
    w = r.json()
    assert w["key"] == f"user:{w['id']}" and w["mine"] and not w["published"]
    f = logged_in.get(w["url"])
    assert f.status_code == 200 and f.headers["content-type"] == "image/webp"
    assert "immutable" in f.headers["cache-control"] and f.content[:4] == b"RIFF"
    assert logged_in.get(w["poster"]).status_code == 200
    other = user_with(app, logged_in, "other", ["wallets.view"])
    assert other.get(w["url"]).status_code == 404  # private
    assert all(x["id"] != w["id"] for x in other.get("/api/wallpapers").json()["uploaded"])
    assert (
        other.patch(f"/api/wallpapers/{w['id']}", json={"published": True}, headers=H).status_code
        == 404
    )
    # super publishes it: now everyone can use it, but only the owner deletes it
    assert (
        logged_in.patch(
            f"/api/wallpapers/{w['id']}", json={"published": True}, headers=H
        ).status_code
        == 200
    )
    assert other.get(w["url"]).status_code == 200
    assert other.delete(f"/api/wallpapers/{w['id']}", headers=H).status_code == 403


def test_publishing_needs_the_permission(app, logged_in):
    maker = user_with(app, logged_in, "maker", ["wallets.view"])
    w = upload(maker, png()).json()
    r = maker.patch(f"/api/wallpapers/{w['id']}", json={"published": True}, headers=H)
    assert r.status_code == 403


def test_bad_upload_and_names(logged_in):
    r = upload(logged_in, b"not an image at all" * 10)
    assert r.status_code == 422 and "Not a picture" in r.json()["detail"]
    # A pasted private key as the name (a well-known example key that holds nothing; short
    # enough to pass the 60-character limit, so only the secret check can refuse it).
    wif = "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ"
    r = upload(logged_in, png(), name=wif)
    assert r.status_code == 422 and r.json()["detail"] == "Give it a plain name."
    assert logged_in.post("/api/wallpapers?name=x", content=b"", headers=UP).status_code == 422


def test_limits(logged_in, monkeypatch):
    from app.routers import wallpapers as router

    monkeypatch.setattr(router, "MAX_PER_USER", 1)
    assert upload(logged_in, png()).status_code == 201
    r = upload(logged_in, png())
    assert r.status_code == 409 and "At most 1" in r.json()["detail"]
    monkeypatch.setattr(wp, "MAX_UPLOAD", 1000)
    assert upload(logged_in, png()).status_code == 413
    # Streamed without a declared size (chunked): the running count still stops it.
    chunks = (b"\x89PNG" + b"\x00" * 400 for _ in range(10))
    r = logged_in.post("/api/wallpapers?name=x", content=chunks, headers=UP)
    assert r.status_code == 413


class BusyLock:
    """Another upload is being converted. Waiting for it would hang the test (and a request):
    the endpoint must answer 429 without trying to take it."""

    def locked(self):
        return True

    async def __aenter__(self):
        raise AssertionError("waited for a busy lock instead of answering 429")

    async def __aexit__(self, *exc):
        return False


def test_one_upload_processed_at_a_time(app, logged_in, monkeypatch):
    monkeypatch.setattr(app.state, "wallpaper_lock", BusyLock())
    r = upload(logged_in, png())
    assert r.status_code == 429 and "try again" in r.json()["detail"]


def test_delete_removes_files_and_sweep_clears_orphans(app, logged_in, tmp_path):
    from app.routers.wallpapers import sweep

    w = upload(logged_in, png()).json()
    base = Path(app.state.settings.state_dir) / "wallpapers"
    files = sorted(p.name for p in base.iterdir())
    assert len(files) == 2
    assert logged_in.delete(f"/api/wallpapers/{w['id']}", headers=H).status_code == 204
    assert list(base.iterdir()) == []
    (base / "left-behind.webp").write_bytes(b"x")
    with app.state.session_factory() as db:
        assert sweep(app.state.settings.state_dir, db) == 1
    assert list(base.iterdir()) == []


def test_wallpaper_preference(logged_in):
    for good in ({"source": "builtin:aurora"}, {"source": "user:3", "fit": "tile", "dim": 80},
                 {"source": "none", "blur": 20, "motion": "still"}):  # fmt: skip
        r = logged_in.patch("/api/me/preferences", json={"wallpaper": good}, headers=H)
        assert r.status_code == 200, (good, r.text)
    for bad in ({"source": "http://evil.example.com/x.png"}, {"source": "builtin:../x"},
                {"dim": 90}, {"blur": -1}, {"fit": "stretch"}, {"url": "x"}):  # fmt: skip
        r = logged_in.patch("/api/me/preferences", json={"wallpaper": bad}, headers=H)
        assert r.status_code == 422, bad


def test_ffmpeg_presence_is_reported(logged_in):
    assert logged_in.get("/api/wallpapers").json()["video"] == bool(shutil.which("ffmpeg"))
