#!/usr/bin/env python3
"""
TikTok Growth Engine — core logic + CLI
=======================================

This module is the single source of truth for the growth logic. It is used two
ways:

  * As a **command-line tool** (run directly): `python tiktok_growth.py plan`.
  * As an **importable library** by the web app (`app.py`): the pure functions
    below (build_schedule, recommend_hashtags, score_idea, generate_ideas,
    compute_stats, next_slot, schedule_to_ics, build_caption) return plain data
    so the FastAPI layer can serve them as JSON.

What it does
------------
  * WHEN to post   -> a personalised weekly posting schedule.
  * HOW to post    -> a pre-publish checklist + a hook/idea scorer.
  * WHICH hashtags -> a balanced mix of broad / niche / micro tags for a topic.
  * WHAT works     -> log your real posts and let the tool learn YOUR best
                      times and hashtags from your own numbers.

Honest caveats
--------------
* Nobody can *guarantee* views. TikTok's recommendation system is private and
  changes constantly. This encodes public best practices and helps you measure.
* The biggest lever is consistency + watch-time (a strong hook, videos people
  finish). Timing/hashtags are a small edge on top of good content.
* This does NOT post for you and uses NO bots or fake engagement — those
  violate TikTok's Terms and don't build a real audience. Strategy + analytics
  assistant only.

Data is stored in `tiktok_data.json` (override the directory with $DATA_DIR,
e.g. a Railway volume, so it survives redeploys).

CLI usage
---------
    python tiktok_growth.py setup          # one-time: niche, timezone, etc.
    python tiktok_growth.py schedule       # best days/times to post this week
    python tiktok_growth.py hashtags "topic words"
    python tiktok_growth.py ideas "topic"  # generate pre-scored video ideas
    python tiktok_growth.py score          # interactive hook / idea scorer
    python tiktok_growth.py checklist      # how-to-post pre-publish checklist
    python tiktok_growth.py log            # record a post you published
    python tiktok_growth.py stats          # what's working (learned from logs)
    python tiktok_growth.py plan           # full weekly action plan
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from datetime import datetime, timedelta

# Data path: defaults next to this script, override with $DATA_DIR (e.g. a
# Railway volume mounted at /data) so logged posts persist across redeploys.
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(DATA_DIR, "tiktok_data.json")

# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------
# Aggregated from widely-published TikTok engagement studies. Sensible starting
# defaults; once you log ~10+ posts the tool learns your real best times.
# Each entry is (day, hour_24, strength 1-3), in the creator's local timezone.
GENERIC_BEST_SLOTS = [
    ("Mon", 6, 2), ("Mon", 10, 2), ("Mon", 22, 3),
    ("Tue", 2, 2), ("Tue", 4, 2), ("Tue", 9, 3),
    ("Wed", 7, 2), ("Wed", 8, 2), ("Wed", 23, 2),
    ("Thu", 9, 3), ("Thu", 12, 2), ("Thu", 19, 2),
    ("Fri", 5, 2), ("Fri", 13, 2), ("Fri", 15, 1),
    ("Sat", 11, 2), ("Sat", 19, 3), ("Sat", 20, 2),
    ("Sun", 7, 2), ("Sun", 8, 2), ("Sun", 16, 1),
]

DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

NICHE_TAGS = {
    "general": ["fyp", "foryou", "foryoupage", "viral", "trending"],
    "news": ["news", "breakingnews", "newsupdate", "todayinnews", "explained"],
    "fitness": ["gymtok", "fitness", "workout", "fittok", "gymmotivation"],
    "food": ["foodtiktok", "recipe", "easyrecipe", "cooking", "foodie"],
    "beauty": ["beautytok", "makeup", "skincare", "grwm", "makeuptutorial"],
    "comedy": ["comedy", "funny", "skit", "humor", "relatable"],
    "education": ["learnontiktok", "edutok", "didyouknow", "studytok", "facts"],
    "tech": ["techtok", "tech", "gadgets", "coding", "ai"],
    "gaming": ["gamingtiktok", "gaming", "gamer", "twitch", "gameplay"],
    "fashion": ["fashiontiktok", "ootd", "style", "outfit", "fashion"],
    "business": ["entrepreneur", "smallbusiness", "sidehustle", "moneytok", "business"],
    "music": ["musictok", "newmusic", "singer", "cover", "musician"],
    "travel": ["traveltok", "travel", "wanderlust", "traveltiktok", "vacation"],
    "diy": ["diy", "crafttok", "homedecor", "diyproject", "satisfying"],
    "pets": ["petsoftiktok", "dogsoftiktok", "catsoftiktok", "puppy", "cute"],
}

HOOK_PATTERNS = [
    "POV:", "Watch till the end", "Here's why", "Nobody talks about",
    "I tried", "Stop doing", "The truth about", "3 things",
    "You've been doing X wrong", "Wait for it", "This is your sign",
]

# Templates used by generate_ideas(): "{t}" is replaced by the topic.
IDEA_TEMPLATES = [
    "Here's why {t} actually matters",
    "3 things about {t} nobody tells you",
    "POV: you finally understand {t}",
    "The truth about {t}",
    "Stop scrolling — {t} in 20 seconds",
    "Nobody is talking about {t}",
    "What {t} really means for you",
    "Wait for it: the {t} twist",
]

CHECKLIST = [
    ("Hook in first 1-2 seconds", "Open with motion, a bold claim, or a question. The first frame must stop the scroll."),
    ("Vertical 9:16, fills the screen", "Shoot/export 1080x1920. No black bars, no letterboxing."),
    ("Good lighting + clear audio", "Face a window or use a key light. Bad audio kills retention faster than bad video."),
    ("On-screen captions", "~80% watch on mute at first. Burn in captions or use auto-captions."),
    ("Trending or original sound", "Use a sound that's rising. Add it BEFORE filming so beats line up."),
    ("Keep it tight (loop-able)", "Cut dead air. A video people re-watch / finish gets pushed harder."),
    ("Strong CTA in caption", "Ask a question to drive comments. Comments > likes for reach."),
    ("3-5 hashtags, mixed tiers", "1 broad + 2 niche + 1-2 micro. Use the Hashtags tool."),
    ("Reply to early comments", "Engage in the first 30-60 min. Replies and pinned comments boost the loop."),
    ("Post at a high-traffic slot", "Use your schedule. Consistency (same daily slots) trains the algorithm."),
]


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            pass
    return {"profile": {}, "posts": []}


def save_data(data: dict) -> None:
    os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


# ===========================================================================
# PURE LOGIC  —  returns data, no printing/input. Used by both CLI and web.
# ===========================================================================
def normalize_niche(niche: str) -> str:
    """Map an arbitrary niche string to a known key (falls back to general)."""
    n = (niche or "").strip().lower()
    return n if n in NICHE_TAGS else "general"


def ranked_slots(data: dict):
    """Best (day, hour, strength) slots: learned from logs if enough, else generic.

    Returns (slots, learned_bool).
    """
    posts = data.get("posts", [])
    learned = {}
    for post in posts:
        day = post.get("day")
        hour = post.get("hour")
        views = post.get("views")
        if day in DAY_ORDER and isinstance(hour, int) and isinstance(views, (int, float)):
            learned.setdefault((day, hour), []).append(views)

    if len(posts) >= 10 and learned:
        scored = [(d, h, sum(v) / len(v)) for (d, h), v in learned.items()]
        scored.sort(key=lambda x: x[2], reverse=True)
        top = scored[:12]
        mx = top[0][2] or 1
        slots = [(d, h, max(1, round(3 * a / mx))) for (d, h, a) in top]
        return slots, True

    return list(GENERIC_BEST_SLOTS), False


def build_schedule(data: dict) -> dict:
    """Weekly schedule spread across days (one per day before doubling up).

    Returns {"slots": [{"day","hour","strength"}], "learned": bool,
             "posts_per_week": int}.
    """
    profile = data.get("profile", {})
    ppw = int(profile.get("posts_per_week", 7))
    slots, learned = ranked_slots(data)

    # Pick each day's single best slot first, rank days by strength, then take
    # as many distinct days as posts/week. Guarantees daily cadence (incl.
    # weekends at 7/week) instead of clustering on strong days.
    best_per_day = {}
    for day, hour, strength in slots:
        cur = best_per_day.get(day)
        if cur is None or strength > cur[2]:
            best_per_day[day] = (day, hour, strength)
    day_slots = sorted(best_per_day.values(),
                       key=lambda s: (-s[2], DAY_ORDER.index(s[0])))

    if ppw <= len(day_slots):
        ranked = day_slots[:ppw]
    else:
        ranked = list(day_slots)
        used = {(d, h) for d, h, _ in ranked}
        extra = sorted((s for s in slots if (s[0], s[1]) not in used),
                       key=lambda s: -s[2])
        ranked += extra[:ppw - len(day_slots)]

    ranked.sort(key=lambda s: (DAY_ORDER.index(s[0]), s[1]))
    return {
        "slots": [{"day": d, "hour": h, "strength": st} for d, h, st in ranked],
        "learned": learned,
        "posts_per_week": ppw,
    }


def recommend_hashtags(niche: str, topic: str) -> dict:
    """Balanced broad/niche/micro hashtag set for a topic."""
    niche = normalize_niche(niche)
    words = [w.strip("#").lower() for w in (topic or "").split() if w.strip("#")]
    broad = ["fyp", "foryou", "viral"]
    niche_tags = NICHE_TAGS.get(niche, NICHE_TAGS["general"])
    micro = [w for w in words if w.isalnum() and len(w) > 2]
    if len(words) >= 2:
        micro.append("".join(words[:2]))

    seen, chosen = set(), []
    for x in broad[:1] + niche_tags[:2] + micro[:2]:
        if x and x not in seen:
            seen.add(x); chosen.append(x)
    if len(chosen) < 4:
        for x in niche_tags + broad:
            if x and x not in seen:
                seen.add(x); chosen.append(x)
            if len(chosen) >= 5:
                break

    return {
        "tags": chosen[:5],
        "rationale": [
            "1 BROAD tag – maximum reach, very competitive.",
            "2 NICHE tags – signals your category to the algorithm.",
            "1-2 MICRO tags – low competition, easier to rank, finds true fans.",
            "Keep it to 3-5; relevance beats volume; rotate the broad tag.",
        ],
    }


def score_idea(hook: str, has_visual: bool, length: int, has_payoff: bool) -> dict:
    """Score a planned video 0-10 with actionable notes."""
    hook = (hook or "").strip()
    if not hook:
        return {"score": 0, "notes": ["✗ No hook entered — that's the #1 problem. Write one first."],
                "verdict": "🛠  Needs work — write a hook."}

    score, notes = 0, []
    if len(hook.split()) <= 9:
        score += 2; notes.append("✓ Hook is short and punchy.")
    else:
        notes.append("✗ Hook is long — tighten to <=9 words; people decide in ~1s.")

    if any(pat.lower().split()[0] in hook.lower() for pat in HOOK_PATTERNS) or any(c in hook for c in "?!"):
        score += 2; notes.append("✓ Uses a curiosity/pattern device.")
    else:
        notes.append("✗ Add a curiosity trigger (a question, 'POV:', 'here's why', a number).")

    if has_visual:
        score += 2; notes.append("✓ Visual hook present.")
    else:
        notes.append("✗ Start on motion or a striking frame, not a static talking head.")

    length = int(length or 0)
    if 7 <= length <= 34:
        score += 2; notes.append("✓ Length in the high-completion sweet spot (7-34s).")
    elif length <= 60:
        score += 1; notes.append("~ Okay length; shorter usually completes better.")
    else:
        notes.append("✗ Long videos need a strong reason to stay; watch your completion rate.")

    if has_payoff:
        score += 2; notes.append("✓ Has a payoff — good for completion + re-watch.")
    else:
        notes.append("✗ Promise a payoff in the hook and deliver it at the end.")

    verdict = ("🔥 Strong — post it." if score >= 8 else
               "👍 Decent — fix the ✗ items first." if score >= 5 else
               "🛠  Needs work — address the ✗ items before filming.")
    return {"score": score, "notes": notes, "verdict": verdict}


def build_caption(hook: str, cta: str, tags) -> str:
    """Assemble a paste-ready caption from hook + CTA + hashtags."""
    hook = (hook or "").strip()
    cta = (cta or "").strip() or "Follow for daily updates 👀"
    if isinstance(tags, str):
        tags = [t.strip("#") for t in tags.split()]
    tagline = " ".join("#" + t.strip("#") for t in tags if t)
    parts = [p for p in (hook, cta, tagline) if p]
    return "\n\n".join(parts)


def generate_ideas(niche: str, topic: str, n: int = 5) -> list:
    """Generate N pre-scored video ideas (hook + score + caption + hashtags)."""
    niche = normalize_niche(niche)
    topic = (topic or "this topic").strip()
    n = max(1, min(int(n or 5), len(IDEA_TEMPLATES)))
    tags = recommend_hashtags(niche, topic)["tags"]

    ideas = []
    for template in IDEA_TEMPLATES[:n]:
        hook = template.format(t=topic)
        # Score the hook assuming good production values so ranking reflects
        # hook quality; the user still controls visuals/length when filming.
        scored = score_idea(hook, has_visual=True, length=22, has_payoff=True)
        ideas.append({
            "hook": hook,
            "score": scored["score"],
            "caption": build_caption(hook, "Follow for daily updates 👀", tags),
            "hashtags": tags,
        })
    ideas.sort(key=lambda i: i["score"], reverse=True)
    return ideas


def compute_stats(data: dict) -> dict:
    """Aggregate performance from logged posts."""
    posts = data.get("posts", [])
    if not posts:
        return {"count": 0}

    n = len(posts)
    total_views = sum(p.get("views", 0) for p in posts)
    total_likes = sum(p.get("likes", 0) for p in posts)
    total_comments = sum(p.get("comments", 0) for p in posts)

    by_day = {}
    for p in posts:
        by_day.setdefault(p.get("day"), []).append(p.get("views", 0))
    day_avgs = [{"day": d, "avg": int(sum(v) / len(v)), "n": len(v)}
                for d, v in by_day.items() if d in DAY_ORDER]
    day_avgs.sort(key=lambda x: DAY_ORDER.index(x["day"]))
    best_day = max(day_avgs, key=lambda x: x["avg"])["day"] if day_avgs else None

    top = sorted(posts, key=lambda p: p.get("views", 0), reverse=True)[:3]
    top_posts = [{"views": p.get("views", 0), "desc": p.get("desc", "")} for p in top]

    tag_perf = {}
    for p in posts:
        for t in p.get("tags", []):
            tag_perf.setdefault(t, []).append(p.get("views", 0))
    best_tags = [{"tag": t, "avg": int(sum(v) / len(v))}
                 for t, v in tag_perf.items() if len(v) >= 2]
    best_tags.sort(key=lambda x: x["avg"], reverse=True)

    return {
        "count": n,
        "total_views": total_views,
        "avg_views": total_views // n,
        "engagement_rate": round(100 * (total_likes + total_comments) / total_views, 1) if total_views else 0.0,
        "day_avgs": day_avgs,
        "best_day": best_day,
        "top_posts": top_posts,
        "best_tags": best_tags[:5],
        "to_personalised": max(0, 10 - n),
    }


def _next_datetime_for(day: str, hour: int, now: datetime) -> datetime:
    """Next occurrence (>= now) of a given weekday+hour."""
    target_wd = DAY_ORDER.index(day)
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    days_ahead = (target_wd - now.weekday()) % 7
    candidate += timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def next_slot(data: dict, now: datetime | None = None) -> dict:
    """The next upcoming posting slot + a countdown, for the Today view."""
    now = now or datetime.now()
    sched = build_schedule(data)
    if not sched["slots"]:
        return {}
    upcoming = [(_next_datetime_for(s["day"], s["hour"], now), s) for s in sched["slots"]]
    when, slot = min(upcoming, key=lambda x: x[0])
    minutes = int((when - now).total_seconds() // 60)
    return {
        "day": slot["day"],
        "hour": slot["hour"],
        "strength": slot["strength"],
        "when_iso": when.isoformat(timespec="minutes"),
        "countdown_minutes": minutes,
        "countdown_human": f"{minutes // 60}h {minutes % 60}m",
    }


def schedule_to_ics(data: dict, now: datetime | None = None) -> str:
    """Render the weekly schedule as an iCalendar file (weekly recurring events
    with a 30-minute reminder), importable into the iPhone Calendar app."""
    now = now or datetime.now()
    sched = build_schedule(data)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//TikTok Growth Engine//EN", "CALSCALE:GREGORIAN",
    ]
    for i, s in enumerate(sched["slots"]):
        start = _next_datetime_for(s["day"], s["hour"], now)
        end = start + timedelta(minutes=15)
        stamp = now.strftime("%Y%m%dT%H%M%S")
        fmt = "%Y%m%dT%H%M%S"
        lines += [
            "BEGIN:VEVENT",
            f"UID:ttge-{i}-{s['day']}{s['hour']}@tiktok-growth",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start.strftime(fmt)}",
            f"DTEND:{end.strftime(fmt)}",
            "RRULE:FREQ=WEEKLY",
            "SUMMARY:Post on TikTok 🎬",
            "DESCRIPTION:Your scheduled TikTok posting slot. Run the checklist first!",
            "BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY",
            "DESCRIPTION:TikTok post in 30 min — film/queue your video",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def get_checklist() -> list:
    return [{"title": t, "detail": d} for t, d in CHECKLIST]


# ===========================================================================
# CLI  —  thin presentation layer over the pure functions above.
# ===========================================================================
def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        val = ""
    return val or default


def ask_int(prompt: str, default: int, lo: int, hi: int) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            n = int(raw)
            if lo <= n <= hi:
                return n
        except ValueError:
            pass
        print(f"  Enter a whole number between {lo} and {hi}.")


def hr(title: str = "") -> None:
    line = "=" * 64
    print(f"\n{line}\n  {title}\n{line}" if title else line)


def _h12(hour: int) -> str:
    try:
        return datetime.strptime(str(hour), "%H").strftime("%-I %p")
    except ValueError:
        return f"{hour}:00"


def cmd_setup(data: dict) -> None:
    hr("SETUP  —  tell the engine about your account")
    p = data.get("profile", {})
    print("\nKnown niches (others fall back to 'general'):", ", ".join(sorted(NICHE_TAGS)))
    niche = ask("Your main niche", p.get("niche", "general")).lower()
    posts_per_week = ask_int("How many videos can you post per week?", p.get("posts_per_week", 7), 1, 21)
    audience = ask("One-line description of your target viewer",
                   p.get("audience", "people interested in " + niche))
    tz = ask("Your timezone label (for your reference, e.g. EST/PST/GMT)", p.get("tz", "local"))
    data["profile"] = {
        "niche": niche, "posts_per_week": posts_per_week,
        "audience": audience, "tz": tz,
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    save_data(data)
    print("\n✓ Saved. Next, run:  python tiktok_growth.py plan")


def cmd_schedule(data: dict) -> None:
    if not data.get("profile"):
        print("Run `setup` first.")
        return
    sched = build_schedule(data)
    hr("POSTING SCHEDULE")
    src = "LEARNED from your logged posts" if sched["learned"] else "generic best-practice defaults"
    print(f"Source: {src}  (timezone: {data['profile'].get('tz', 'local')})")
    print(f"Target: {sched['posts_per_week']} videos / week\n")
    for s in sched["slots"]:
        bar = "★" * s["strength"] + "·" * (3 - s["strength"])
        print(f"  {s['day']}  {s['hour']:02d}:00 ({_h12(s['hour'])})   {bar}")
    if not sched["learned"]:
        print("\nStarting points. Log 10+ posts and the schedule rebuilds from")
        print("YOUR audience's real behaviour.")
    print("\nTip: same slots daily trains the algorithm AND your viewers.")


def cmd_hashtags(data: dict, topic: str) -> None:
    niche = data.get("profile", {}).get("niche", "general")
    res = recommend_hashtags(niche, topic)
    hr("HASHTAG SET")
    print("\nRecommended set (copy/paste):\n")
    print("  " + " ".join("#" + t for t in res["tags"]))
    print("\nWhy this mix:")
    for r in res["rationale"]:
        print("  • " + r)


def cmd_ideas(data: dict, topic: str) -> None:
    niche = data.get("profile", {}).get("niche", "general")
    ideas = generate_ideas(niche, topic, 5)
    hr(f"VIDEO IDEAS  —  {topic}")
    for i, idea in enumerate(ideas, 1):
        print(f"\n  {i}. [{idea['score']}/10]  {idea['hook']}")
        print(f"      tags: {' '.join('#' + t for t in idea['hashtags'])}")


def cmd_score(data: dict) -> None:
    hr("HOOK / IDEA SCORER")
    hook = ask("Your opening line / hook (first 2 seconds)")
    if not hook:
        print("No hook entered — write one first.")
        return
    has_visual = ask("Motion / visual surprise in the first frame? (y/n)", "n").lower().startswith("y")
    length = ask_int("Planned length in seconds", 21, 3, 600)
    has_payoff = ask("Clear payoff / reason to watch to the end? (y/n)", "n").lower().startswith("y")
    res = score_idea(hook, has_visual, length, has_payoff)
    hr()
    print(f"SCORE: {res['score']} / 10\n")
    for note in res["notes"]:
        print("  " + note)
    print("\n" + res["verdict"])


def cmd_checklist(data: dict) -> None:
    hr("HOW TO POST  —  pre-publish checklist")
    for i, item in enumerate(get_checklist(), 1):
        print(f"\n  {i:>2}. [ ] {item['title']}")
        for line in textwrap.wrap(item["detail"], 58):
            print(f"          {line}")


def cmd_log(data: dict) -> None:
    hr("LOG A POST")
    desc = ask("Short description / hook of the video")
    day = ask("Day posted (Mon/Tue/.../Sun)", datetime.now().strftime("%a"))[:3].title()
    if day not in DAY_ORDER:
        day = DAY_ORDER[datetime.now().weekday()]
    hour = ask_int("Hour posted (0-23)", datetime.now().hour, 0, 23)
    views = ask_int("Views so far", 0, 0, 1_000_000_000)
    likes = ask_int("Likes", 0, 0, 1_000_000_000)
    comments = ask_int("Comments", 0, 0, 1_000_000_000)
    tags = ask("Hashtags used (space separated, optional)")
    data.setdefault("posts", []).append({
        "desc": desc, "day": day, "hour": hour,
        "views": views, "likes": likes, "comments": comments,
        "tags": [t.strip("#").lower() for t in tags.split()],
        "logged": datetime.now().isoformat(timespec="seconds"),
    })
    save_data(data)
    n = len(data["posts"])
    print(f"\n✓ Logged. {n} post(s) on record."
          + (f" Log {10 - n} more to personalise timing." if n < 10 else " Timing is now personalised. 🎯"))


def cmd_stats(data: dict) -> None:
    hr("STATS  —  what's working")
    s = compute_stats(data)
    if not s.get("count"):
        print("No posts logged yet. Use `log` after you publish.")
        return
    print(f"\nPosts logged: {s['count']}   total views: {s['total_views']:,}   avg/post: {s['avg_views']:,}")
    print(f"Engagement rate: {s['engagement_rate']}% (likes+comments / views)")
    if s["day_avgs"]:
        print("\nAvg views by day:")
        for d in s["day_avgs"]:
            print(f"  {d['day']}: {d['avg']:,}  (n={d['n']})")
        print(f"  → Best day so far: {s['best_day']}")
    print("\nTop posts:")
    for p in s["top_posts"]:
        print(f"  {p['views']:>8,} views  —  {p['desc'][:42]}")
    if s["best_tags"]:
        print("\nBest hashtags (used 2+ times):")
        for t in s["best_tags"]:
            print(f"  #{t['tag']}: {t['avg']:,} avg views")


def cmd_plan(data: dict) -> None:
    profile = data.get("profile", {})
    if not profile:
        print("Run `setup` first, then `plan`.")
        return
    hr("YOUR WEEKLY TIKTOK GROWTH PLAN")
    print(f"Niche: {profile.get('niche')}   |   Audience: {profile.get('audience')}")
    print(f"Cadence: {profile.get('posts_per_week')} posts/week\n")
    print("THE LOOP (every week):")
    print("  1. BATCH-FILM 2-3 videos in one sitting.")
    print("  2. For EACH video, run `score` (fix anything below 8/10).")
    print("  3. Post at your slots; same slots daily = consistency.")
    print("  4. Reply to every comment in the first hour.")
    print("  5. After ~24-48h, `log` each post.")
    print("  6. Weekly, `stats` — double down on what works.")
    print("\n--- This week's slots ---")
    cmd_schedule(data)
    print("\n--- The 3 non-negotiables ---")
    print("  1. HOOK: earn the first 2 seconds or nothing else matters.")
    print("  2. COMPLETION: short + a payoff = shown to more people.")
    print("  3. CONSISTENCY: 1 post/day for 30 days beats 30 posts in one day.")


COMMANDS = {
    "setup": cmd_setup, "schedule": cmd_schedule, "score": cmd_score,
    "checklist": cmd_checklist, "log": cmd_log, "stats": cmd_stats, "plan": cmd_plan,
}


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[0].lower()
    data = load_data()
    if cmd == "hashtags":
        cmd_hashtags(data, " ".join(argv[1:]) or ask("Topic / keywords"))
        return 0
    if cmd == "ideas":
        cmd_ideas(data, " ".join(argv[1:]) or ask("Topic / keywords"))
        return 0
    handler = COMMANDS.get(cmd)
    if not handler:
        print(f"Unknown command: {cmd}\n{__doc__}")
        return 1
    handler(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
