const runs = [
  {
    id: "run-142",
    issue: 142,
    title: "Email validator accepts incomplete domains",
    repo: "acme/accounts-api",
    status: "awaiting_plan_approval",
    time: "2 minutes ago",
    summary: "The baseline suite reproduces the defect: user@example is accepted even though the API contract requires a dotted domain.",
  },
  {
    id: "run-139",
    issue: 139,
    title: "Pagination drops the final result",
    repo: "acme/accounts-api",
    status: "verifying",
    time: "18 minutes ago",
    summary: "A one-line boundary condition was patched. Focused and regression tests are running in the bounded workspace.",
  },
  {
    id: "run-133",
    issue: 133,
    title: "Normalize whitespace in profile names",
    repo: "acme/accounts-api",
    status: "completed",
    time: "Yesterday",
    summary: "The repair passed all configured tests and a draft pull request was created after human approval.",
  },
];

let selectedRunId = runs[0].id;

const statusInfo = {
  awaiting_plan_approval: ["Awaiting plan approval", "approval"],
  awaiting_publish_approval: ["Awaiting publish approval", "approval"],
  verifying: ["Verifying patch", "running"],
  completed: ["Draft PR created", "success"],
  received: ["Queued", "pending"],
};

const views = [...document.querySelectorAll(".view")];
const navItems = [...document.querySelectorAll(".nav-item")];

