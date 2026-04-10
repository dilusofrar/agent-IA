const form = document.getElementById("upload-form");
const fileInput = document.getElementById("pdf-file");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const employeeNameEl = document.getElementById("employee-name");
const periodTextEl = document.getElementById("period-text");
const summaryGridEl = document.getElementById("summary-grid");
const issuesListEl = document.getElementById("issues-list");
const daysTableEl = document.getElementById("days-table");
const inconsistencyCountEl = document.getElementById("inconsistency-count");
const exportLinkEl = document.getElementById("export-link");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!fileInput.files.length) {
    setStatus("Selecione um PDF para continuar.", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  setStatus("Processando PDF e calculando a apuração...", "loading");

  try {
    const response = await fetch("/api/process", { method: "POST", body: formData });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Falha ao processar arquivo.");
    renderPayload(payload);
    setStatus("Apuração concluída com sucesso.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

function setStatus(message, mode) {
  statusEl.textContent = message;
  statusEl.className = `status ${mode}`;
}

function renderPayload(payload) {
  resultsEl.classList.remove("hidden");
  employeeNameEl.textContent = payload.employeeName || "Colaborador não identificado";
  periodTextEl.textContent = `Período: ${formatDate(payload.periodStart)} até ${formatDate(payload.periodEnd)} · Processado em ${payload.processedAt.replace("T", " ")}`;
  exportLinkEl.href = `/api/export/${payload.reportId}`;

  const cards = [
    ["Dias processados", payload.summary.businessDaysProcessed],
    ["Dias ignorados", payload.summary.ignoredDays],
    ["Inconsistências", payload.summary.inconsistencyCount],
    ["Horas trabalhadas", payload.summary.worked],
    ["Horas previstas", payload.summary.expected],
    ["Saldo", payload.summary.balance],
    ["Banco positivo", payload.summary.positiveBank],
    ["Banco negativo", payload.summary.negativeBank],
    ["Compensadas", payload.summary.compensated],
    ["Extra antes", payload.summary.overtimeBeforeLunch],
    ["Extra depois", payload.summary.overtimeAfterLunch],
  ];

  summaryGridEl.innerHTML = cards.map(([label, value]) => `
    <article class="metric"><span>${label}</span><strong>${value}</strong></article>
  `).join("");

  const issueDays = payload.days.filter((day) => day.issues.length);
  inconsistencyCountEl.textContent = String(issueDays.length);
  issuesListEl.innerHTML = issueDays.length
    ? issueDays.map((day) => `
        <div class="issue-item">
          <strong>${formatDate(day.date)} · ${day.statusLabel}</strong>
          <div>${day.issues.join("<br/>")}</div>
        </div>
      `).join("")
    : `<div class="issue-item"><strong>Nenhuma inconsistência crítica</strong><div>Os dias úteis com batidas completas foram processados sem alertas.</div></div>`;

  daysTableEl.innerHTML = payload.days.map((day) => {
    const rowClass = day.issues.length ? "issue" : day.ignored ? "ignored" : "";
    const badgeClass = day.issues.length ? "warn" : day.ignored ? "off" : "ok";
    const alerts = day.issues.length
      ? day.issues.join("<br/>")
      : day.ignored
        ? (day.ignoredReason || day.holidayName || "Dia fora da apuração")
        : "Sem alertas";
    return `
      <tr class="${rowClass}">
        <td>${formatDate(day.date)}<br/><small>${day.weekday}</small></td>
        <td><span class="badge ${badgeClass}">${day.statusLabel}</span></td>
        <td>${day.firstEntry || "-"}</td>
        <td>${day.lastExit || "-"}</td>
        <td>${day.worked}</td>
        <td>${day.balance}</td>
        <td>${day.overtimeBeforeLunch}</td>
        <td>${day.overtimeAfterLunch}</td>
        <td>${alerts}</td>
      </tr>
    `;
  }).join("");
}

function formatDate(isoDate) {
  const [year, month, day] = isoDate.split("-");
  return `${day}/${month}/${year}`;
}
