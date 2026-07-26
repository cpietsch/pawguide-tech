(function (root) {
  "use strict";

  const ACCEPTANCE_URL = "/admin/status/acceptance";

  function finalStopIsSafe(state) {
    return Boolean(
      state
      && state.stop_latched === true
      && state.mission_state === "stopped"
      && state.operator_heartbeat_fresh === false
      && state.active_waypoint == null
      && state.last_stop_reason === "operator_stop"
    );
  }

  function elapsedSeconds(report, nowMs) {
    if (Number.isFinite(report.show_elapsed_s)) return report.show_elapsed_s;
    const started = Date.parse(report.started_at || "");
    if (!Number.isFinite(started)) return null;
    const finished = Date.parse(report.finished_at || "");
    const end = Number.isFinite(finished) ? finished : nowMs;
    return Math.max(0, Math.round((end - started) / 1000));
  }

  function showSequence(report) {
    if (!Array.isArray(report.checks) || !Array.isArray(report.confirmations)) {
      return null;
    }
    const passedChecks = new Set(
      report.checks.filter((check) => check?.passed === true).map((check) => check.name)
    );
    const failedChecks = new Set(
      report.checks.filter((check) => check?.passed === false).map((check) => check.name)
    );
    const confirmations = new Set(report.confirmations.map((item) => item?.stage));
    const status = (passed, failed = false) =>
      failed ? "failed" : passed ? "passed" : report.finished_at ? "failed" : "pending";
    return [
      {
        id: "ready",
        label: "Ready at home",
        status: status(
          passedChecks.has("initial_home_stationary")
          && confirmations.has("activation_ready"),
          failedChecks.has("initial_home_stationary")
        ),
      },
      {
        id: "greeting",
        label: "Stand and greet",
        status: status(
          passedChecks.has("stand_up")
          && passedChecks.has("greeting")
          && confirmations.has("greeting_complete")
        ),
      },
      {
        id: "gate",
        label: "Navigate 5 m to demo gate",
        status: status(
          passedChecks.has("gate_stationary_arrival")
          && passedChecks.has("gate_orientation")
          && confirmations.has("gate_arrived"),
          failedChecks.has("gate_stationary_arrival")
          || failedChecks.has("gate_orientation")
        ),
      },
      {
        id: "farewell",
        label: "Gate confirmation and farewell",
        status: status(confirmations.has("farewell_complete")),
      },
      {
        id: "return",
        label: "Return home",
        status: status(
          passedChecks.has("home_stationary_arrival")
          && passedChecks.has("return_home_orientation")
          && confirmations.has("home_arrived"),
          failedChecks.has("home_stationary_arrival")
          || failedChecks.has("return_home_orientation")
        ),
      },
      {
        id: "sit",
        label: "Sit down",
        status: status(confirmations.has("sitting_complete")),
      },
      {
        id: "final-stop",
        label: "Final safety STOP",
        status: status(
          passedChecks.has("final_stop") && passedChecks.has("final_stop_invariants"),
          failedChecks.has("final_stop") || failedChecks.has("final_stop_invariants")
        ),
      },
    ];
  }

  function resultStatus(report, completed, requested, safe) {
    if (report.status === "passed" || report.passed === true) {
      return safe ? "passed" : "failed";
    }
    if (report.status === "failed") return "failed";
    if (report.finished_at && report.passed === false) return "failed";
    if (requested > 0 && completed >= requested && report.passed === false) {
      return "failed";
    }
    return "running";
  }

  function synthesizedSequence(report, status, completed, requested, safe) {
    const hasStarted = completed > 0 || Boolean(report.started_at);
    return [
      {
        id: "initial-stop",
        label: "Initial safety STOP",
        status: hasStarted ? "passed" : "pending",
        evidence: hasStarted ? "Run artifact created under a latched STOP." : "",
      },
      {
        id: "show-sequence",
        label: requested
          ? `Arena show sequence (${completed}/${requested})`
          : "Arena show sequence",
        status: status === "failed"
          ? "failed"
          : status === "passed"
            ? "passed"
            : "running",
        evidence: `${completed} completed; ${report.passed_legs ?? completed} passed.`,
      },
      {
        id: "final-stop",
        label: "Final STOP invariants",
        status: safe ? "passed" : status === "failed" ? "failed" : "pending",
        evidence: safe
          ? "STOP latched, heartbeat stale, no active waypoint."
          : "Final safe state is not yet evidenced.",
      },
    ];
  }

  function normalizeAcceptance(report, nowMs = Date.now()) {
    if (!report || typeof report !== "object" || Array.isArray(report)) {
      throw new TypeError("acceptance report must be an object");
    }
    const conceptSequence = showSequence(report);
    const requested = Number(
      report.requested_steps ?? report.requested_legs ?? 0
    ) || (conceptSequence ? conceptSequence.length : 0);
    const completed = Number(
      report.completed_steps
        ?? report.completed_legs
        ?? (conceptSequence
          ? conceptSequence.filter((step) => step.status === "passed").length
          : report.passed ? requested || 1 : 0)
    );
    const safe = finalStopIsSafe(report.final_state);
    const status = resultStatus(report, completed, requested, safe);
    const sequence = conceptSequence
      || (Array.isArray(report.sequence) && report.sequence.length
      ? report.sequence.map((step, index) => ({
          id: String(step.id || `step-${index + 1}`),
          label: String(step.label || step.name || `Step ${index + 1}`),
          status: ["passed", "failed", "running", "pending"].includes(step.status)
            ? step.status
            : step.passed === true
              ? "passed"
              : step.passed === false
                ? "failed"
                : "pending",
          evidence: String(step.evidence || step.detail || ""),
        }))
      : synthesizedSequence(report, status, completed, requested, safe));
    const checks = Array.isArray(report.checks) ? report.checks : [];
    const evidence = checks
      .filter((check) =>
        check
        && (
          check.passed === false
          || ["waypoint_arrival", "sustained_arrival", "heartbeat_loss_stop",
              "gate_stationary_arrival", "gate_orientation",
              "home_stationary_arrival", "return_home_orientation",
              "show_duration", "final_stop", "final_stop_invariants", "gateway_latency"]
            .includes(check.name)
        )
      )
      .slice(-6)
      .map((check) => ({
        label: String(check.name || "check").replaceAll("_", " "),
        detail: String(check.detail || ""),
        passed: check.passed === true,
      }));
    if (!evidence.length) {
      evidence.push({
        label: "sequence progress",
        detail: `${completed}/${requested || "—"} complete`,
        passed: status !== "failed",
      });
      evidence.push({
        label: "final STOP",
        detail: safe ? "safe invariants evidenced" : "awaiting final evidence",
        passed: safe,
      });
    }
    return {
      status,
      requested,
      completed,
      elapsed_s: elapsedSeconds(report, nowMs),
      safe,
      sequence,
      evidence,
      artifact_url: report.artifact_url || report.evidence_url || "",
      viewer_url: report.viewer_url || report.visualization_url || "",
      message: String(report.message || ""),
    };
  }

  function formatElapsed(seconds) {
    if (!Number.isFinite(seconds)) return "—";
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    return hours
      ? `${hours}h ${String(minutes).padStart(2, "0")}m`
      : `${minutes}m ${String(remainder).padStart(2, "0")}s`;
  }

  function setList(id, values, render) {
    const list = document.querySelector(`#${id}`);
    list.replaceChildren();
    values.forEach((value) => {
      const item = document.createElement("li");
      item.className = value.status || (value.passed ? "passed" : "failed");
      item.textContent = render(value);
      list.appendChild(item);
    });
  }

  function renderAcceptance(value) {
    const result = document.querySelector("#acceptance-result");
    result.className = `badge ${value.status}`;
    result.textContent = value.status.toUpperCase();
    document.querySelector("#acceptance-progress").textContent =
      `Sequence ${value.completed}/${value.requested || "—"}`;
    document.querySelector("#acceptance-elapsed").textContent =
      `Elapsed ${formatElapsed(value.elapsed_s)}`;
    const safety = document.querySelector("#safety-state");
    safety.className = value.safe ? "safe" : "unsafe";
    safety.textContent = value.safe ? "Safety · final STOP" : "Safety · not final";
    setList("sequence-list", value.sequence, (step) =>
      step.evidence ? `${step.label} — ${step.evidence}` : step.label
    );
    setList("evidence-list", value.evidence, (item) =>
      item.detail ? `${item.label}: ${item.detail}` : item.label
    );
    const message = document.querySelector("#acceptance-message");
    message.textContent = value.message
      || (value.status === "running"
        ? "Qualification evidence refreshes every five seconds."
        : "Result is backed by the saved acceptance artifact.");
    const artifact = document.querySelector("#artifact-link");
    artifact.hidden = !value.artifact_url;
    if (value.artifact_url) artifact.href = value.artifact_url;
  }

  async function refreshAcceptance() {
    try {
      const response = await fetch(ACCEPTANCE_URL, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderAcceptance(normalizeAcceptance(await response.json()));
    } catch (error) {
      const result = document.querySelector("#acceptance-result");
      result.className = "badge failed";
      result.textContent = "UNAVAILABLE";
      document.querySelector("#acceptance-message").textContent =
        `Acceptance evidence unavailable: ${error.message}`;
    }
  }

  const api = { finalStopIsSafe, elapsedSeconds, normalizeAcceptance, formatElapsed };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.PawGuideAcceptance = api;

  if (
    typeof document !== "undefined"
    && document.querySelector("#acceptance-panel")
  ) {
    refreshAcceptance();
    setInterval(refreshAcceptance, 5000);
  }
})(typeof window !== "undefined" ? window : globalThis);

(function (root) {
  "use strict";

  const TARGETS = Object.freeze({
    sim: "/admin/api/sim",
    physical: "/admin/api/physical",
  });

  function newCommandId() {
    if (root.crypto?.randomUUID) return root.crypto.randomUUID();
    const bytes = new Uint8Array(16);
    if (root.crypto?.getRandomValues) {
      root.crypto.getRandomValues(bytes);
    } else {
      for (let index = 0; index < bytes.length; index += 1) {
        bytes[index] = Math.floor(Math.random() * 256);
      }
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0"));
    return [
      hex.slice(0, 4).join(""),
      hex.slice(4, 6).join(""),
      hex.slice(6, 8).join(""),
      hex.slice(8, 10).join(""),
      hex.slice(10).join(""),
    ].join("-");
  }

  function commandEnvelope(action, argumentsValue = {}, explicitCommandId) {
    return {
      command_id: explicitCommandId || newCommandId(),
      action,
      arguments: argumentsValue,
    };
  }

  function mayDispatch({ connected, heartbeat }) {
    return Boolean(connected && heartbeat);
  }

  function mayMove({ connected, heartbeat, stopLatched }) {
    return mayDispatch({ connected, heartbeat })
      && stopLatched === false;
  }

  function createControlCenter(doc, storage = root.localStorage) {
    const state = {
      connected: false,
      capabilities: null,
      heartbeatTimer: null,
      heartbeat: false,
      stopLatched: null,
    };
    const byId = (id) => doc.querySelector(`#${id}`);
    const actionButtons = [...doc.querySelectorAll("[data-action]")];

    function target() {
      return byId("gateway-target").value;
    }

    function baseUrl() {
      return TARGETS[target()];
    }

    function token() {
      return byId("operator-token").value.trim();
    }

    function log(message, detail) {
      const output = byId("command-log");
      const stamp = new Date().toLocaleTimeString();
      const suffix = detail === undefined
        ? ""
        : ` ${typeof detail === "string" ? detail : JSON.stringify(detail)}`;
      output.textContent = `[${stamp}] ${message}${suffix}\n${output.textContent}`
        .slice(0, 8000);
    }

    async function request(path, options = {}) {
      if (!token()) throw new Error("operator token required");
      const response = await fetch(`${baseUrl()}${path}`, {
        cache: "no-store",
        ...options,
        headers: {
          Authorization: `Bearer ${token()}`,
          ...(options.body ? { "Content-Type": "application/json" } : {}),
          ...(options.headers || {}),
        },
      });
      let body = null;
      try {
        body = await response.json();
      } catch (_) {
        body = { detail: `HTTP ${response.status}` };
      }
      if (!response.ok) {
        const reason = typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body);
        throw new Error(`${response.status}: ${reason}`);
      }
      return body;
    }

    function renderState(snapshot) {
      if (!snapshot) return;
      byId("control-stop").textContent = snapshot.stop_latched ? "LATCHED" : "released";
      byId("control-heartbeat").textContent =
        snapshot.operator_heartbeat_fresh ? "fresh" : state.heartbeat ? "starting" : "off";
      byId("control-mission").textContent = snapshot.mission_state || "—";
      byId("control-waypoint").textContent = snapshot.active_waypoint || "—";
      state.stopLatched = snapshot.stop_latched === true;
    }

    function renderControls() {
      const physical = target() === "physical";
      byId("heartbeat-command").textContent =
        state.heartbeat ? "Stop heartbeat" : "Start heartbeat";
      byId("control-connection").textContent =
        state.connected ? "connected" : "disconnected";
      const dispatchReady = mayDispatch({
        connected: state.connected,
        heartbeat: state.heartbeat,
      });
      const movementReady = mayMove({
        connected: state.connected,
        heartbeat: state.heartbeat,
        stopLatched: state.stopLatched,
      });
      actionButtons.forEach((button) => {
        button.disabled = !movementReady;
      });
      byId("arm-command").disabled = !dispatchReady;
      byId("heartbeat-command").disabled = !state.connected;
      byId("stop-command").disabled =
        !state.connected || !token();
      byId("tag-waypoint-command").disabled = !(
        dispatchReady
        && physical
        && state.stopLatched === true
      );

      const guidance = byId("control-guidance");
      guidance.className = movementReady ? "ready" : "";
      if (!state.connected) {
        guidance.textContent =
          "Enter the operator token and press Connect. Controls will become live automatically.";
      } else if (!state.heartbeat) {
        guidance.textContent = "Connection is live; restarting the control heartbeat…";
      } else if (state.stopLatched !== false) {
        guidance.textContent =
          "STOP is latched. Press Resume after STOP to make movement controls live.";
      } else {
        guidance.textContent =
          "Ready: STOP is released. Sit, Stand, and the other bounded actions are enabled.";
      }
    }

    async function refreshState() {
      const snapshot = await request("/v1/state");
      renderState(snapshot);
      renderControls();
      return snapshot;
    }

    async function connect() {
      stopHeartbeat(false);
      state.connected = false;
      renderControls();
      try {
        const [capabilities, snapshot] = await Promise.all([
          request("/v1/capabilities"),
          request("/v1/state"),
        ]);
        state.capabilities = capabilities;
        state.connected = true;
        byId("control-adapter").textContent =
          `${capabilities.adapter}${capabilities.motion_capable ? " · motion" : " · no motion"}`;
        const waypoint = byId("waypoint-command");
        waypoint.replaceChildren();
        capabilities.allowed_waypoints.forEach((name) => {
          const option = doc.createElement("option");
          option.value = name;
          option.textContent = name;
          waypoint.appendChild(option);
        });
        renderState(snapshot);
        log(`Connected to ${target()} gateway`, {
          adapter: capabilities.adapter,
          motion_capable: capabilities.motion_capable,
          waypoints: capabilities.allowed_waypoints,
        });
        renderControls();
        await toggleHeartbeat();
        await sendCommand("reset_stop");
      } catch (error) {
        byId("control-adapter").textContent = "—";
        log("Connection failed", error.message);
      }
      renderControls();
    }

    async function heartbeatOnce() {
      try {
        const snapshot = await request("/v1/heartbeat", {
          method: "POST",
          body: JSON.stringify({ source: "tailscale-admin-control-center" }),
        });
        renderState(snapshot);
        renderControls();
      } catch (error) {
        log("Heartbeat failed; lease stopped", error.message);
        stopHeartbeat(false);
      }
    }

    function stopHeartbeat(writeLog = true) {
      if (state.heartbeatTimer !== null) {
        root.clearInterval(state.heartbeatTimer);
        state.heartbeatTimer = null;
      }
      const wasActive = state.heartbeat;
      state.heartbeat = false;
      if (writeLog && wasActive) {
        log("Heartbeat stopped; gateway watchdog will latch STOP");
      }
      renderControls();
    }

    async function toggleHeartbeat() {
      if (state.heartbeat) {
        stopHeartbeat();
        return;
      }
      state.heartbeat = true;
      await heartbeatOnce();
      if (!state.heartbeat) return;
      state.heartbeatTimer = root.setInterval(heartbeatOnce, 500);
      log("Operator heartbeat started at 500 ms");
      renderControls();
    }

    async function sendCommand(action, argumentsValue = {}) {
      const dispatchReady = mayDispatch({
        connected: state.connected,
        heartbeat: state.heartbeat,
      });
      if (action !== "stop" && !dispatchReady) {
        throw new Error("connect and start the heartbeat first");
      }
      if (
        action !== "stop"
        && action !== "reset_stop"
        && state.stopLatched !== false
      ) {
        throw new Error("press Resume after STOP before issuing movement");
      }
      log(`Sending ${action}…`);
      const result = await request("/v1/commands", {
        method: "POST",
        body: JSON.stringify(commandEnvelope(action, argumentsValue)),
      });
      log(`${action}: ${result.accepted ? "accepted" : "rejected"}`, result.reason);
      if (action === "stop") stopHeartbeat(false);
      await refreshState();
      return result;
    }

    async function tagWaypoint() {
      if (
        target() !== "physical"
        || !state.heartbeat
        || state.stopLatched !== true
      ) {
        throw new Error(
          "physical target, fresh heartbeat, and latched STOP are required"
        );
      }
      const waypointId = byId("waypoint-command").value;
      const result = await request(
        `/v1/commissioning/waypoints/${encodeURIComponent(waypointId)}`,
        {
          method: "POST",
          body: JSON.stringify({ confirm_stationary: true }),
        }
      );
      log(`Recorded exact waypoint ${waypointId}`, result.detail);
      return result;
    }

    function initializeChecklists() {
      doc.querySelectorAll("[data-checklist]").forEach((list) => {
        const name = list.dataset.checklist;
        const boxes = [...list.querySelectorAll('input[type="checkbox"]')];
        let saved = {};
        try {
          saved = JSON.parse(storage.getItem(`pawguide-checklist-${name}`) || "{}");
        } catch (_) {
          saved = {};
        }
        const update = () => {
          const values = Object.fromEntries(boxes.map((box) => [box.value, box.checked]));
          storage.setItem(`pawguide-checklist-${name}`, JSON.stringify(values));
          const complete = boxes.filter((box) => box.checked).length;
          doc.querySelector(`[data-progress="${name}"]`).textContent =
            `${complete}/${boxes.length} confirmed`;
        };
        boxes.forEach((box) => {
          box.checked = saved[box.value] === true;
          box.addEventListener("change", update);
        });
        update();
      });
    }

    byId("connect-command").addEventListener("click", connect);
    byId("refresh-command").addEventListener("click", () =>
      refreshState().catch((error) => log("State refresh failed", error.message))
    );
    byId("heartbeat-command").addEventListener("click", () =>
      toggleHeartbeat().catch((error) => log("Heartbeat failed", error.message))
    );
    byId("arm-command").addEventListener("click", () =>
      sendCommand("reset_stop").catch((error) => log("Arm failed", error.message))
    );
    byId("stop-command").addEventListener("click", () =>
      sendCommand("stop").catch((error) => log("STOP failed", error.message))
    );
    byId("go-command").addEventListener("click", () =>
      sendCommand("go_to_waypoint", {
        waypoint_id: byId("waypoint-command").value,
      }).catch((error) => log("Waypoint command failed", error.message))
    );
    byId("tag-waypoint-command").addEventListener("click", () =>
      tagWaypoint().catch((error) => log("Waypoint recording failed", error.message))
    );
    actionButtons
      .filter((button) => button.id !== "go-command")
      .forEach((button) => {
        button.addEventListener("click", () =>
          sendCommand(button.dataset.action)
            .catch((error) => log(`${button.dataset.action} failed`, error.message))
        );
      });
    byId("gateway-target").addEventListener("change", () => {
      stopHeartbeat(false);
      state.connected = false;
      renderControls();
      log(`Target changed to ${target()}; reconnect required`);
    });
    byId("operator-token").addEventListener("input", renderControls);
    doc.querySelectorAll('[role="tab"]').forEach((tab) => {
      tab.addEventListener("click", () => {
        doc.querySelectorAll('[role="tab"]').forEach((item) =>
          item.setAttribute("aria-selected", String(item === tab))
        );
        doc.querySelectorAll(".tab-panel").forEach((panel) => {
          panel.hidden = panel.id !== tab.dataset.tab;
        });
      });
    });
    root.addEventListener("pagehide", () => stopHeartbeat(false));
    initializeChecklists();
    renderControls();

    return {
      state,
      connect,
      sendCommand,
      tagWaypoint,
      stopHeartbeat,
      refreshState,
    };
  }

  const api = {
    TARGETS,
    newCommandId,
    commandEnvelope,
    mayDispatch,
    mayMove,
    createControlCenter,
  };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { ...module.exports, ...api };
  }
  root.PawGuideControls = api;

  if (
    typeof document !== "undefined"
    && document.querySelector("#operator-token")
  ) {
    createControlCenter(document);
  }
})(typeof window !== "undefined" ? window : globalThis);

