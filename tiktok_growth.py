#!/usr/bin/env python3
"""
TikTok Growth Engine
====================

A dependency-free command-line tool that helps you grow on TikTok by turning
the well-known growth playbook into something you can actually *run*:

  * WHEN to post   -> a personalised weekly posting schedule.
  * HOW to post    -> a pre-publish checklist + a hook/idea scorer.
  * WHICH hashtags -> a balanced mix of broad / niche / micro tags for a topic.
  * WHAT works     -> log your real posts and let the tool learn YOUR best
                      times and hashtags from your own numbers.

Important, honest caveats
-------------------------
* Nobody can *guarantee* views. TikTok's recommendation system is private and
  changes constantly. This tool encodes publicly known best practices and,
  more importantly, helps you measure and improve.
* The single biggest lever is **consistency + watch-time** (a strong hook and
  videos people finish/re-watch). Treat the timing/hashtag advice as a small
  edge on top of good content, not a substitute for it.
* This tool does NOT post for you and does NOT use bots, fake engagement, or
  view inflation. Those violate TikTok's Terms of Service, get accounts
  shadow-banned or removed, and don't build a real audience. This is a
  strategy + analytics assistant, period.

Everything is stored locally in `tiktok_data.json` next to this script.

Usage
-----
    python tiktok_growth.py setup          # one-time: set niche, timezone, etc.
    python tiktok_growth.py schedule       # best days/times to post this week
    python tiktok_growth.py hashtags "topic words"
    python tiktok_growth.py score          # interactive hook / idea scorer
    python tiktok_growth.py checklist      # how-to-post pre-publish checklist
    python tiktok_growth.py log            # record a post you published
    python tiktok_growth.py stats          # what's working (learned from logs)
    python tiktok_growth.py plan           # full weekly action plan (the "algorithm")
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from datetime import datetime, timedelta

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tiktok_data.json")

# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------
# These windows are aggregated from widely-published TikTok engagement studies
# (e.g. social-media analytics reports). They are sensible *starting defaults*.
# Once you log ~10+ posts, the tool learns your audience's real best times and
# these defaults stop mattering.
#
# Times are in the CREATOR's local timezone and assume your audience overlaps
# heavily with your own region. Each entry is (day, hour_24, strength 1-3).
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

# Niche-specific broad hashtags. Each video should blend tiers (see hashtags()).
NICHE_TAGS = {
    "general": ["fyp", "foryou", "foryoupage", "viral", "trending"],
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

CHECKLIST = [
    ("Hook in first 1-2 seconds", "Open with motion, a bold claim, or a question. The first frame must stop the scroll."),
    ("Vertical 9:16, fills the screen", "Shoot/export 1080x1920. No black bars, no letterboxing."),
    ("Good lighting + clear audio", "Face a window or use a key light. Bad audio kills retention faster than bad video."),
    ("On-screen captions", "~80% watch on mute at first. Burn in captions or use auto-captions."),
    ("Trending or original sound", "Use a sound that's rising. Add it BEFORE filming so beats line up."),
    ("Keep it tight (loop-able)", "Cut dead air. A video people re-watch / finish gets pushed harder."),
    ("Strong CTA in caption", "Ask a question to drive comments. Comments > likes for reach."),
    ("3-5 hashtags, mixed tiers", "1 broad + 2 niche + 1-2 micro. Run `hashtags` for a set."),
    ("Reply to early comments", "Engage in the first 30-60 min. Replies and pinned comments boost the loop."),
    ("Post at a high-traffic slot", "Run `schedule`. Consistency (same daily slots) trains the algorithm."),
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
            print("! tiktok_data.json was unreadable; starting fresh.")
    return {"profile": {}, "posts": []}


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


# ---------------------------------------------------------------------------
# Small input helpers
# ---------------------------------------------------------------------------
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
    if title:
        print(f"\n{line}\n  {title}\n{line}")
    else:
        print(line)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_setup(data: dict) -> None:
    hr("SETUP  —  tell the engine about your account")
    p = data.get("profile", {})

    print("\nAvailable niches:", ", ".join(sorted(NICHE_TAGS)))
    niche = ask("Your main niche", p.get("niche", "general")).lower()
    if niche not in NICHE_TAGS:
        print(f"  '{niche}' isn't a known niche; using 'general'. (Hashtags still work for any topic.)")
        niche = "general"

    posts_per_week = ask_int("How many videos can you post per week?", p.get("posts_per_week", 7), 1, 21)
    audience = ask("One-line description of your target viewer",
                   p.get("audience", "people interested in " + niche))
    tz = ask("Your timezone label (just for your reference, e.g. EST/PST/GMT)", p.get("tz", "local"))

    data["profile"] = {
        "niche": niche,
        "posts_per_week": posts_per_week,
        "audience": audience,
        "tz": tz,
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    save_data(data)
    print("\n✓ Saved. Next, run:  python tiktok_growth.py plan")


def _ranked_slots(data: dict):
    """Return best slots, learned from logs if we have enough, else generic."""
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


def cmd_schedule(data: dict) -> None:
    profile = data.get("profile", {})
    if not profile:
        print("Run `setup` first.")
        return
    ppw = profile.get("posts_per_week", 7)
    slots, learned = _ranked_slots(data)

    hr("POSTING SCHEDULE")
    source = "LEARNED from your logged posts" if learned else "generic best-practice defaults"
    print(f"Source: {source}  (timezone: {profile.get('tz', 'local')})")
    print(f"Target: {ppw} videos / week\n")

    ranked = sorted(slots, key=lambda s: s[2], reverse=True)[:ppw]
    ranked.sort(key=lambda s: (DAY_ORDER.index(s[0]), s[1]))

    for day, hour, strength in ranked:
        bar = "★" * strength + "·" * (3 - strength)
        ampm = datetime.strptime(str(hour), "%H").strftime("%-I %p") if hasattr(datetime, "strptime") else f"{hour}:00"
        print(f"  {day}  {hour:02d}:00 ({ampm})   {bar}")

    if not learned:
        print("\nThese are starting points. Log 10+ posts (`log`) and the schedule")
        print("rebuilds itself from YOUR audience's real behaviour.")
    print("\nTip: posting at the SAME slots daily trains the algorithm and your")
    print("viewers to expect you. Consistency beats perfect timing.")


def cmd_hashtags(data: dict, topic: str) -> None:
    profile = data.get("profile", {})
    niche = profile.get("niche", "general")
    hr("HASHTAG SET")

    words = [w.strip("#").lower() for w in topic.split() if w.strip("#")]
    # Tier 1: broad reach (huge but competitive)
    broad = ["fyp", "foryou", "viral"]
    # Tier 2: niche (your category)
    niche_tags = NICHE_TAGS.get(niche, NICHE_TAGS["general"])
    # Tier 3: micro / specific (your actual topic words + combos)
    micro = []
    for w in words:
        if w.isalnum() and len(w) > 2:
            micro.append(w)
    if len(words) >= 2:
        micro.append("".join(words[:2]))

    def dedupe(seq):
        seen, out = set(), []
        for x in seq:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    chosen = dedupe(broad[:1] + niche_tags[:2] + micro[:2])
    if len(chosen) < 4:
        chosen = dedupe(chosen + niche_tags + broad)[:5]

    print("\nRecommended set (copy/paste):\n")
    print("  " + " ".join("#" + t for t in chosen[:5]))
    print("\nWhy this mix:")
    print("  • 1 BROAD tag  – maximum reach, very competitive.")
    print("  • 2 NICHE tags – signals your category to the algorithm.")
    print("  • 1-2 MICRO    – low competition, easier to rank, finds true fans.")
    print("\nRules of thumb:")
    print("  - 3-5 tags total. More is NOT better; it dilutes relevance.")
    print("  - Make tags match the video's actual content (relevance > volume).")
    print("  - Rotate the broad tag; don't paste identical sets every time.")


def cmd_score(data: dict) -> None:
    hr("HOOK / IDEA SCORER")
    print("Answer a few questions about the video you're planning.\n")

    hook = ask("Your opening line / hook (first 2 seconds)")
    score = 0
    notes = []

    if not hook:
        print("No hook entered — that itself is the #1 problem. Write one first.")
        return

    n_words = len(hook.split())
    if n_words <= 9:
        score += 2; notes.append("✓ Hook is short and punchy.")
    else:
        notes.append("✗ Hook is long — tighten to <=9 words; people decide in ~1s.")

    if any(pat.lower().split()[0] in hook.lower() for pat in HOOK_PATTERNS) or \
       any(c in hook for c in "?!"):
        score += 2; notes.append("✓ Uses a curiosity/pattern device.")
    else:
        notes.append("✗ Add a curiosity trigger (a question, 'POV:', 'here's why', a number).")

    visual = ask("Is there motion / a visual surprise in the first frame? (y/n)", "n").lower()
    if visual.startswith("y"):
        score += 2; notes.append("✓ Visual hook present.")
    else:
        notes.append("✗ Start on motion or a striking frame, not a static talking head.")

    length = ask_int("Planned length in seconds", 21, 3, 600)
    if 7 <= length <= 34:
        score += 2; notes.append("✓ Length in the high-completion sweet spot (7-34s).")
    elif length <= 60:
        score += 1; notes.append("~ Okay length; shorter usually completes better.")
    else:
        notes.append("✗ Long videos need a very strong reason to stay; watch your completion rate.")

    payoff = ask("Is there a clear payoff / reason to watch to the end? (y/n)", "n").lower()
    if payoff.startswith("y"):
        score += 2; notes.append("✓ Has a payoff — good for completion + re-watch.")
    else:
        notes.append("✗ Promise a payoff in the hook and deliver it at the end (drives completion).")

    hr()
    print(f"SCORE: {score} / 10\n")
    for n in notes:
        print("  " + n)
    verdict = ("🔥 Strong — post it." if score >= 8 else
               "👍 Decent — fix the ✗ items first." if score >= 5 else
               "🛠  Needs work — address the ✗ items before filming.")
    print("\n" + verdict)


def cmd_checklist(data: dict) -> None:
    hr("HOW TO POST  —  pre-publish checklist")
    for i, (title, detail) in enumerate(CHECKLIST, 1):
        print(f"\n  {i:>2}. [ ] {title}")
        for line in textwrap.wrap(detail, 58):
            print(f"          {line}")
    print("\nWork top to bottom before you hit Post. The first 3 (hook, format,")
    print("audio/captions) decide whether the algorithm tests you with more views.")


def cmd_log(data: dict) -> None:
    hr("LOG A POST")
    print("Record a video you already published so the engine can learn.\n")

    desc = ask("Short description / hook of the video")
    day = ask("Day posted (Mon/Tue/.../Sun)", datetime.now().strftime("%a"))
    day = day[:3].title()
    if day not in DAY_ORDER:
        print(f"  Unrecognised day; defaulting to {DAY_ORDER[datetime.now().weekday()]}.")
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
    print(f"\n✓ Logged. You now have {n} post(s) on record.")
    if n < 10:
        print(f"  Log {10 - n} more to unlock personalised timing in `schedule`/`stats`.")
    else:
        print("  You have enough data — `schedule` and `stats` are now personalised. 🎯")


def cmd_stats(data: dict) -> None:
    posts = data.get("posts", [])
    hr("STATS  —  what's working")
    if not posts:
        print("No posts logged yet. Use `log` after you publish.")
        return

    total_views = sum(p.get("views", 0) for p in posts)
    total_likes = sum(p.get("likes", 0) for p in posts)
    total_comments = sum(p.get("comments", 0) for p in posts)
    n = len(posts)
    print(f"\nPosts logged: {n}")
    print(f"Total views: {total_views:,}   avg/post: {total_views // n:,}")
    if total_views:
        print(f"Engagement rate: {100 * (total_likes + total_comments) / total_views:.1f}% "
              f"(likes+comments / views)")

    # Best day
    by_day = {}
    for p in posts:
        by_day.setdefault(p.get("day"), []).append(p.get("views", 0))
    if by_day:
        ranked_days = sorted(by_day.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), reverse=True)
        print("\nAvg views by day:")
        for day, vs in sorted(ranked_days, key=lambda kv: DAY_ORDER.index(kv[0]) if kv[0] in DAY_ORDER else 9):
            print(f"  {day}: {int(sum(vs)/len(vs)):,}  (n={len(vs)})")
        print(f"  → Best day so far: {ranked_days[0][0]}")

    # Top posts
    top = sorted(posts, key=lambda p: p.get("views", 0), reverse=True)[:3]
    print("\nTop posts:")
    for p in top:
        print(f"  {p.get('views',0):>8,} views  —  {p.get('desc','(no description)')[:42]}")

    # Best hashtags
    tag_perf = {}
    for p in posts:
        for t in p.get("tags", []):
            tag_perf.setdefault(t, []).append(p.get("views", 0))
    tag_perf = {t: v for t, v in tag_perf.items() if len(v) >= 2}
    if tag_perf:
        best_tags = sorted(tag_perf.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), reverse=True)[:5]
        print("\nBest-performing hashtags (used 2+ times):")
        for t, vs in best_tags:
            print(f"  #{t}: {int(sum(vs)/len(vs)):,} avg views")

    if n < 10:
        print(f"\n(Log {10 - n} more posts for fully personalised scheduling.)")


def cmd_plan(data: dict) -> None:
    """The full 'algorithm': a single weekly action plan tying it all together."""
    profile = data.get("profile", {})
    if not profile:
        print("Run `setup` first, then `plan`.")
        return

    hr("YOUR WEEKLY TIKTOK GROWTH PLAN")
    print(f"Niche: {profile.get('niche')}   |   Audience: {profile.get('audience')}")
    print(f"Cadence: {profile.get('posts_per_week')} posts/week\n")

    print("THE LOOP (run this every week):")
    print("  1. BATCH-FILM 2-3 videos in one sitting (lowers the friction to post daily).")
    print("  2. For EACH video, run:  score   (fix anything below 8/10).")
    print("  3. Post at your scheduled slots below; same slots daily = consistency.")
    print("  4. Reply to every comment in the first hour.")
    print("  5. After ~24-48h, run:  log   for each post.")
    print("  6. Weekly, run:  stats   — double down on your best day/format/hashtags.")

    print("\n--- This week's slots ---")
    cmd_schedule(data)

    print("\n--- Content angles that tend to travel ---")
    for h in HOOK_PATTERNS[:6]:
        print(f"  • {h} ...")

    print("\n--- The 3 non-negotiables ---")
    print("  1. HOOK: earn the first 2 seconds or nothing else matters.")
    print("  2. COMPLETION: short + a payoff = the algorithm shows more people.")
    print("  3. CONSISTENCY: 1 post/day for 30 days beats 30 posts in one day.")
    print("\nRun `checklist` before each upload. Run `hashtags \"your topic\"` per video.")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
COMMANDS = {
    "setup": cmd_setup,
    "schedule": cmd_schedule,
    "score": cmd_score,
    "checklist": cmd_checklist,
    "log": cmd_log,
    "stats": cmd_stats,
    "plan": cmd_plan,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    cmd = argv[0].lower()
    data = load_data()

    if cmd == "hashtags":
        topic = " ".join(argv[1:]) or ask("Topic / keywords for this video")
        cmd_hashtags(data, topic)
        return 0

    handler = COMMANDS.get(cmd)
    if not handler:
        print(f"Unknown command: {cmd}\n")
        print(__doc__)
        return 1

    handler(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
