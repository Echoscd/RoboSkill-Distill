const state = {
  payload: null,
  follow: true,
  usedOnly: false,
  firstStartedAt: null,
  lastCallCount: -1,
  frameTick: 0,
};

const $ = (selector) => document.querySelector(selector);
const fmt = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

function safe(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : value;
}

function formatDuration(ms) {
  if (!ms) return "—";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(ms > 10000 ? 1 : 2)}s`;
}

function jsonPreview(value, max = 110) {
  const text = JSON.stringify(value ?? {});
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function pretty(value) {
  if (typeof value === "string") {
    try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; }
  }
  return JSON.stringify(value ?? {}, null, 2);
}

function statusLabel(payload) {
  const run = payload.run || {};
  const agent = payload.trace?.agent_status;
  if (run.success === true) return ["SUCCESS", "live"];
  if (agent === "tool-running" || agent === "running") return ["LIVE", "live"];
  if (run.run_state === "terminal" || agent === "complete") return ["COMPLETE", ""];
  if (run.exit_code && run.exit_code !== "0") return ["ERROR", "error"];
  return [String(run.run_state || agent || "waiting").toUpperCase(), ""];
}

function derivePhase(calls) {
  let phase = 0;
  for (const call of calls) {
    if (call.name.includes("plan_colored")) phase = Math.max(phase, call.status === "complete" ? 1 : 0);
    if (call.name === "device") {
      const device = call.args?.deviceID;
      const action = call.args?.action;
      if (device?.includes("arm") && action === "write") phase = Math.max(phase, 2);
      if (device?.includes("gripper") && call.args?.args?.actions?.[0] === 0) phase = Math.max(phase, 3);
    }
    if (call.name.includes("verify_colored")) phase = Math.max(phase, call.status === "complete" ? 4 : 3);
    if (call.name.includes("plan_held") || (phase >= 4 && call.name === "device")) phase = Math.max(phase, 5);
  }
  return phase;
}

function renderHeader(payload) {
  const run = payload.run || {};
  const session = payload.trace?.session || {};
  const task = safe(run.task, "等待任务连接").replace(/^robotwin\//, "RoboTwin · ");
  $("#task-title").textContent = task;
  $("#run-id").textContent = run.run_id ? `run ${run.run_id}` : safe(session.id, "—");
  const [label, cls] = statusLabel(payload);
  const badge = $("#live-status");
  badge.className = `status-pill ${cls}`;
  badge.innerHTML = `<i></i>${label}`;
  $("#footer-state").textContent = label;
  $("#footer-detail").textContent = run.success === true ? "native_success=true · success latched" : `${payload.trace?.calls?.length || 0} tool events captured`;
  $("#trace-path").textContent = safe(run.trace);
  if (!state.firstStartedAt && (run.started || session.started_at)) state.firstStartedAt = Date.parse(run.started || session.started_at);
}

function renderMetrics(metrics = {}) {
  $("#metric-tools").textContent = safe(metrics.tool_calls, 0);
  $("#metric-errors").textContent = `${safe(metrics.tool_errors, 0)} errors`;
  $("#metric-latency").textContent = formatDuration(metrics.model_latency_ms);
  $("#metric-tokens").textContent = fmt.format(metrics.total_tokens || 0);
  const allInput = (metrics.input_tokens || 0) + (metrics.cached_tokens || 0);
  const cacheRate = allInput ? `${Math.round((metrics.cached_tokens || 0) / allInput * 100)}%` : "—";
  $("#metric-cache").textContent = `cache ${cacheRate}`;
  $("#metric-cost").textContent = `$${Number(metrics.cost_usd || 0).toFixed(4)}`;
}

function renderDevices(devices = []) {
  $("#device-count").textContent = `${devices.length} DEVICES`;
  const root = $("#device-map");
  root.replaceChildren(...devices.map((device) => {
    const chip = document.createElement("div");
    chip.className = "device-chip";
    chip.innerHTML = `<i></i><strong>${device.name}</strong><em>${device.type}</em>`;
    return chip;
  }));
}

function renderTools(tools = [], calls = []) {
  const usage = new Map();
  for (const call of calls) {
    const item = usage.get(call.name) || { count: 0, status: "used" };
    item.count += 1;
    if (call.status === "running") item.status = "running";
    else if (call.status === "error" && item.status !== "running") item.status = "error";
    usage.set(call.name, item);
  }
  const query = $("#tool-search").value.trim().toLowerCase();
  const merged = new Map(tools.map((tool) => [tool.name, tool]));
  for (const name of usage.keys()) if (!merged.has(name)) merged.set(name, { name, source: "session" });
  const visible = [...merged.values()].filter((tool) => {
    if (state.usedOnly && !usage.has(tool.name)) return false;
    return !query || tool.name.toLowerCase().includes(query) || String(tool.description || "").toLowerCase().includes(query);
  });
  $("#tool-count").textContent = `${merged.size} TOOLS`;
  const rows = visible.map((tool) => {
    const used = usage.get(tool.name);
    const row = document.createElement("div");
    row.className = `tool-row ${used?.status || ""} ${used ? "used" : ""}`;
    row.title = tool.description || tool.name;
    row.innerHTML = `<span class="tool-light"></span><code>${tool.name}</code><span><small>${used ? `${used.count}×` : ""}</small> <i class="source-tag">${tool.source || "session"}</i></span>`;
    return row;
  });
  $("#tool-list").replaceChildren(...rows);
}

function openDetail(call) {
  $("#detail-title").textContent = call.name;
  $("#detail-input").textContent = pretty(call.args);
  $("#detail-output").textContent = call.result ? pretty(call.result) : "工具仍在运行…";
  $("#detail-dialog").showModal();
}

function renderTimeline(calls = []) {
  const root = $("#timeline");
  if (!calls.length) {
    root.innerHTML = '<div class="timeline-empty">等待第一个工具调用…</div>';
    return;
  }
  root.replaceChildren(...calls.map((call, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `event-card ${call.status}`;
    button.innerHTML = `<div class="event-top"><code>${String(index + 1).padStart(2,"0")} · ${call.name}</code><time>${call.status === "running" ? "RUNNING" : formatDuration(call.duration_ms)}</time></div><p>${jsonPreview(call.args)}</p>`;
    button.addEventListener("click", () => openDetail(call));
    return button;
  }));
  if (state.follow && calls.length !== state.lastCallCount) root.scrollTop = root.scrollHeight;
  state.lastCallCount = calls.length;
}

function renderPhases(calls) {
  const current = derivePhase(calls);
  document.querySelectorAll(".phase").forEach((node, index) => {
    node.classList.toggle("done", index < current);
    node.classList.toggle("active", index === current);
  });
}

function render(payload) {
  state.payload = payload;
  const trace = payload.trace || {};
  renderHeader(payload);
  renderMetrics(trace.metrics);
  renderDevices(payload.catalog?.devices || []);
  renderTools(payload.catalog?.tools || [], trace.calls || []);
  renderTimeline(trace.calls || []);
  renderPhases(trace.calls || []);
}

async function refreshState() {
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    const badge = $("#live-status");
    badge.className = "status-pill error";
    badge.innerHTML = "<i></i>DISCONNECTED";
    $("#footer-detail").textContent = String(error);
  }
}

async function refreshFrame() {
  const image = $("#camera-feed");
  try {
    const response = await fetch(`/api/frame?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("no frame");
    const source = response.headers.get("X-Kinex-Frame-Source") || "camera";
    const blob = await response.blob();
    const previous = image.dataset.url;
    const next = URL.createObjectURL(blob);
    image.src = next;
    image.dataset.url = next;
    image.classList.add("ready");
    $("#camera-empty").classList.add("hidden");
    $("#camera-source").textContent = source.toUpperCase();
    $("#frame-time").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    if (previous) URL.revokeObjectURL(previous);
  } catch {
    $("#camera-source").textContent = "NO SIGNAL";
  }
}

