/*
 * app.js — dashboard logic for the Remote Administration Console.
 *
 * Talks to the FastAPI backend over plain fetch():
 *   GET  /api/agents                      -> list of connected agents
 *   POST /api/agents/{id}/command         -> run an action on one agent
 *
 * The agent list is refreshed by polling every 2s (simple and robust for a
 * teaching tool; a production app would push updates over a WebSocket).
 */

"use strict";

let selectedId = null;       // currently selected agent id
let agents = [];             // last fetched agent list

const els = {
  list: document.getElementById("agent-list"),
  count: document.getElementById("agent-count"),
  emptyDetail: document.getElementById("empty-detail"),
  detail: document.getElementById("agent-detail"),
  title: document.getElementById("detail-title"),
  sysinfo: document.getElementById("sysinfo"),
  refresh: document.getElementById("refresh-btn"),
  cmdForm: document.getElementById("cmd-form"),
  cmdInput: document.getElementById("cmd-input"),
  output: document.getElementById("cmd-output"),
};

// ---- API helpers ----------------------------------------------------------

async function apiGet(path) {
  const res = await fetch(path, { credentials: "same-origin" });
  if (res.status === 401) { location.reload(); return null; }  // session expired
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return res.json();
}

async function apiCommand(id, payload) {
  const res = await fetch(`/api/agents/${id}/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(payload),
  });
  if (res.status === 401) { location.reload(); return null; }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `error ${res.status}`);
  return body;
}

// ---- Rendering ------------------------------------------------------------

function renderList() {
  els.count.textContent = agents.length;
  els.list.innerHTML = "";
  for (const a of agents) {
    const host = (a.info && a.info.hostname) || "unknown host";
    const os = (a.info && a.info.os) || "";
    const li = document.createElement("li");
    li.className = "agent-item" + (a.id === selectedId ? " selected" : "");
    li.innerHTML =
      `<div class="host"><span class="dot"></span>${escapeHtml(host)}</div>` +
      `<div class="sub">#${a.id} · ${escapeHtml(os)} · ${escapeHtml(a.address)}</div>`;
    li.onclick = () => selectAgent(a.id);
    els.list.appendChild(li);
  }
  // If the selected agent vanished (disconnected), clear the detail pane.
  if (selectedId !== null && !agents.some((a) => a.id === selectedId)) {
    selectedId = null;
    showDetail(null);
  }
}

function showDetail(agent) {
  const has = !!agent;
  els.emptyDetail.hidden = has;
  els.detail.hidden = !has;
  if (!has) return;

  const info = agent.info || {};
  els.title.textContent = `${info.hostname || "agent"} (#${agent.id})`;

  const rows = [
    ["Hostname", info.hostname],
    ["Operating system", info.os],
    ["OS detail", info.os_detail],
    ["Python version", info.python_version],
    ["Current user", info.current_user],
    ["CPU cores", info.cpu_count],
  ];
  let html = rows
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(String(v))}</dd>`)
    .join("");

  html += `<dt>CPU usage</dt><dd>${meter(info.cpu_percent)}</dd>`;
  const memText = info.memory_used_mb != null
    ? `${info.memory_percent}% (${info.memory_used_mb} / ${info.memory_total_mb} MB)`
    : `${info.memory_percent ?? "?"}%`;
  html += `<dt>Memory usage</dt><dd>${meter(info.memory_percent, memText)}</dd>`;
  els.sysinfo.innerHTML = html;
}

function meter(percent, label) {
  const p = Number(percent) || 0;
  const hot = p >= 80 ? " hot" : "";
  const text = label || `${p}%`;
  return `${escapeHtml(text)}<div class="meter${hot}"><span style="width:${Math.min(p, 100)}%"></span></div>`;
}

// ---- Actions --------------------------------------------------------------

function selectAgent(id) {
  selectedId = id;
  renderList();
  const agent = agents.find((a) => a.id === id) || null;
  showDetail(agent);
  els.output.textContent = "";
  // Pull fresh system info on selection.
  refreshInfo();
}

async function refreshInfo() {
  if (selectedId === null) return;
  try {
    const resp = await apiCommand(selectedId, { action: "sysinfo" });
    if (resp && resp.type === "sysinfo") {
      const agent = agents.find((a) => a.id === selectedId);
      if (agent) { agent.info = resp.data; showDetail(agent); }
    }
  } catch (e) { /* agent may have just disconnected; list poll will correct it */ }
}

async function runCommand(command) {
  if (selectedId === null) return;
  els.output.textContent = `$ ${command}\n…`;
  try {
    const resp = await apiCommand(selectedId, { action: "exec", command });
    renderExecResult(command, resp);
  } catch (e) {
    els.output.innerHTML = `$ ${escapeHtml(command)}\n` +
      `<span class="err">${escapeHtml(e.message)}</span>`;
  }
}

function renderExecResult(command, resp) {
  const result = (resp && resp.result) || {};
  let out = `$ ${escapeHtml(command)}\n`;
  if (!result.ok) {
    out += `<span class="denied">${escapeHtml(result.error || "command failed")}</span>`;
  } else {
    if (result.stdout) out += escapeHtml(result.stdout);
    if (result.stderr) out += `\n<span class="err">${escapeHtml(result.stderr)}</span>`;
    out += `\n<span class="muted">[exit ${result.returncode}]</span>`;
  }
  els.output.innerHTML = out;
}

// ---- Wiring & polling -----------------------------------------------------

els.refresh.onclick = refreshInfo;
els.cmdForm.onsubmit = (e) => {
  e.preventDefault();
  const cmd = els.cmdInput.value.trim();
  if (cmd) runCommand(cmd);
};

async function poll() {
  try {
    const data = await apiGet("/api/agents");
    if (data) { agents = data; renderList(); }
  } catch (e) { /* transient; try again next tick */ }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

poll();
setInterval(poll, 2000);
