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
const inlineStatusEl = document.getElementById("status-inline");
const dropzoneEl = document.querySelector(".dropzone");
const dropzoneTitleEl = dropzoneEl.querySelector("strong");
const dropzoneTextEl = dropzoneEl.querySelector("span");

fileInput.addEventListener("change", () => {
  syncSelectedFileState();
});

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
  if (mode === "success") {
    statusEl.classList.add("hidden");
    inlineStatusEl.textContent = message;
    inlineStatusEl.className = `status status-inline ${mode}`;
  } else {
    statusEl.classList.remove("hidden");
    inlineStatusEl.textContent = "";
    inlineStatusEl.className = "status-inline hidden";
  }
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
    ["Extras pagas", payload.summary.paidOvertime],
    ["Extra antes", payload.summary.overtimeBeforeLunch],
    ["Extra depois", payload.summary.overtimeAfterLunch],
    ["Atrasos", payload.summary.late],
    ["Saída antecipada", payload.summary.earlyLeave],
  ];

  summaryGridEl.replaceChildren(...cards.map(([label, value]) => {
    const card = document.createElement("article");
    card.className = "metric";

    const labelEl = document.createElement("span");
    labelEl.className = "metric-label";
    labelEl.textContent = label;

    const valueEl = document.createElement("strong");
    valueEl.className = "metric-value";
    valueEl.textContent = String(value);

    card.append(labelEl, valueEl);
    return card;
  }));

  const issueDays = payload.days.filter((day) => day.issues.length);
  inconsistencyCountEl.textContent = String(issueDays.length);
  issuesListEl.replaceChildren(...(issueDays.length
    ? issueDays.map((day) => buildIssueItem(
      `${formatDate(day.date)} · ${day.statusLabel}`,
      day.issues,
    ))
    : [buildIssueItem(
      "Nenhuma inconsistência crítica",
      ["Os dias úteis com batidas completas foram processados sem alertas."],
    )]));

  daysTableEl.replaceChildren(...payload.days.map((day) => {
    const rowClass = day.issues.length ? "issue" : day.ignored ? "ignored" : "";
    const badgeClass = day.issues.length ? "warn" : day.ignored ? "off" : "ok";
    const notes = [];
    if (day.issues.length) {
      notes.push(...day.issues);
    }
    if (day.ignored) {
      notes.push(day.ignoredReason || day.holidayName || "Dia fora da apuração");
    }
    if (!day.ignored && day.late !== "00:00") {
      notes.push(`Atraso de ${day.late}`);
    }
    if (!day.ignored && day.earlyLeave !== "00:00") {
      notes.push(`Saída antecipada de ${day.earlyLeave}`);
    }
    if (!day.ignored && day.paidOvertime !== "00:00") {
      notes.push(`Hora extra paga de ${day.paidOvertime}`);
    }
    notes.push(`JRND ${day.journeyCode || "-"}`);
    notes.push(`Jornada aplicada ${day.appliedSchedule}`);
    return buildDayRow(day, rowClass, badgeClass, notes.length ? notes : ["Sem alertas"]);
  }));
}

function formatDate(isoDate) {
  const [year, month, day] = isoDate.split("-");
  return `${day}/${month}/${year}`;
}

function buildIssueItem(title, lines) {
  const container = document.createElement("div");
  container.className = "issue-item";
  if (title === "Nenhuma inconsistência crítica") {
    container.classList.add("safe");
  }

  const titleEl = document.createElement("strong");
  titleEl.textContent = title;

  const detailsEl = createMultilineBlock(lines);
  container.append(titleEl, detailsEl);
  return container;
}

function buildDayRow(day, rowClass, badgeClass, notes) {
  const row = document.createElement("tr");
  if (rowClass) row.className = rowClass;

  const dateCell = document.createElement("td");
  const dateMain = document.createElement("span");
  dateMain.className = "day-date";
  dateMain.textContent = formatDate(day.date);

  dateCell.append(
    dateMain,
    createSmallText(day.weekday),
  );

  const statusBadge = document.createElement("span");
  statusBadge.className = `badge ${badgeClass}`;
  statusBadge.textContent = day.statusLabel;

  const statusCell = document.createElement("td");
  statusCell.append(statusBadge);

  const alertsCell = document.createElement("td");
  alertsCell.className = "alerts-cell";
  alertsCell.append(createMultilineBlock(notes));

  row.append(
    dateCell,
    createCell(day.journeyCode || "-"),
    createCell(day.appliedSchedule),
    statusCell,
    createCell(day.firstEntry || "-"),
    createCell(day.lastExit || "-"),
    createCell(day.worked),
    createCell(day.balance),
    createCell(day.overtimeBeforeLunch),
    createCell(day.overtimeAfterLunch),
    createCell(day.paidOvertime),
    createCell(day.late),
    createCell(day.earlyLeave),
    alertsCell,
  );
  return row;
}

function createCell(value) {
  const cell = document.createElement("td");
  cell.textContent = String(value);
  return cell;
}

function createSmallText(value) {
  const small = document.createElement("small");
  small.className = "day-weekday";
  small.textContent = value;
  return small;
}

function createMultilineBlock(lines) {
  const container = document.createElement("ul");
  container.className = "note-list compact";
  lines.forEach((line, index) => {
    const item = document.createElement("li");
    item.textContent = line;
    item.dataset.index = String(index);
    container.append(item);
  });
  return container;
}

function syncSelectedFileState() {
  const selectedFile = fileInput.files?.[0];
  if (!selectedFile) {
    dropzoneEl.classList.remove("has-file");
    dropzoneTitleEl.textContent = "Solte o PDF aqui";
    dropzoneTextEl.textContent = "ou clique para selecionar o arquivo";
    return;
  }

  dropzoneEl.classList.add("has-file");
  dropzoneTitleEl.textContent = selectedFile.name;
  dropzoneTextEl.textContent = `${(selectedFile.size / 1024).toFixed(1)} KB · clique para trocar o arquivo`;
}
