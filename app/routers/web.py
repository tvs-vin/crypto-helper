"""The web app: one page plus static files, all from this server (strict CSP, no CDNs)."""

import mimetypes
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

WEB = Path(__file__).resolve().parents[1] / "web"
mimetypes.add_type("application/json", ".ctheme")
router = APIRouter()


@router.get("/", include_in_schema=False)
def index():
    # Always revalidated, so an update shows up on the next load.
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


class Static(StaticFiles):
    """Static files that the browser revalidates (ETag) instead of caching blindly."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def mount(app) -> None:
    app.mount("/static", Static(directory=WEB), name="static")
