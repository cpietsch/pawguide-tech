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
    if (value.viewer_url) {
      document.querySelector("#viewer-link").href = value.viewer_url;
    }
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

  if (typeof document !== "undefined") {
    refreshAcceptance();
    setInterval(refreshAcceptance, 5000);
  }
})(typeof window !== "undefined" ? window : globalThis);
