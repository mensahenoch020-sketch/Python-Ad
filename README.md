# TikTok Growth Engine

Turns the well-known TikTok growth playbook into something you can actually
**run**: when to post, how to post, which hashtags to use — and, most
importantly, it **learns from your own posts** to personalise the advice.

It comes in two forms:

* 📱 **A mobile web app (PWA)** you install on your iPhone home screen — the
  recommended way to use it day to day.
* ⌨️ **A command-line tool** (`tiktok_growth.py`) for the terminal.

Both share the exact same engine.

---

## 📱 Use it on your iPhone (the app)

The web app (`app.py`, served by FastAPI) gives you a clean, touch-friendly
interface with bottom tabs: **Today · Plan · Ideas · Log · Stats · Guide**.
Once deployed it installs to your home screen and runs full-screen like a
native app.

### Deploy to Railway (free HTTPS — required for iPhone install)

1. Push this repo to GitHub (already done if you're reading this there).
2. On [railway.app](https://railway.app): **New Project → Deploy from GitHub
   repo** and pick this repo. Railway reads `Procfile` / `railway.json` and
   starts it automatically.
3. Open **Settings → Networking → Generate Domain** to get an
   `https://…up.railway.app` URL.
4. *(Recommended)* Add a **Volume** mounted at `/data` and set an environment
   variable `DATA_DIR=/data`, so your logged posts survive redeploys.
   Without this, Railway's disk is ephemeral and your data resets on each deploy.

### Install on the iPhone home screen

1. Open the Railway URL in **Safari** (must be Safari, and must be HTTPS).
2. Tap the **Share** button → **Add to Home Screen** → **Add**.
3. Launch it from the new icon — it opens full-screen, no browser bars.

> **Privacy note:** there is no login, so anyone with the URL can see/edit your
> data. Keep the URL private. To add a password later, gate the `/api/*` routes
> in `app.py` behind an env-var secret.

### In-app tutorial

The **Guide** tab inside the app walks you through the whole workflow. The short
version:

1. **Set up once** (Today → Set up): niche, posts/week, audience, timezone.
2. **Each morning** open **Today** for your next slot + countdown.
3. **Plan a video** in **Ideas** (pick a high-scoring hook + caption).
4. **Before posting**, in **Plan**: run the checklist, grab hashtags, score it.
5. Tap **Add to iPhone Calendar** so your slots show up with reminders.
6. **After 24–48h**, **Log** the post's views/likes/comments.
7. **Weekly**, check **Stats** and double down on what works.

### Run the web app locally

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
# open http://localhost:8000  (iOS won't fully "install" without HTTPS)
```

---

## ⌨️ Command-line tool

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
| `ideas "topic words"` | Several pre-scored video hooks for a topic. |
| `score` | An interactive hook/idea scorer (rates your video 0–10 and tells you what to fix). |
| `checklist` | A pre-publish "how to post" checklist for maximum reach. |
| `log` | Record a post you published (views, likes, comments, tags). |
| `stats` | What's working: best day, top posts, best hashtags, engagement rate. |

Data is stored in `tiktok_data.json` (next to the script by default; set the
`DATA_DIR` env var — e.g. a Railway volume — to put it elsewhere). Both the CLI
and the web app read/write the same file.

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