function updateClock() {
  const elapsed = state.firstStartedAt ? Math.max(0, Date.now() - state.firstStartedAt) : 0;
  const seconds = Math.floor(elapsed / 1000);
  const label = `${String(Math.floor(seconds / 60)).padStart(2,"0")}:${String(seconds % 60).padStart(2,"0")}`;
  $("#scene-clock").textContent = `T+${label}`;
  $("#wall-time").textContent = label;
}

function exportSnapshot() {
  if (!state.payload) return;
  const blob = new Blob([JSON.stringify(state.payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `kinex-monitor-${new Date().toISOString().replace(/[:.]/g,"-")}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

$("#tool-search").addEventListener("input", () => state.payload && renderTools(state.payload.catalog?.tools, state.payload.trace?.calls));
$("#used-only").addEventListener("click", (event) => {
  state.usedOnly = !state.usedOnly;
  event.currentTarget.classList.toggle("active", state.usedOnly);
  event.currentTarget.setAttribute("aria-pressed", String(state.usedOnly));
  if (state.payload) renderTools(state.payload.catalog?.tools, state.payload.trace?.calls);
});
$("#follow-button").addEventListener("click", (event) => {
  state.follow = !state.follow;
  event.currentTarget.classList.toggle("active", state.follow);
  event.currentTarget.setAttribute("aria-pressed", String(state.follow));
});
$("#export-button").addEventListener("click", exportSnapshot);

refreshState();
refreshFrame();
updateClock();
setInterval(refreshState, 750);
setInterval(refreshFrame, 700);
setInterval(updateClock, 1000);
