(function () {
  "use strict";

  const form = document.getElementById("upload-form");
  const fileInput = document.getElementById("pdf-file");
  const dropzone = document.getElementById("dropzone");
  const dzTitle = document.getElementById("dropzone-title");
  const dzHint = document.getElementById("dropzone-hint");
  const submitBtn = document.getElementById("submit-btn");

  const statusEl = document.getElementById("status");
  const resultsEl = document.getElementById("results");
  const employeeEl = document.getElementById("employee-name");
  const periodEl = document.getElementById("period-text");
  const summaryGrid = document.getElementById("summary-grid");
  const issuesList = document.getElementById("issues-list");
  const issuesCount = document.getElementById("inconsistency-count");
  const daysTable = document.getElementById("days-table");
  const exportLink = document.getElementById("export-link");
  const healthPill = document.getElementById("health-pill");
  const yearEl = document.getElementById("year");

  if (yearEl) {
    yearEl.textContent = String(new Date().getFullYear());
  }

  fetch("/healthz", { method: "GET" })
    .then((response) => {
      if (!response.ok) {
        throw new Error("offline");
      }
      setHealth(true);
    })
    .catch(() => setHealth(false));

  function setHealth(online) {
    if (!healthPill) return;
    healthPill.classList.toggle("pill-success", online);
    healthPill.innerHTML = online
      ? '<span class="dot"></span> Sistema operacional'
      : '<span class="dot" style="background:#dc2626;box-shadow:0 0 0 3px rgba(220,38,38,.18)"></span> Indisponível';
  }

  function setStatus(kind, message) {
    statusEl.hidden = false;
    statusEl.classList.remove("is-loading", "is-success", "is-error");
    if (kind) {
      statusEl.classList.add("is-" + kind);
    }
    statusEl.innerHTML =
      kind === "loading"
        ? '<span class="spinner" aria-hidden="true"></span><span>' + escapeHtml(message) + "</span>"
        : "<span>" + escapeHtml(message) + "</span>";
  }

  function clearStatus() {
    statusEl.hidden = true;
    statusEl.className = "status";
    statusEl.innerHTML = "";
  }

  if (dropzone && fileInput) {
    ["dragenter", "dragover"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        event.stopPropagation();
        dropzone.classList.add("is-drag");
      });
    });

    ["dragleave", "drop"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        event.stopPropagation();
        dropzone.classList.remove("is-drag");
      });
    });

    dropzone.addEventListener("drop", (event) => {
      const files = event.dataTransfer && event.dataTransfer.files;
      if (files && files[0]) {
        if (!looksLikePdf(files[0])) {
          setStatus("error", "Formato inválido. Envie um arquivo PDF.");
          return;
        }
        fileInput.files = files;
        updateDropzoneFromFile(files[0]);
      }
    });

    fileInput.addEventListener("change", () => {
      const file = fileInput.files && fileInput.files[0];
      if (file) {
        updateDropzoneFromFile(file);
      }
    });
  }

  function looksLikePdf(file) {
    if (!file) return false;
    return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  }

  function updateDropzoneFromFile(file) {
    const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
    dropzone.classList.add("has-file");
    dzTitle.textContent = file.name;
    dzHint.textContent = "PDF selecionado · " + sizeMB + " MB";
  }

  const summaryConfig = [
    ["Dias processados", "businessDaysProcessed", ""],
    ["Dias ignorados", "ignoredDays", ""],
    ["Inconsistências", "inconsistencyCount", "warn"],
    ["Horas trabalhadas", "worked", "ok"],
    ["Horas previstas", "expected", ""],
    ["Saldo", "balance", ""],
    ["Banco positivo", "positiveBank", "ok"],
    ["Banco negativo", "negativeBank", "danger"],
    ["Compensadas", "compensated", ""],
    ["Extras pagas", "paidOvertime", "warn"],
    ["Extra antes", "overtimeBeforeLunch", ""],
    ["Extra depois", "overtimeAfterLunch", ""],
    ["Atrasos", "late", "warn"],
    ["Saída antecipada", "earlyLeave", "danger"],
  ];

  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();

      const file = fileInput.files && fileInput.files[0];
      if (!file) {
        setStatus("error", "Selecione um arquivo PDF antes de processar.");
        return;
      }

      if (!looksLikePdf(file)) {
        setStatus("error", "Formato inválido. Envie um arquivo PDF.");
        return;
      }

      const formData = new FormData();
      formData.append("file", file);

      submitBtn.disabled = true;
      submitBtn.querySelector(".btn-label").textContent = "Processando…";
      setStatus("loading", "Enviando e processando o cartão de ponto…");

      try {
        const response = await fetch("/api/process", { method: "POST", body: formData });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Erro ao processar o arquivo.");
        }
        renderResults(payload);
        setStatus("success", "Apuração concluída com sucesso.");
      } catch (error) {
        console.error(error);
        resultsEl.hidden = true;
        setStatus("error", error && error.message ? error.message : "Falha ao processar o cartão.");
      } finally {
        submitBtn.disabled = false;
        submitBtn.querySelector(".btn-label").textContent = "Processar cartão";
      }
    });
  }

  function renderResults(payload) {
    employeeEl.textContent = payload.employeeName || "Colaborador não identificado";
    periodEl.textContent =
      "Período: " +
      formatDate(payload.periodStart) +
      " até " +
      formatDate(payload.periodEnd) +
      " · Processado em " +
      String(payload.processedAt || "").replace("T", " ");

    summaryGrid.innerHTML = "";
    summaryConfig.forEach(([label, key, tone]) => {
      summaryGrid.appendChild(
        renderMetric({
          label: label,
          value: payload.summary && key in payload.summary ? payload.summary[key] : "—",
          tone: tone,
        }),
      );
    });

    const issueDays = (payload.days || []).filter((day) => Array.isArray(day.issues) && day.issues.length);
    issuesList.innerHTML = "";
    issuesCount.textContent = String(issueDays.length);
    issuesCount.className = "badge " + (issueDays.length ? "badge-warning" : "badge-success");

    if (!issueDays.length) {
      issuesList.innerHTML =
        '<div class="issue"><span class="issue-icon">✓</span><div class="issue-body"><span class="issue-title">Nenhuma inconsistência crítica</span><span class="issue-desc">Os dias úteis com batidas completas foram processados sem alertas.</span></div></div>';
    } else {
      issueDays.forEach((day) => {
        issuesList.appendChild(renderIssue(day));
      });
    }

    daysTable.innerHTML = "";
    if (!(payload.days || []).length) {
      const emptyRow = document.createElement("tr");
      emptyRow.className = "empty-row";
      emptyRow.innerHTML = '<td colspan="14">Nenhum registro diário disponível.</td>';
      daysTable.appendChild(emptyRow);
    } else {
      payload.days.forEach((day) => {
        daysTable.appendChild(renderDay(day));
      });
    }

    exportLink.href = "/api/export/" + encodeURIComponent(payload.reportId);
    exportLink.hidden = !payload.reportId;

    resultsEl.hidden = false;
    resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderMetric(metric) {
    const wrap = document.createElement("div");
    wrap.className = "metric";
    wrap.innerHTML =
      '<div class="metric-head">' +
      '<span class="metric-label">' + escapeHtml(metric.label) + "</span>" +
      '<span class="metric-icon ' + escapeHtml(metric.tone || "") + '">' + pickIcon(metric.label) + "</span>" +
      "</div>" +
      '<div class="metric-value">' + escapeHtml(String(metric.value)) + "</div>";
    return wrap;
  }

  function renderIssue(day) {
    const item = document.createElement("div");
    item.className = "issue";
    item.innerHTML =
      '<span class="issue-icon">!</span>' +
      '<div class="issue-body">' +
      '<span class="issue-title">' +
      escapeHtml(formatDate(day.date) + " · " + (day.statusLabel || "Inconsistência")) +
      "</span>" +
      '<span class="issue-desc">' + escapeHtml(day.issues.join(" · ")) + "</span>" +
      "</div>";
    return item;
  }

  function renderDay(day) {
    const row = document.createElement("tr");
    if (day.issues && day.issues.length) {
      row.classList.add("row-issue");
    }
    if (day.ignored) {
      row.classList.add("row-ignored");
    }

    const alerts = buildAlerts(day);
    row.innerHTML =
      "<td><span class=\"day-date\">" + escapeHtml(formatDate(day.date)) + "</span><span class=\"day-weekday\">" + escapeHtml(day.weekday || "") + "</span></td>" +
      "<td>" + escapeHtml(day.journeyCode || "-") + "</td>" +
      "<td>" + escapeHtml(day.appliedSchedule || "-") + "</td>" +
      "<td>" + renderStatusBadge(day) + "</td>" +
      "<td>" + escapeHtml(day.firstEntry || "-") + "</td>" +
      "<td>" + escapeHtml(day.lastExit || "-") + "</td>" +
      "<td>" + escapeHtml(day.worked || "-") + "</td>" +
      "<td>" + escapeHtml(day.balance || "-") + "</td>" +
      "<td>" + escapeHtml(day.overtimeBeforeLunch || "-") + "</td>" +
      "<td>" + escapeHtml(day.overtimeAfterLunch || "-") + "</td>" +
      "<td>" + escapeHtml(day.paidOvertime || "-") + "</td>" +
      "<td>" + escapeHtml(day.late || "-") + "</td>" +
      "<td>" + escapeHtml(day.earlyLeave || "-") + "</td>" +
      "<td>" + renderAlertsList(alerts) + "</td>";
    return row;
  }

  function renderStatusBadge(day) {
    let badgeClass = "badge-success";
    if (day.issues && day.issues.length) {
      badgeClass = "badge-warning";
    } else if (day.ignored) {
      badgeClass = "badge-muted";
    }
    return '<span class="badge ' + badgeClass + '">' + escapeHtml(day.statusLabel || "—") + "</span>";
  }

  function buildAlerts(day) {
    const alerts = [];
    if (day.issues && day.issues.length) {
      alerts.push.apply(alerts, day.issues);
    }
    if (day.ignored) {
      alerts.push(day.ignoredReason || day.holidayName || "Dia fora da apuração");
    }
    if (!day.ignored && day.late && day.late !== "00:00") {
      alerts.push("Atraso de " + day.late);
    }
    if (!day.ignored && day.earlyLeave && day.earlyLeave !== "00:00") {
      alerts.push("Saída antecipada de " + day.earlyLeave);
    }
    if (!day.ignored && day.paidOvertime && day.paidOvertime !== "00:00") {
      alerts.push("Hora extra paga de " + day.paidOvertime);
    }
    alerts.push("JRND " + (day.journeyCode || "-"));
    alerts.push("Jornada aplicada " + (day.appliedSchedule || "-"));
    return alerts;
  }

  function renderAlertsList(alerts) {
    return (
      '<ul class="alerts-list">' +
      alerts.map((alert) => "<li>" + escapeHtml(alert) + "</li>").join("") +
      "</ul>"
    );
  }

  function formatDate(isoDate) {
    if (!isoDate || !isoDate.includes("-")) {
      return isoDate || "—";
    }
    const parts = isoDate.split("-");
    return parts[2] + "/" + parts[1] + "/" + parts[0];
  }

  function pickIcon(label) {
    const text = String(label || "").toLowerCase();
    if (/hora|trabalh|jornada/.test(text)) return svg('<circle cx="12" cy="12" r="9"></circle><polyline points="12 7 12 12 15 14"></polyline>');
    if (/extra/.test(text)) return svg('<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>');
    if (/falta|inconsist|ausente|atras/.test(text)) return svg('<circle cx="12" cy="12" r="9"></circle><line x1="9" y1="9" x2="15" y2="15"></line><line x1="15" y1="9" x2="9" y2="15"></line>');
    if (/dia|presen/.test(text)) return svg('<rect x="3" y="4" width="18" height="16" rx="3"></rect><path d="M3 10h18"></path>');
    if (/saldo|total|banco/.test(text)) return svg('<path d="M3 12h18"></path><path d="M3 6h18"></path><path d="M3 18h18"></path>');
    return svg('<circle cx="12" cy="12" r="9"></circle>');
  }

  function svg(inner) {
    return '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + inner + "</svg>";
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
})();
