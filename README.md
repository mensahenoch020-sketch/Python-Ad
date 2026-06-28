# TikTok Growth Engine

A small, dependency-free Python command-line tool that turns the well-known
TikTok growth playbook into something you can actually **run**: when to post,
how to post, which hashtags to use — and, most importantly, it **learns from
your own posts** to personalise the advice over time.

```
python tiktok_growth.py plan        # your full weekly action plan
```

---

## What it does

| Command | What you get |
|---|---|
| `setup` | One-time: set your niche, timezone, posting cadence, audience. |
| `plan` | The full weekly "algorithm": the loop + this week's slots + angles. |
| `schedule` | A personalised weekly posting schedule (best days/times). |
| `hashtags "topic words"` | A balanced broad / niche / micro hashtag set for a video. |
| `score` | An interactive hook/idea scorer (rates your video 0–10 and tells you what to fix). |
| `checklist` | A pre-publish "how to post" checklist for maximum reach. |
| `log` | Record a post you published (views, likes, comments, tags). |
| `stats` | What's working: best day, top posts, best hashtags, engagement rate. |

Everything is stored locally in `tiktok_data.json` next to the script.

---

## Quick start

```bash
# 1. One-time setup
python tiktok_growth.py setup

# 2. See your weekly plan and posting slots
python tiktok_growth.py plan

# 3. Before filming a video, score the idea
python tiktok_growth.py score

# 4. Get hashtags for that specific video
python tiktok_growth.py hashtags "high protein breakfast"

# 5. Run the checklist before you upload
python tiktok_growth.py checklist

# 6. After ~24-48h, log how each post did
python tiktok_growth.py log

# 7. Weekly, review what's working
python tiktok_growth.py stats
```

No installation needed — it uses only the Python standard library
(Python 3.7+).

---

## How the "algorithm" works

1. **Defaults first.** Until you've logged enough posts, scheduling uses
   aggregated best-practice posting windows as sensible starting points.
2. **Then it learns you.** Once you've logged **10+ posts**, the schedule and
   stats rebuild themselves from *your* audience's real behaviour — your best
   day, your best times, and the hashtags that actually drive your views.
3. **The loop.** Batch-film → `score` each idea → post at your slots → engage
   early → `log` results → `stats` weekly → double down on what works.

The three non-negotiables it keeps pushing:

1. **Hook** — earn the first 2 seconds or nothing else matters.
2. **Completion** — short videos with a payoff get shown to more people.
3. **Consistency** — one post a day for 30 days beats 30 posts in one day.

---

## Honest caveats

* **No one can guarantee views.** TikTok's recommendation system is private and
  changes constantly. This tool encodes public best practices and helps you
  measure and improve — it's an edge on top of good content, not a substitute.
* **It does not post for you, and it uses no bots or fake engagement.** Those
  violate TikTok's Terms of Service, get accounts shadow-banned or removed, and
  don't build a real audience. This is a strategy + analytics assistant only.
* The biggest lever is always **good content + consistency**. Timing and
  hashtags are the small percentages on top.
