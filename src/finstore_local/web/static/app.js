(function () {
  "use strict";

  // ── Fetch-status polling ──────────────────────────────────────────────────
  // Polls /fetch/status while a job is running and updates the status section.

  const statusBox = document.getElementById("fetch-status");
  if (!statusBox) return;

  const sections = {
    idle:    document.getElementById("status-idle"),
    running: document.getElementById("status-running"),
    done:    document.getElementById("status-done"),
    error:   document.getElementById("status-error"),
  };
  const startBtn = document.getElementById("fetch-start-btn");

  function showState(state) {
    for (const [key, el] of Object.entries(sections)) {
      if (!el) continue;
      el.classList.toggle("hidden", key !== state);
    }
    if (startBtn) startBtn.disabled = (state === "running");
  }

  let pollTimer = null;

  function poll() {
    fetch("/fetch/status")
      .then(function (r) { return r.json(); })
      .then(function (job) {
        showState(job.state);
        if (job.state === "running") {
          pollTimer = setTimeout(poll, 2000);
        } else {
          // Reload so the report text (rendered server-side) is up to date.
          if (statusBox.dataset.jobState === "running") {
            window.location.reload();
          }
        }
      })
      .catch(function () {
        // Network error — keep trying.
        pollTimer = setTimeout(poll, 4000);
      });
  }

  const initialState = statusBox.dataset.jobState || "idle";
  showState(initialState);
  if (initialState === "running") {
    pollTimer = setTimeout(poll, 2000);
  }
})();