function showView(name) {
  views.forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  navItems.forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  history.replaceState(null, "", `#${name}`);
  document.getElementById("sidebar").classList.remove("open");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

navItems.forEach((item) => item.addEventListener("click", (event) => {
  event.preventDefault();
  showView(item.dataset.view);
}));
document.querySelectorAll("[data-view-target]").forEach((button) =>
  button.addEventListener("click", () => showView(button.dataset.viewTarget)),
);

function statusBadge(status) {
  const [label, type] = statusInfo[status] || [status, "pending"];
  return `<span class="status ${type}">${label}</span>`;
}

function renderRecentRuns() {
  document.getElementById("recentRuns").innerHTML = runs.map((run) => `
    <div class="run-row" data-run="${run.id}">
      <span class="issue-number">#${run.issue}</span>
      <div class="run-copy"><strong>${run.title}</strong><small>${run.repo}</small></div>
      ${statusBadge(run.status)}
      <span class="run-time">${run.time}</span><span class="row-arrow">›</span>
    </div>`).join("");
  document.querySelectorAll(".run-row").forEach((row) => row.addEventListener("click", () => {
    selectedRunId = row.dataset.run;
    renderRunList();
    renderDetail();
    showView("runs");
  }));
}

function renderRunList() {
  document.getElementById("runList").innerHTML = runs.map((run) => `
    <div class="run-list-item ${run.id === selectedRunId ? "active" : ""}" data-run="${run.id}">
      <div><span class="issue-number">#${run.issue}</span>${statusBadge(run.status)}</div>
      <strong>${run.title}</strong><small>${run.time} · ${run.repo}</small>
    </div>`).join("");
  document.querySelectorAll(".run-list-item").forEach((item) => item.addEventListener("click", () => {
    selectedRunId = item.dataset.run;
    renderRunList();
    renderDetail();
  }));
}

function detailAction(run) {
  if (run.status === "awaiting_plan_approval") return `
    <button class="danger-button" data-action="reject">Reject</button>
    <button class="primary-button" data-action="approve-plan">Approve plan</button>`;
  if (run.status === "awaiting_publish_approval") return `
    <button class="danger-button" data-action="reject">Reject</button>
    <button class="primary-button" data-action="approve-publish">Create draft PR</button>`;
  if (run.status === "completed") return `<button class="secondary-button" data-action="open-pr">View draft PR ↗</button>`;
  return `<button class="secondary-button" disabled>Agent working…</button>`;
}

function timelineFor(run) {
  const publishWait = run.status === "awaiting_publish_approval";
  const completed = run.status === "completed";
  const verifying = run.status === "verifying";
  return `
    <div class="timeline-item"><span>✓</span><strong>Issue received</strong><small>Scope and repository recorded</small></div>
    <div class="timeline-item"><span>✓</span><strong>Defect reproduced</strong><small>Baseline: 1 failed, 2 passed</small></div>
    <div class="timeline-item ${run.status === "awaiting_plan_approval" ? "pending" : ""}"><span>${run.status === "awaiting_plan_approval" ? "Ⅱ" : "✓"}</span><strong>Plan approval</strong><small>${run.status === "awaiting_plan_approval" ? "Waiting for your decision" : "Approved by reviewer"}</small></div>
    <div class="timeline-item ${verifying ? "pending" : ""}"><span>${run.status === "awaiting_plan_approval" ? "·" : (verifying ? "↻" : "✓")}</span><strong>Patch & verify</strong><small>${run.status === "awaiting_plan_approval" ? "Not started" : (verifying ? "Tests running…" : "3 passed, scope valid")}</small></div>
    <div class="timeline-item ${publishWait ? "pending" : ""}"><span>${publishWait ? "Ⅱ" : (completed ? "✓" : "·")}</span><strong>Publish approval</strong><small>${publishWait ? "Waiting for your decision" : (completed ? "Approved by reviewer" : "Not started")}</small></div>
    <div class="timeline-item"><span>${completed ? "✓" : "·"}</span><strong>Draft PR</strong><small>${completed ? "Created · #201" : "Not created"}</small></div>`;
}

function renderDetail() {
  const run = runs.find((item) => item.id === selectedRunId) || runs[0];
  const approvalText = run.status === "awaiting_plan_approval"
    ? "Review the proposed scope. Approval permits PatchPilot to modify one fixture file."
    : run.status === "awaiting_publish_approval"
      ? "All tests passed. Approval permits PatchPilot to create a draft PR; it still cannot merge."
      : "This run is read-only while the agent works or after it completes.";
  document.getElementById("runDetail").innerHTML = `
    <div class="detail-head">
      <div><span class="eyebrow">RUN ${run.id.toUpperCase()}</span><h2>#${run.issue} · ${run.title}</h2><p>${run.repo} · started ${run.time}</p></div>
      <div class="detail-actions">${detailAction(run)}</div>
    </div>
    ${(run.status.includes("approval")) ? `<div class="approval-callout"><span>Ⅱ</span><p><strong>Human decision required</strong>${approvalText}</p></div>` : ""}
    <div class="detail-body">
      <div class="evidence">
        <p class="section-label">AGENT FINDING</p><p class="agent-summary">${run.summary}</p>
        <p class="section-label">PROPOSED REPAIR PLAN</p>
        <ol class="plan-steps"><li data-step="1">Inspect the validator and its current regression tests.</li><li data-step="2">Require a non-empty local part and a dotted domain.</li><li data-step="3">Run the focused suite before and after the patch.</li></ol>
        <p class="section-label">EXPECTED CHANGE</p><div class="file-chip">app/validation.py <span>1 file · low risk</span></div>
      </div>
      <aside class="timeline"><p class="section-label">AUDIT TIMELINE</p>${timelineFor(run)}</aside>
    </div>`;
  document.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", () => handleAction(button.dataset.action, run)));
}

function handleAction(action, run) {
  if (action === "reject") {
    run.status = "completed";
    run.summary = "The run was stopped by a human reviewer. No additional side effects occurred.";
    showToast("Run safely stopped", "The rejection and reason were added to the audit trail.");
  } else if (action === "approve-plan") {
    run.status = "awaiting_publish_approval";
    run.summary = "The approved one-file patch now rejects incomplete domains. All 3 regression tests passed and policy review found no scope violations.";
    showToast("Plan approved", "Patch applied, tests passed, and the agent paused before publication.");
  } else if (action === "approve-publish") {
    run.status = "completed";
    run.summary = "Draft pull request #201 contains the verified one-file repair and a complete evidence summary. It has not been merged.";
    showToast("Draft PR created", "Publication approval was recorded. PatchPilot cannot merge or deploy.");
  } else if (action === "open-pr") {
    showToast("Demo draft PR", "A production adapter would open GitHub here.");
  }
  renderAll();
}

function showToast(title, message) {
  const toast = document.getElementById("toast");
  toast.querySelector("strong").textContent = title;
  toast.querySelector("small").textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 3600);
}

function renderAll() {
  renderRecentRuns();
  renderRunList();
  renderDetail();
  const waiting = runs.filter((run) => run.status.includes("approval")).length;
  document.getElementById("approvalCount").textContent = waiting;
}

const modal = document.getElementById("newRunModal");
function openModal() { modal.classList.add("open"); modal.setAttribute("aria-hidden", "false"); }
function closeModal() { modal.classList.remove("open"); modal.setAttribute("aria-hidden", "true"); }
document.getElementById("newRunTop").addEventListener("click", openModal);
document.getElementById("newRunPage").addEventListener("click", openModal);
document.getElementById("closeModal").addEventListener("click", closeModal);
modal.addEventListener("click", (event) => { if (event.target === modal) closeModal(); });
document.getElementById("newRunForm").addEventListener("submit", (event) => {
  event.preventDefault();
  selectedRunId = "run-142";
  closeModal();
  renderAll();
  showView("runs");
  showToast("Investigation complete", "The defect was reproduced and the repair plan is ready for approval.");
});
document.getElementById("mobileMenu").addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeModal(); });

renderAll();
const initial = location.hash.slice(1);
if (["overview", "runs", "evaluations", "policies", "docs"].includes(initial)) showView(initial);
