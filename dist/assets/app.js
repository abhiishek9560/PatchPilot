let apiMode = false;
let currentAccount = null;
let authMode = "register";

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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeExternalUrl(value) {
  try {
    const url = new URL(String(value));
    return ["https:", "http:"].includes(url.protocol) ? escapeHtml(url.href) : "#";
  } catch (_error) {
    return "#";
  }
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
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const detail = payload?.detail;
    const message = typeof detail === "string" ? detail : "Request failed";
    throw new Error(message);
  }
  return payload;
}

function setAuthMode(mode) {
  authMode = mode;
  const registering = mode === "register";
  document.getElementById("authTitle").textContent = registering
    ? "Create your PatchPilot account"
    : "Sign in to PatchPilot";
  document.getElementById("displayNameField").hidden = !registering;
  document.getElementById("displayName").required = registering;
  document.getElementById("password").autocomplete = registering ? "new-password" : "current-password";
  document.getElementById("authSubmit").textContent = registering ? "Create account" : "Sign in";
  document.getElementById("authToggle").textContent = registering
    ? "Already registered? Sign in"
    : "Need an account? Register";
}

function renderResources(repositories = [], issues = [], workItems = []) {
  document.getElementById("repoCount").textContent = `${repositories.length} ${repositories.length === 1 ? "repository" : "repositories"}`;
  document.getElementById("issueCount").textContent = `${issues.length} ${issues.length === 1 ? "issue" : "issues"}`;
  document.getElementById("repositoryList").className = repositories.length ? "resource-list" : "empty-state";
  document.getElementById("repositoryList").innerHTML = repositories.length
    ? repositories.map((repository) => `<div class="resource-row"><div><strong>${escapeHtml(repository.full_name)}</strong><small>Default branch: ${escapeHtml(repository.default_branch)}</small></div><span>${repository.private ? "Private" : "Public"}</span></div>`).join("")
    : "Install the GitHub App to see repositories here.";
  document.getElementById("issueList").className = issues.length ? "resource-list" : "empty-state";
  document.getElementById("issueList").innerHTML = issues.length
    ? issues.map((issue) => `<div class="resource-row with-actions"><div><strong>#${Number(issue.number)} · ${escapeHtml(issue.title)}</strong><small>${escapeHtml(issue.full_name)}</small></div><div class="resource-row-actions"><span>${escapeHtml(issue.state)}</span><button class="button secondary mini assign-issue" data-repository-id="${Number(issue.repository_id)}" data-issue-number="${Number(issue.number)}">Assign</button></div></div>`).join("")
    : "Signed GitHub issue events will appear here.";
  const activeCount = workItems.filter((item) => !["completed", "failed", "rejected", "cancelled"].includes(item.status)).length;
  document.getElementById("workItemCount").textContent = `${activeCount} active`;
  document.getElementById("workItemList").className = workItems.length ? "resource-list" : "empty-state";
  document.getElementById("workItemList").innerHTML = workItems.length
    ? workItems.map((item) => {
      const approval = item.status === "awaiting_plan_approval"
        ? `<button class="button secondary mini suggest-plan" data-work-item-id="${escapeHtml(item.id)}">Suggest changes</button><button class="button primary mini approve-work" data-stage="plan" data-work-item-id="${escapeHtml(item.id)}">Approve plan</button>`
        : item.status === "awaiting_publish_approval"
          ? `<button class="button primary mini approve-work" data-stage="publish" data-work-item-id="${escapeHtml(item.id)}">Approve draft PR</button>`
          : `<span class="work-status">${escapeHtml(item.status.replaceAll("_", " "))}</span>`;
      const plan = item.plan
        ? `<details class="work-evidence" ${item.status === "awaiting_plan_approval" ? "open" : ""}><summary>Plan v${Number(item.plan_version)} · ${escapeHtml(item.plan.summary)}</summary><p>${escapeHtml(item.plan.reproduction || "")}</p><ol>${(item.plan.steps || []).map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol><small>Expected files: ${(item.plan.expected_files || []).map(escapeHtml).join(", ") || "Not specified"}</small></details>`
        : "";
      const patch = item.artifact?.patch
        ? `<details class="work-evidence"><summary>Review proposed patch · ${escapeHtml((item.artifact.patch.changed_files || []).join(", "))}</summary><p>${escapeHtml(item.artifact.patch.rationale || "")}</p><pre>${escapeHtml(item.artifact.patch.unified_diff || "")}</pre><small>${escapeHtml(item.artifact.verification?.note || "")}</small></details>`
        : "";
      const pullRequest = item.artifact?.pr_url
        ? `<a class="pr-link" href="${safeExternalUrl(item.artifact.pr_url)}" target="_blank" rel="noopener noreferrer">Open draft PR #${Number(item.artifact.pr_number)}</a>`
        : "";
      return `<article class="resource-row work-item"><div class="work-item-copy"><strong>#${Number(item.issue_number)} · ${escapeHtml(item.issue_title)}</strong><small>${escapeHtml(item.full_name)} · ${escapeHtml(item.status.replaceAll("_", " "))}</small>${plan}${patch}${pullRequest}</div><div class="resource-row-actions">${approval}</div></article>`;
    }).join("")
    : "Assign an issue to create a durable planning job.";
}

async function renderAccount() {
  const signedIn = Boolean(currentAccount);
  document.getElementById("signedOutPanel").hidden = signedIn;
  document.getElementById("signedInPanel").hidden = !signedIn;
  document.getElementById("accountButton").textContent = signedIn
    ? currentAccount.user.display_name
    : "Sign in";
  if (!signedIn) {
    renderResources();
    return;
  }
  document.getElementById("accountName").textContent = currentAccount.organizations[0]?.name || "Your workspace";
  try {
    const [repositories, issues, workItems] = await Promise.all([
      request("/api/repositories"),
      request("/api/issues"),
      request("/api/work-items"),
    ]);
    renderResources(repositories, issues, workItems);
  } catch (error) {
    showToast("Could not load workspace", error.message);
  }
}

