"use strict";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const $ = (s) => document.querySelector(s);
const el = (s) => document.getElementById(s);

async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}
function post(path, body) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
function h12(hr) {
  const ap = hr < 12 ? "AM" : "PM";
  const h = hr % 12 === 0 ? 12 : hr % 12;
  return `${h} ${ap}`;
}
function esc(s) { return (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

/* ---------- tab navigation ---------- */
const loaders = {};
function go(tab) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  document.querySelectorAll(".tabbtn").forEach((b) => b.classList.toggle("active", b.dataset.go === tab));
  window.scrollTo(0, 0);
  if (loaders[tab]) loaders[tab]();
}
document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => go(b.dataset.go)));

/* ---------- TODAY ---------- */
loaders.today = async () => {
  const t = await api("/api/today");
  const card = el("today-card");
  if (!t.configured) {
    card.innerHTML = `<h2>Welcome 👋</h2><p class="muted">Set up your account to get a personalised plan.</p>`;
    el("setup-prompt").innerHTML = `<button class="btn" id="open-setup">Set up</button>`;
    el("open-setup").onclick = openSetup;
    el("niche-pill").classList.add("hidden");
    return;
  }
  el("setup-prompt").innerHTML = "";
  const pill = el("niche-pill");
  pill.textContent = "#" + t.niche;
  pill.classList.remove("hidden");
  const s = t.next_slot || {};
  card.innerHTML = `
    <div class="muted">Your next posting slot</div>
    <h2 style="font-size:28px;margin:6px 0">${s.day || "-"} · ${h12(s.hour || 0)}</h2>
    <div class="muted">in ${s.countdown_human || "—"} &nbsp;·&nbsp; strength ${"★".repeat(s.strength || 0)}</div>
  `;
};

/* ---------- setup modal ---------- */
async function openSetup() {
  const p = await api("/api/profile");
  el("su-niche").value = p.niche || "";
  el("su-ppw").value = p.posts_per_week || 7;
  el("su-audience").value = p.audience || "";
  el("su-tz").value = p.tz || "GMT";
  el("setup-modal").classList.remove("hidden");
}
el("su-cancel").onclick = () => el("setup-modal").classList.add("hidden");
el("su-save").onclick = async () => {
  await post("/api/profile", {
    niche: el("su-niche").value || "general",
    posts_per_week: parseInt(el("su-ppw").value) || 7,
    audience: el("su-audience").value,
    tz: el("su-tz").value || "GMT",
  });
  el("setup-modal").classList.add("hidden");
  go("today");
  loaders.plan();
};

/* ---------- PLAN: schedule + checklist ---------- */
loaders.plan = async () => {
  const sched = await api("/api/schedule");
  const box = el("schedule");
  if (!sched.slots || !sched.slots.length) {
    box.innerHTML = `<span class="muted">Set up your account first (Today tab).</span>`;
  } else {
    const src = sched.learned ? "Learned from your posts" : "Best-practice defaults";
    box.innerHTML = `<div class="muted" style="margin-bottom:8px">${src} · ${sched.posts_per_week}/week</div>` +
      sched.slots.map((s) =>
        `<div class="slot"><span class="when">${s.day} · ${h12(s.hour)}</span>
         <span class="stars">${"★".repeat(s.strength)}${"·".repeat(3 - s.strength)}</span></div>`
      ).join("");
  }
  const items = await api("/api/checklist");
  el("checklist").innerHTML = items.map((it, i) =>
    `<label class="check"><input type="checkbox" /> <span><b>${i + 1}. ${esc(it.title)}</b><br>
     <span class="muted" style="font-size:13px">${esc(it.detail)}</span></span></label>`
  ).join("");
};

