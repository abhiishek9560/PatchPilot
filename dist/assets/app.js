const apiMode = ["localhost", "127.0.0.1"].includes(window.location.hostname);

const demoRun = () => ({
  id: "public-demo",
  status: "awaiting_plan_approval",
  issue: {
    repository: "acme/accounts-api",
    number: 142,
    title: "Email validator accepts incomplete domains",
  },
  failure: null,
  pr_url: null,
});

let currentRun = demoRun();

const statusLabels = {
  received: "Issue received",
  inspecting: "Inspecting repository",
  reproduced: "Defect reproduced",
  awaiting_plan_approval: "Awaiting plan approval",
  patching: "Applying patch",
  verifying: "Verifying patch",
  reviewing: "Reviewing evidence",
  awaiting_publish_approval: "Awaiting publish approval",
  completed: "Draft PR created",
  rejected: "Run rejected",
  failed: "Failed safely",
};

const steps = [
  ["received", "Issue accepted", "Repository and scope recorded"],
  ["reproduced", "Defect reproduced", "Baseline test failed as reported"],
  ["awaiting_plan_approval", "Plan approval", "Human review before any write"],
  ["verifying", "Patch and verify", "Policy-checked change and tests"],
  ["awaiting_publish_approval", "Publish approval", "Separate decision before GitHub"],
  ["completed", "Draft pull request", "Reviewable output; never auto-merged"],
];

const rank = {
  received: 0,
  inspecting: 0,
  reproduced: 1,
  awaiting_plan_approval: 2,
  patching: 3,
  verifying: 3,
  reviewing: 3,
  awaiting_publish_approval: 4,
  completed: 5,
};

function showToast(title, message) {
  const toast = document.getElementById("toast");
  toast.querySelector("strong").textContent = title;
  toast.querySelector("span").textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 3200);
}