async function submitAuth(event) {
  event.preventDefault();
  if (!apiMode) {
    showToast("Backend not connected", "Open this dashboard from the PatchPilot API to create an account.");
    return;
  }
  const payload = {
    email: document.getElementById("email").value,
    password: document.getElementById("password").value,
  };
  if (authMode === "register") payload.display_name = document.getElementById("displayName").value;
  try {
    currentAccount = await request(`/api/auth/${authMode}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    document.getElementById("authForm").reset();
    await renderAccount();
    showToast(authMode === "register" ? "Account created" : "Signed in", "Your workspace session is active.");
  } catch (error) {
    showToast("Account action failed", error.message);
  }
}

async function logout() {
  try {
    if (apiMode) await request("/api/auth/logout", { method: "POST" });
    currentAccount = null;
    setAuthMode("login");
    await renderAccount();
    showToast("Signed out", "The browser session has been revoked.");
  } catch (error) {
    showToast("Sign out failed", error.message);
  }
}

async function connectGithub() {
  if (!currentAccount?.organizations?.length) return;
  try {
    const organizationId = encodeURIComponent(currentAccount.organizations[0].id);
    const result = await request(`/api/github/connect?organization_id=${organizationId}`, { method: "POST" });
    window.location.assign(result.install_url);
  } catch (error) {
    showToast("GitHub connection unavailable", error.message);
  }
}

async function assignIssue(repositoryId, issueNumber) {
  try {
    await request(`/api/issues/${repositoryId}/${issueNumber}/assign`, {
      method: "POST",
      body: JSON.stringify({ selection_mode: "manual" }),
    });
    await renderAccount();
    showToast("Issue assigned", "A durable planning job is ready for the PatchPilot worker.");
  } catch (error) {
    showToast("Assignment failed", error.message);
  }
}

async function autoAssignIssue() {
  if (!currentAccount?.organizations?.length) return;
  try {
    const organizationId = encodeURIComponent(currentAccount.organizations[0].id);
    await request(`/api/issues/auto-assign?organization_id=${organizationId}`, { method: "POST" });
    await renderAccount();
    showToast("Issue selected", "PatchPilot chose the next unassigned open issue.");
  } catch (error) {
    showToast("No issue selected", error.message);
  }
}

async function approveProductWork(workItemId, stage) {
  try {
    await request(`/api/work-items/${workItemId}/approvals`, {
      method: "POST",
      body: JSON.stringify({ stage }),
    });
    await renderAccount();
    showToast("Approval recorded", stage === "plan" ? "The patch job is now queued." : "Draft PR publication is now queued.");
  } catch (error) {
    showToast("Approval failed", error.message);
  }
}

async function suggestPlanChange(workItemId) {
  const message = window.prompt("What should PatchPilot change in this plan?");
  if (!message) return;
  try {
    await request(`/api/work-items/${workItemId}/plan-feedback`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    await renderAccount();
    showToast("Feedback recorded", "A new plan revision job is queued.");
  } catch (error) {
    showToast("Feedback failed", error.message);
  }
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
document.getElementById("accountButton").addEventListener("click", () => showView("product"));
document.getElementById("authForm").addEventListener("submit", submitAuth);
document.getElementById("authToggle").addEventListener("click", () => setAuthMode(authMode === "register" ? "login" : "register"));
document.getElementById("logoutButton").addEventListener("click", logout);
document.getElementById("connectGithub").addEventListener("click", connectGithub);
document.getElementById("autoAssign").addEventListener("click", autoAssignIssue);
document.getElementById("issueList").addEventListener("click", (event) => {
  const button = event.target.closest(".assign-issue");
  if (button) assignIssue(Number(button.dataset.repositoryId), Number(button.dataset.issueNumber));
});
document.getElementById("workItemList").addEventListener("click", (event) => {
  const approval = event.target.closest(".approve-work");
  const suggestion = event.target.closest(".suggest-plan");
  if (approval) approveProductWork(approval.dataset.workItemId, approval.dataset.stage);
  if (suggestion) suggestPlanChange(suggestion.dataset.workItemId);
});

async function initialize() {
  try {
    const health = await request("/api/health");
    apiMode = health?.status === "ok";
  } catch (_error) {
    apiMode = false;
  }
  document.getElementById("modeLabel").textContent = apiMode
    ? "Connected to PatchPilot API"
    : "Interactive public demo";
  if (apiMode) {
    document.getElementById("truthTitle").textContent = "This dashboard is connected to the executable workflow.";
    document.getElementById("truthCopy").textContent = "Actions call the FastAPI service and persist workflow and account state.";
    try {
      const [runs, account] = await Promise.all([
        request("/api/runs"),
        request("/api/auth/me").catch(() => null),
      ]);
      if (runs.length) currentRun = runs[0];
      currentAccount = account;
    } catch (error) {
      showToast("API unavailable", "Showing the interactive demo state instead.");
    }
  }
  setAuthMode("register");
  await renderAccount();
  renderRun();
  const initial = location.hash.slice(1);
  showView(["demo", "product", "workflow", "project"].includes(initial) ? initial : "demo");
  if (new URLSearchParams(location.search).get("github") === "connected") {
    showView("product");
    showToast("GitHub connected", "Selected repositories are ready; new issues will sync by webhook.");
  }
}

initialize();
window.setInterval(() => {
  if (apiMode && currentAccount && document.visibilityState === "visible") renderAccount();
}, 5000);