el("hash-btn").onclick = async () => {
  const r = await api("/api/hashtags?topic=" + encodeURIComponent(el("hash-topic").value));
  el("hash-out").innerHTML =
    `<div class="chips">${r.tags.map((t) => `<span class="chip">#${esc(t)}</span>`).join("")}</div>
     <button class="btn ghost" id="hash-copy">Copy tags</button>`;
  el("hash-copy").onclick = () => copy(r.tags.map((t) => "#" + t).join(" "));
};

el("score-btn").onclick = async () => {
  const r = await post("/api/score", {
    hook: el("score-hook").value,
    has_visual: el("score-visual").checked,
    has_payoff: el("score-payoff").checked,
    length: parseInt(el("score-length").value) || 0,
  });
  el("score-out").innerHTML =
    `<div class="scorebig">${r.score}/10</div>` +
    r.notes.map((n) => `<div class="note ${n[0] === "✓" ? "ok" : n[0] === "✗" ? "bad" : ""}">${esc(n)}</div>`).join("") +
    `<p><b>${esc(r.verdict)}</b></p>`;
};

/* ---------- IDEAS + caption ---------- */
el("ideas-btn").onclick = async () => {
  const topic = el("ideas-topic").value || "this topic";
  const ideas = await api("/api/ideas?n=6&topic=" + encodeURIComponent(topic));
  el("ideas-out").innerHTML = ideas.map((i) =>
    `<div class="idea"><span class="badge">${i.score}/10</span>
     <div style="font-weight:600;margin:4px 0">${esc(i.hook)}</div>
     <div class="chips">${i.hashtags.map((t) => `<span class="chip">#${esc(t)}</span>`).join("")}</div>
     <button class="btn ghost" data-cap="${encodeURIComponent(i.caption)}">Use as caption</button></div>`
  ).join("");
  el("ideas-out").querySelectorAll("[data-cap]").forEach((b) =>
    b.addEventListener("click", () => { el("cap-out").value = decodeURIComponent(b.dataset.cap); go("ideas"); }));
};

el("cap-btn").onclick = async () => {
  const r = await post("/api/caption", {
    hook: el("cap-hook").value, cta: el("cap-cta").value,
    tags: (el("cap-tags").value || "").split(/\s+/).filter(Boolean),
  });
  el("cap-out").value = r.caption;
};
el("cap-copy").onclick = () => copy(el("cap-out").value);

/* ---------- LOG ---------- */
el("log-day").innerHTML = DAYS.map((d) => `<option>${d}</option>`).join("");
el("log-day").value = DAYS[(new Date().getDay() + 6) % 7];
el("log-hour").value = new Date().getHours();
el("log-btn").onclick = async () => {
  const r = await post("/api/posts", {
    desc: el("log-desc").value, day: el("log-day").value,
    hour: parseInt(el("log-hour").value) || 0,
    views: parseInt(el("log-views").value) || 0,
    likes: parseInt(el("log-likes").value) || 0,
    comments: parseInt(el("log-comments").value) || 0,
    tags: (el("log-tags").value || "").split(/\s+/).filter(Boolean),
  });
  const left = Math.max(0, 10 - r.count);
  el("log-out").innerHTML = `<div class="toast">✓ Saved. ${r.count} post(s) on record. ` +
    (left ? `Log ${left} more to personalise timing.` : `Timing is now personalised! 🎯`) + `</div>`;
  ["log-desc", "log-tags"].forEach((id) => (el(id).value = ""));
};

/* ---------- STATS ---------- */
loaders.stats = async () => {
  const s = await api("/api/stats");
  const box = el("stats");
  if (!s.count) { box.innerHTML = `<span class="muted">No posts logged yet. Use the Log tab after you publish.</span>`; return; }
  const max = Math.max(1, ...s.day_avgs.map((d) => d.avg));
  box.innerHTML = `
    <div class="stat-grid">
      <div class="stat"><div class="num">${s.count}</div><div class="lbl">posts logged</div></div>
      <div class="stat"><div class="num">${s.avg_views.toLocaleString()}</div><div class="lbl">avg views</div></div>
      <div class="stat"><div class="num">${s.total_views.toLocaleString()}</div><div class="lbl">total views</div></div>
      <div class="stat"><div class="num">${s.engagement_rate}%</div><div class="lbl">engagement</div></div>
    </div>
    ${s.best_day ? `<p>Best day so far: <b>${s.best_day}</b></p>` : ""}
    <h3>Avg views by day</h3>
    ${s.day_avgs.map((d) => `<div class="slot"><span>${d.day}</span><span class="muted">${d.avg.toLocaleString()} (n=${d.n})</span></div>
       <div class="bar"><i style="width:${Math.round(100 * d.avg / max)}%"></i></div>`).join("")}
    ${s.best_tags.length ? `<h3>Best hashtags</h3>${s.best_tags.map((t) => `<div class="slot"><span>#${esc(t.tag)}</span><span class="muted">${t.avg.toLocaleString()} avg</span></div>`).join("")}` : ""}
    ${s.to_personalised ? `<p class="fine">Log ${s.to_personalised} more posts to fully personalise scheduling.</p>` : ""}
  `;
};

/* ---------- helpers ---------- */
async function copy(text) {
  try { await navigator.clipboard.writeText(text); alert("Copied!"); }
  catch { prompt("Copy:", text); }
}

/* ---------- boot ---------- */
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
go("today");
