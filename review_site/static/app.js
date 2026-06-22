const state = {
  view: "review",
  selected: null,
  papers: [],
  rows: [],
};

const $ = (id) => document.getElementById(id);

function value(id) {
  return $(id).value.trim();
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function short(text, n = 120) {
  const s = String(text ?? "");
  return s.length > n ? `${s.slice(0, n - 1)}...` : s;
}

function dataValue(row, keys) {
  for (const key of keys) {
    if (row[key] !== undefined && row[key] !== null && row[key] !== "") return row[key];
    if (row.data && row.data[key] !== undefined && row.data[key] !== null && row.data[key] !== "") return row.data[key];
  }
  return "";
}

function renderStats(summary) {
  $("lastImport").textContent = summary.last_import ? `Last import: ${summary.last_import}` : "No import yet";
  const items = [
    ["Papers", summary.papers],
    ["Strength", summary.strength_results],
    ["Components", summary.mixture_components],
    ["Open Review", summary.review_open],
    ["Resolved", summary.review_resolved],
    ["Answers", summary.answers],
  ];
  $("stats").innerHTML = items.map(([label, val]) => `
    <div class="stat"><span>${label}</span><strong>${val ?? 0}</strong></div>
  `).join("");
}

async function loadSummary() {
  const summary = await api("/api/summary");
  renderStats(summary);
}

async function loadPapers() {
  state.papers = await api("/api/papers");
  $("paperFilter").innerHTML = '<option value="">全部文章</option>' + state.papers.map((p) => (
    `<option value="${escapeHtml(p.paper_id)}">${escapeHtml(p.paper_id)} (${p.open_reviews} open)</option>`
  )).join("");
}

function columnsForView(view) {
  if (view === "review") return ["id", "status", "paper_id", "target_sheet", "question", "suggested_action", "notes"];
  if (view === "papers") return ["paper_id", "doi", "year", "strength_count", "component_count", "open_reviews", "title"];
  if (view === "strength") return ["paper_id", "record_key", "mixture_id", "mixture_original_id", "age_days", "compressive_strength_mpa", "unit", "source_type", "evidence_ids", "human_decision"];
  if (view === "mixtures") return ["paper_id", "record_key", "mixture_id", "component_standard", "category", "amount", "unit", "basis", "replacement_pct", "human_decision"];
  if (view === "answers") return ["id", "participant", "decision", "paper_id", "review_key", "answer", "corrected_value", "comment", "created_at"];
  return [];
}

function renderTable(rows) {
  const cols = columnsForView(state.view);
  if (!rows.length) {
    $("tableWrap").innerHTML = '<div class="notice">没有匹配的记录</div>';
    return;
  }
  $("tableWrap").innerHTML = `
    <table>
      <thead><tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
      <tbody>
        ${rows.map((row, index) => `
          <tr data-index="${index}">
            ${cols.map((col) => {
              const raw = dataValue(row, [col]);
              const cell = col === "status"
                ? `<span class="badge ${escapeHtml(raw)}">${escapeHtml(raw)}</span>`
                : escapeHtml(short(raw));
              return `<td title="${escapeHtml(raw)}">${cell}</td>`;
            }).join("")}
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
  document.querySelectorAll("tbody tr").forEach((tr) => {
    tr.addEventListener("click", () => selectRow(Number(tr.dataset.index), tr));
  });
}

function renderDetail(item) {
  if (!item) {
    $("selectedItem").className = "selected empty";
    $("selectedItem").textContent = "选择一条 review item";
    $("submitAnswer").disabled = true;
    return;
  }
  $("selectedItem").className = "selected";
  const rows = [
    ["id", item.id],
    ["paper_id", item.paper_id],
    ["status", item.status],
    ["target_sheet", item.target_sheet],
    ["target_records", item.target_record_ids],
    ["question", item.question],
    ["suggested_action", item.suggested_action],
    ["notes", item.notes],
  ];
  const dataRows = Object.entries(item.data || {}).filter(([key]) => !rows.some(([k]) => k === key));
  $("selectedItem").innerHTML = `
    <dl class="kv">
      ${rows.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v || "")}</dd>`).join("")}
      ${dataRows.slice(0, 24).map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join("")}
    </dl>
  `;
  $("manualPaperId").value = item.paper_id || "";
  $("manualTarget").value = [item.target_sheet, item.target_record_ids].filter(Boolean).join(":");
  $("submitAnswer").disabled = state.view !== "review";
}

function selectRow(index, tr) {
  document.querySelectorAll("tbody tr").forEach((row) => row.classList.remove("selectedRow"));
  tr?.classList.add("selectedRow");
  state.selected = state.rows[index];
  renderDetail(state.selected);
}

async function loadView() {
  const paper = encodeURIComponent(value("paperFilter"));
  const q = encodeURIComponent(value("searchBox"));
  const status = encodeURIComponent(value("statusFilter"));
  let title = "Review Queue";
  let exportTable = "review_queue";
  if (state.view === "review") {
    state.rows = await api(`/api/review?status=${status}&paper_id=${paper}&q=${q}`);
  } else if (state.view === "papers") {
    title = "Papers";
    exportTable = "papers";
    state.rows = state.papers;
  } else if (state.view === "strength") {
    title = "Strength Results";
    exportTable = "records";
    state.rows = await api(`/api/records?sheet=strength_results&paper_id=${paper}`);
  } else if (state.view === "mixtures") {
    title = "Mixture Components";
    exportTable = "records";
    state.rows = await api(`/api/records?sheet=mixture_components&paper_id=${paper}`);
  } else if (state.view === "answers") {
    title = "Answers";
    exportTable = "answers";
    state.rows = await api("/api/answers");
  }
  $("viewTitle").textContent = title;
  $("exportLink").href = `/api/export/${exportTable}`;
  state.selected = null;
  renderDetail(null);
  renderTable(state.rows);
}

async function submitAnswer(event) {
  event.preventDefault();
  if (!state.selected || state.view !== "review") return;
  const participant = value("participant");
  if (!participant) {
    alert("请先填写参与者姓名");
    return;
  }
  await api("/api/answer", {
    method: "POST",
    body: JSON.stringify({
      review_item_id: state.selected.id,
      participant,
      decision: value("decision"),
      answer: value("answerText"),
      corrected_value: value("correctedValue"),
      comment: value("comment"),
    }),
  });
  $("answerText").value = "";
  $("correctedValue").value = "";
  $("comment").value = "";
  await refreshAll();
}

async function createManualReview() {
  const paperId = value("manualPaperId");
  const question = value("manualQuestion");
  if (!paperId || !question) {
    alert("paper_id 和问题都需要填写");
    return;
  }
  await api("/api/review", {
    method: "POST",
    body: JSON.stringify({
      paper_id: paperId,
      question,
      target_record_ids: value("manualTarget"),
      priority: "normal",
    }),
  });
  $("manualQuestion").value = "";
  await refreshAll();
}

async function reimport() {
  $("reimportBtn").disabled = true;
  $("reimportBtn").textContent = "导入中...";
  try {
    await api("/api/import", { method: "POST", body: "{}" });
    await refreshAll();
  } finally {
    $("reimportBtn").disabled = false;
    $("reimportBtn").textContent = "重新导入 Excel";
  }
}

async function refreshAll() {
  await loadSummary();
  await loadPapers();
  await loadView();
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", async () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.view = btn.dataset.view;
      await loadView();
    });
  });
  $("statusFilter").addEventListener("change", loadView);
  $("paperFilter").addEventListener("change", loadView);
  $("searchBox").addEventListener("input", () => {
    clearTimeout(window.searchTimer);
    window.searchTimer = setTimeout(loadView, 220);
  });
  $("answerForm").addEventListener("submit", submitAnswer);
  $("createReview").addEventListener("click", createManualReview);
  $("reimportBtn").addEventListener("click", reimport);
}

bindEvents();
refreshAll().catch((error) => {
  $("tableWrap").innerHTML = `<div class="notice">加载失败：${escapeHtml(error.message)}</div>`;
});
