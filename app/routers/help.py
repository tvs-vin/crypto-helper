"""The Help window's pages (the wiki, see app/help.py). Anyone signed in may read them."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app import help as wiki
from app.deps import current_user

router = APIRouter(prefix="/api/help", tags=["help"], dependencies=[Depends(current_user)])


@router.get("")
def contents():
    return {"sections": wiki.contents(wiki.load())}


@router.get("/page")
def page(id: str = Query(min_length=1, max_length=80)):  # noqa: A002 (the page's id)
    found = wiki.load().get(id)  # an id from the list, never a path
    if found is None:
        raise HTTPException(status_code=404, detail="No such help page")
    return {"id": found.id, "title": found.title, "section": found.section,
            "blocks": found.blocks}  # fmt: skip


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=100)):
    return {"results": wiki.search(wiki.load(), q)}
