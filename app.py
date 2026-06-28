#!/usr/bin/env python3
"""
app.py — web/PWA backend for the TikTok Growth Engine
=====================================================

A small FastAPI app that wraps the pure logic in `tiktok_growth.py` as a JSON
API and serves the mobile-first PWA frontend in ./static. Deploy on Railway
(HTTPS) and "Add to Home Screen" on iPhone to install it as an app.

Run locally:
    pip install -r requirements.txt
    uvicorn app:app --host 0.0.0.0 --port 8000

On Railway the Procfile runs uvicorn bound to $PORT.

Note: there is intentionally no login. Anyone with the URL can use it, so keep
the URL private. To add a password later, gate the /api/* routes behind a
dependency that checks an env-var secret.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Body
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import tiktok_growth as core

app = FastAPI(title="TikTok Growth Engine", docs_url="/api/docs")

STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.get("/api/profile")
def get_profile():
    return core.load_data().get("profile", {})


@app.post("/api/profile")
def set_profile(payload: dict = Body(...)):
    data = core.load_data()
    data["profile"] = {
        "niche": str(payload.get("niche", "general")).lower(),
        "posts_per_week": int(payload.get("posts_per_week", 7) or 7),
        "audience": payload.get("audience", ""),
        "tz": payload.get("tz", "local"),
        "updated": core.datetime.now().isoformat(timespec="seconds"),
    }
    core.save_data(data)
    return data["profile"]


@app.get("/api/schedule")
def get_schedule():
    return core.build_schedule(core.load_data())


@app.get("/api/schedule.ics")
def get_schedule_ics():
    ics = core.schedule_to_ics(core.load_data())
    return Response(
        content=ics,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="tiktok-schedule.ics"'},
    )


@app.get("/api/hashtags")
def get_hashtags(topic: str = ""):
    niche = core.load_data().get("profile", {}).get("niche", "general")
    return core.recommend_hashtags(niche, topic)


@app.post("/api/score")
def post_score(payload: dict = Body(...)):
    return core.score_idea(
        hook=payload.get("hook", ""),
        has_visual=bool(payload.get("has_visual", False)),
        length=int(payload.get("length", 0) or 0),
        has_payoff=bool(payload.get("has_payoff", False)),
    )


@app.get("/api/checklist")
def get_checklist():
    return core.get_checklist()


@app.get("/api/posts")
def get_posts():
    return core.load_data().get("posts", [])


@app.post("/api/posts")
def add_post(payload: dict = Body(...)):
    data = core.load_data()
    day = str(payload.get("day", ""))[:3].title()
    if day not in core.DAY_ORDER:
        day = core.DAY_ORDER[core.datetime.now().weekday()]
    tags = payload.get("tags", [])
    if isinstance(tags, str):
        tags = tags.split()
    data.setdefault("posts", []).append({
        "desc": payload.get("desc", ""),
        "day": day,
        "hour": int(payload.get("hour", 0) or 0),
        "views": int(payload.get("views", 0) or 0),
        "likes": int(payload.get("likes", 0) or 0),
        "comments": int(payload.get("comments", 0) or 0),
        "tags": [t.strip("#").lower() for t in tags],
        "logged": core.datetime.now().isoformat(timespec="seconds"),
    })
    core.save_data(data)
    return {"ok": True, "count": len(data["posts"])}


@app.get("/api/stats")
def get_stats():
    return core.compute_stats(core.load_data())


@app.get("/api/ideas")
def get_ideas(topic: str = "", n: int = 5):
    niche = core.load_data().get("profile", {}).get("niche", "general")
    return core.generate_ideas(niche, topic, n)


@app.post("/api/caption")
def post_caption(payload: dict = Body(...)):
    return {"caption": core.build_caption(
        payload.get("hook", ""), payload.get("cta", ""), payload.get("tags", []))}


@app.get("/api/today")
def get_today():
    data = core.load_data()
    return {
        "niche": data.get("profile", {}).get("niche", "general"),
        "configured": bool(data.get("profile")),
        "next_slot": core.next_slot(data),
    }


# ---------------------------------------------------------------------------
# Static / PWA  (mounted last so /api/* wins)
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# Serve manifest + service worker from root scope (sw.js must be top-level so it
# can control the whole app), plus everything else under /static.
@app.get("/sw.js")
def service_worker():
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(404)
def not_found(_request, _exc):
    return JSONResponse({"error": "not found"}, status_code=404)