(function (root) {
  "use strict";

  if (
    typeof document === "undefined"
    || !document.querySelector("#action-grid")
  ) return;

  const BASE_URL = "/admin/api/physical";
  const state = {
    connected: false,
    heartbeat: false,
    heartbeatTimer: null,
    reconnectTimer: null,
    connectPromise: null,
    stopLatched: null,
    busy: false,
  };
  const byId = (id) => document.querySelector(`#${id}`);
  const actionButtons = [...document.querySelectorAll("[data-action]")];
  const roundTripButton = byId("round-trip-command");

  function log(message, detail) {
    const stamp = new Date().toLocaleTimeString();
    const suffix = detail === undefined
      ? ""
      : ` ${typeof detail === "string" ? detail : JSON.stringify(detail)}`;
    const output = byId("command-log");
    output.textContent = `[${stamp}] ${message}${suffix}\n${output.textContent}`
      .slice(0, 5000);
  }

  async function request(path, options = {}) {
    const response = await fetch(`${BASE_URL}${path}`, {
      cache: "no-store",
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    let body;
    try {
      body = await response.json();
    } catch (_) {
      body = { detail: `HTTP ${response.status}` };
    }
    if (!response.ok) {
      const reason = typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body);
      throw new Error(`${response.status}: ${reason}`);
    }
    return body;
  }

  function renderState(snapshot) {
    if (!snapshot) return;
    state.stopLatched = snapshot.stop_latched === true;
    byId("control-stop").textContent =
      state.stopLatched ? "LATCHED" : "released";
    byId("control-heartbeat").textContent =
      snapshot.operator_heartbeat_fresh ? "fresh" : state.heartbeat ? "starting…" : "offline";
    byId("control-mission").textContent = snapshot.mission_state || "—";
  }

  function renderControls() {
    byId("control-connection").textContent =
      state.connected ? "connected" : "connecting…";
    actionButtons.forEach((button) => {
      button.disabled = !state.connected || !state.heartbeat || state.busy;
    });
    roundTripButton.disabled = !state.connected || !state.heartbeat || state.busy;
    const guidance = byId("control-guidance");
    const ready = state.connected && state.heartbeat && !state.busy;
    guidance.className = ready ? "ready" : "";
    guidance.textContent = state.busy
      ? "Sending command…"
      : ready
        ? "Ready. Press any action button."
        : "Connecting to the physical Go2…";
    const x5 = byId("x5");
    x5.className = state.connected ? "status ok" : "status fail";
    x5.textContent = state.connected ? "X5 connected" : "X5 reconnecting…";
  }

  function scheduleReconnect() {
    if (state.reconnectTimer !== null) return;
    state.reconnectTimer = root.setTimeout(() => {
      state.reconnectTimer = null;
      connect();
    }, 1000);
  }

  async function heartbeatOnce() {
    try {
      const snapshot = await request("/v1/heartbeat", {
        method: "POST",
        body: JSON.stringify({ source: "tailscale-admin-kiosk" }),
      });
      renderState(snapshot);
      renderControls();
    } catch (error) {
      state.connected = false;
      state.heartbeat = false;
      if (state.heartbeatTimer !== null) {
        root.clearInterval(state.heartbeatTimer);
        state.heartbeatTimer = null;
      }
      log("Connection lost", error.message);
      renderControls();
      scheduleReconnect();
    }
  }

  async function startHeartbeat() {
    if (state.heartbeat) return;
    state.heartbeat = true;
    await heartbeatOnce();
    if (!state.heartbeat) return;
    state.heartbeatTimer = root.setInterval(heartbeatOnce, 500);
  }

  async function connect() {
    if (state.connectPromise) return state.connectPromise;
    state.connectPromise = (async () => {
      try {
        const [capabilities, snapshot] = await Promise.all([
          request("/v1/capabilities"),
          request("/v1/state"),
        ]);
        if (!capabilities.motion_capable) {
          throw new Error("physical motion adapter is unavailable");
        }
        state.connected = true;
        renderState(snapshot);
        renderControls();
        await startHeartbeat();
        log("Physical Go2 ready", { adapter: capabilities.adapter });
      } catch (error) {
        state.connected = false;
        state.heartbeat = false;
        log("Connection failed", error.message);
        renderControls();
        scheduleReconnect();
      } finally {
        state.connectPromise = null;
      }
    })();
    return state.connectPromise;
  }

  async function postCommand(action, argumentsValue = {}) {
    log(`Sending ${action}…`);
    const result = await request("/v1/commands", {
      method: "POST",
      body: JSON.stringify(
        root.PawGuideControls.commandEnvelope(action, argumentsValue)
      ),
    });
    log(`${action}: ${result.accepted ? "accepted" : "rejected"}`, result.reason);
    if (!result.accepted) {
      throw new Error(result.reason || `${action} rejected`);
    }
    return result;
  }

  async function ensureMovementReady() {
    if (!state.connected) await connect();
    if (!state.connected) throw new Error("X5 is offline");
    if (!state.heartbeat) await startHeartbeat();
    if (!state.heartbeat) throw new Error("control heartbeat is offline");
    const snapshot = await request("/v1/state");
    renderState(snapshot);
    if (state.stopLatched !== false) {
      await postCommand("reset_stop");
      renderState(await request("/v1/state"));
    }
  }

  async function sendAction(action) {
    if (action === "stop") {
      try {
        if (!state.connected) await connect();
        await postCommand("stop");
        renderState(await request("/v1/state"));
      } catch (error) {
        log("STOP failed", error.message);
      } finally {
        renderControls();
      }
      return;
    }
    if (state.busy) return;
    state.busy = true;
    renderControls();
    try {
      await ensureMovementReady();
      await postCommand(action);
      renderState(await request("/v1/state"));
    } catch (error) {
      log(`${action} failed`, error.message);
    } finally {
      state.busy = false;
      renderControls();
    }
  }

  byId("stop-command").addEventListener("click", () => sendAction("stop"));
  actionButtons.forEach((button) => {
    button.addEventListener("click", () => sendAction(button.dataset.action));
  });
  roundTripButton.addEventListener("click", async () => {
    if (state.busy) return;
    state.busy = true;
    renderControls();
    try {
      await ensureMovementReady();
      await postCommand("go_to_waypoint", { waypoint_id: "demo_gate" });
      await new Promise((resolve) => root.setTimeout(resolve, 1000));
      await postCommand("return_home");
      renderState(await request("/v1/state"));
      log("1 m round trip complete");
    } catch (error) {
      log("Round trip failed", error.message);
    } finally {
      state.busy = false;
      renderControls();
    }
  });
  root.addEventListener("pagehide", () => {
    if (state.heartbeatTimer !== null) root.clearInterval(state.heartbeatTimer);
    if (state.reconnectTimer !== null) root.clearTimeout(state.reconnectTimer);
  });

  renderControls();
  connect();
})(typeof window !== "undefined" ? window : globalThis);
