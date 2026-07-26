(function (root) {
  "use strict";

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
    const hex = [...bytes].map((value) =>
      value.toString(16).padStart(2, "0")
    );
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

  const helpers = { newCommandId, commandEnvelope, mayDispatch, mayMove };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = helpers;
  }
  root.PawGuideControls = helpers;

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
        : JSON.stringify(body.detail ?? body);
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
      snapshot.operator_heartbeat_fresh
        ? "fresh"
        : state.heartbeat
          ? "starting…"
          : "offline";
    byId("control-mission").textContent = snapshot.mission_state || "—";
  }

  function renderControls() {
    byId("control-connection").textContent =
      state.connected ? "connected" : "connecting…";
    actionButtons.forEach((button) => {
      button.disabled = !state.connected || !state.heartbeat || state.busy;
    });
    roundTripButton.disabled =
      !state.connected || !state.heartbeat || state.busy;
    const guidance = byId("control-guidance");
    const ready = state.connected && state.heartbeat && !state.busy;
    guidance.className = ready ? "ready" : "";
    guidance.textContent = state.busy
      ? "Waiting for the command result…"
      : ready
        ? "Ready. Press an action button."
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

  function stopHeartbeat() {
    if (state.heartbeatTimer !== null) {
      root.clearInterval(state.heartbeatTimer);
      state.heartbeatTimer = null;
    }
    state.heartbeat = false;
  }

  async function heartbeatOnce() {
    try {
      const snapshot = await request("/v1/heartbeat", {
        method: "POST",
        body: JSON.stringify({ source: "admin-kiosk" }),
      });
      renderState(snapshot);
      renderControls();
    } catch (error) {
      state.connected = false;
      stopHeartbeat();
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
        log("Physical Go2 ready", {
          adapter: capabilities.adapter,
          waypoints: capabilities.allowed_waypoints,
        });
      } catch (error) {
        state.connected = false;
        stopHeartbeat();
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
      body: JSON.stringify(commandEnvelope(action, argumentsValue)),
    });
    log(
      `${action}: ${result.accepted ? "accepted" : "rejected"}`,
      result.reason
    );
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
    renderState(await request("/v1/state"));
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
    button.addEventListener("click", () =>
      sendAction(button.dataset.action)
    );
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
    stopHeartbeat();
    if (state.reconnectTimer !== null) {
      root.clearTimeout(state.reconnectTimer);
    }
  });

  renderControls();
  connect();
})(typeof window !== "undefined" ? window : globalThis);