function showView(name) {
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id === `view-${name}`);
  });
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.classList.toggle("active", link.dataset.view === name);
  });
  document.getElementById("sidebar").classList.remove("open");
  history.replaceState(null, "", `#${name}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.querySelectorAll(".nav-link").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    showView(link.dataset.view);
  });
});

document.getElementById("menuButton").addEventListener("click", () => {
  document.getElementById("sidebar").classList.toggle("open");
});

function renderTimeline() {
  const terminalFailure = ["failed", "rejected"].includes(currentRun.status);
  const currentRank = rank[currentRun.status] ?? 0;
  document.getElementById("timeline").innerHTML = steps.map(([state, title, copy], index) => {
    let type = "future";
    let mark = "·";
    if (terminalFailure && index === Math.min(currentRank + 1, steps.length - 1)) {
      type = "failed";
      mark = "×";
    } else if (index < currentRank || currentRun.status === "completed") {
      type = "done";
      mark = "✓";
    } else if (index === currentRank) {
      type = "pending";
      mark = currentRun.status.includes("approval") ? "Ⅱ" : "↻";
    }
    return `<div class="timeline-step ${type}"><i>${mark}</i><strong>${title}</strong><small>${copy}</small></div>`;
  }).join("");
}

function renderRun() {
  const statusBadge = document.getElementById("statusBadge");
  statusBadge.textContent = statusLabels[currentRun.status] || currentRun.status;
  statusBadge.className = "status";
  if (currentRun.status === "completed") statusBadge.classList.add("success");
  if (["failed", "rejected"].includes(currentRun.status)) statusBadge.classList.add("failed");

  const box = document.getElementById("decisionBox");
  const title = document.getElementById("decisionTitle");
  const copy = document.getElementById("decisionCopy");
  const approve = document.getElementById("approveButton");
  const reject = document.getElementById("rejectButton");
  box.className = "decision";
  approve.disabled = false;
  reject.disabled = false;
  reject.hidden = false;

  if (currentRun.status === "awaiting_plan_approval") {
    title.textContent = "Approve the repair plan?";
    copy.textContent = "No file has been modified. Approval allows one policy-checked patch.";
    approve.textContent = "Approve plan";
  } else if (currentRun.status === "awaiting_publish_approval") {
    title.textContent = "Create the draft pull request?";
    copy.textContent = "The patch passed verification and scope review. V1 still cannot merge.";
    approve.textContent = "Create draft PR";
    document.getElementById("runFinding").textContent = "The approved one-file patch now rejects incomplete domains. The focused regression suite passes and policy review found no scope violations.";
  } else if (currentRun.status === "completed") {
    box.classList.add("complete");
    title.textContent = "Run complete";
    copy.textContent = "A draft PR record was created after both approvals. No merge or deployment occurred.";
    approve.textContent = "Completed";
    approve.disabled = true;
    reject.hidden = true;
  } else if (currentRun.status === "rejected") {
    box.classList.add("failed");
    title.textContent = "Run rejected by reviewer";
    copy.textContent = "The decision was recorded and no further side effect was allowed.";
    approve.textContent = "Stopped";
    approve.disabled = true;
    reject.hidden = true;
  } else if (currentRun.status === "failed") {
    box.classList.add("failed");
    title.textContent = "Run failed safely";
    copy.textContent = currentRun.failure || "The workflow stopped before publication.";
    approve.textContent = "Stopped";
    approve.disabled = true;
    reject.hidden = true;
  } else {
    title.textContent = "Agent is working";
    copy.textContent = "The workflow will pause again before any publication step.";
    approve.textContent = "Working…";
    approve.disabled = true;
    reject.disabled = true;
  }
  renderTimeline();
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "Request failed");
  return payload;
}

async function restartRun() {
  try {
    currentRun = apiMode
      ? await request("/api/runs/demo", { method: "POST", body: JSON.stringify({}) })
      : demoRun();
    document.getElementById("runFinding").innerHTML = "<code>user@example</code> is accepted even though the service requires a dotted domain. The baseline suite fails exactly as reported.";
    renderRun();
    showToast("Investigation complete", "The defect was reproduced and the plan is ready for review.");
  } catch (error) {
    showToast("Could not start run", error.message);
  }
}

async function approveRun() {
  try {
    if (apiMode) {
      const approval = currentRun.status === "awaiting_plan_approval" ? "plan" : "publish";
      currentRun = await request(`/api/runs/${currentRun.id}/approvals`, {
        method: "POST",
        body: JSON.stringify({ approval, actor: "demo-reviewer" }),
      });
    } else if (currentRun.status === "awaiting_plan_approval") {
      currentRun.status = "awaiting_publish_approval";
    } else if (currentRun.status === "awaiting_publish_approval") {
      currentRun.status = "completed";
      currentRun.pr_url = "https://github.com/acme/accounts-api/pull/demo";
    }
    const finished = currentRun.status === "completed";
    renderRun();
    showToast(finished ? "Draft PR created" : "Plan approved", finished
      ? "Publication approval was recorded. PatchPilot cannot merge it."
      : "The patch passed tests and paused at the second approval gate.");
  } catch (error) {
    showToast("Action failed", error.message);
  }
}

async function rejectRun() {
  try {
    if (apiMode) {
      currentRun = await request(`/api/runs/${currentRun.id}/rejection`, {
        method: "POST",
        body: JSON.stringify({ actor: "demo-reviewer", reason: "Reviewer stopped the demo run" }),
      });
    } else {
      currentRun.status = "rejected";
    }
    renderRun();
    showToast("Run safely stopped", "The rejection was recorded; no further action occurred.");
  } catch (error) {
    showToast("Action failed", error.message);
  }
}

document.getElementById("restartRun").addEventListener("click", restartRun);
document.getElementById("approveButton").addEventListener("click", approveRun);
document.getElementById("rejectButton").addEventListener("click", rejectRun);

async function initialize() {
  document.getElementById("modeLabel").textContent = apiMode
    ? "Connected to local FastAPI workflow"
    : "Interactive public demo";
  if (apiMode) {
    document.getElementById("truthTitle").textContent = "This dashboard is connected to the executable workflow.";
    document.getElementById("truthCopy").textContent = "Actions call the local FastAPI service and persist run state in SQLite.";
    try {
      const runs = await request("/api/runs");
      if (runs.length) currentRun = runs[0];
    } catch (error) {
      showToast("API unavailable", "Showing the interactive demo state instead.");
    }
  }
  renderRun();
  const initial = location.hash.slice(1);
  showView(["demo", "workflow", "project"].includes(initial) ? initial : "demo");
}

initialize();
