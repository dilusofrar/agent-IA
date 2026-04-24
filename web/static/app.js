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
  const insightsGrid = document.getElementById("insights-grid");
  const issuesList = document.getElementById("issues-list");
  const issuesCount = document.getElementById("inconsistency-count");
  const daysTable = document.getElementById("days-table");
  const exportLink = document.getElementById("export-link");
  const healthPill = document.getElementById("health-pill");
  const yearEl = document.getElementById("year");
  const recentList = document.getElementById("recent-list");
  const recentCount = document.getElementById("recent-count");
  const filterGroup = document.getElementById("day-filter-group");
  const searchInput = document.getElementById("day-search");
  const tableStats = document.getElementById("table-stats");
  const ruleSchedule = document.getElementById("rule-schedule");
  const rulePaidHours = document.getElementById("rule-paid-hours");

  const state = {
    payload: null,
    filter: "all",
    query: "",
    settings: null,
  };

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

  const filterPredicates = {
    all: function () {
      return true;
    },
    issues: function (day) {
      return Array.isArray(day.issues) && day.issues.length > 0;
    },
    ignored: function (day) {
      return Boolean(day.ignored);
    },
    overtime: function (day) {
      return day.paidOvertime && day.paidOvertime !== "00:00";
    },
    late: function (day) {
      return (day.late && day.late !== "00:00") || (day.earlyLeave && day.earlyLeave !== "00:00");
    },
  };

  if (yearEl) {
    yearEl.textContent = String(new Date().getFullYear());
  }

  checkHealth();
  fetchSettings();
  fetchRecentReports();

  if (dropzone && fileInput) {
    ["dragenter", "dragover"].forEach(function (eventName) {
      dropzone.addEventListener(eventName, function (event) {
        event.preventDefault();
        event.stopPropagation();
        dropzone.classList.add("is-drag");
      });
    });

    ["dragleave", "drop"].forEach(function (eventName) {
      dropzone.addEventListener(eventName, function (event) {
        event.preventDefault();
        event.stopPropagation();
        dropzone.classList.remove("is-drag");
      });
    });

    dropzone.addEventListener("drop", function (event) {
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

    fileInput.addEventListener("change", function () {
      const file = fileInput.files && fileInput.files[0];
      if (file) {
        updateDropzoneFromFile(file);
      }
    });
  }

  if (filterGroup) {
    filterGroup.addEventListener("click", function (event) {
      const button = event.target.closest("[data-filter]");
      if (!button) {
        return;
      }
      state.filter = button.getAttribute("data-filter") || "all";
      syncFilterButtons();
      renderDaysSection();
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      state.query = String(searchInput.value || "").trim().toLowerCase();
      renderDaysSection();
    });
  }

  if (form) {
    form.addEventListener("submit", async function (event) {
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

      setSubmitState(true);
      setStatus("loading", "Enviando e processando o cartão de ponto…");

      try {
        const response = await fetch("/api/process", { method: "POST", body: formData });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Erro ao processar o arquivo.");
        }
        renderResults(payload);
        setStatus("success", "Apuração concluída com sucesso.");
        fetchRecentReports();
      } catch (error) {
        console.error(error);
        resultsEl.hidden = true;
        setStatus("error", error && error.message ? error.message : "Falha ao processar o cartão.");
      } finally {
        setSubmitState(false);
      }
    });
  }

  function checkHealth() {
    fetch("/healthz", { method: "GET" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("offline");
        }
        return response.json();
      })
      .then(function (payload) {
        setHealth(true, payload && payload.version ? "Sistema operacional · v" + payload.version : "Sistema operacional");
      })
      .catch(function () {
        setHealth(false, "Indisponível");
      });
  }

  async function fetchRecentReports() {
    if (!recentList || !recentCount) {
      return;
    }

    try {
      const response = await fetch("/api/reports/recent", { method: "GET" });
      if (!response.ok) {
        throw new Error("Falha ao carregar histórico");
      }
      const payload = await response.json();
      renderRecentReports(payload.items || []);
    } catch (error) {
      recentCount.textContent = "0";
      recentCount.className = "badge badge-muted";
      recentList.replaceChildren(createEmptyState("Ainda não há apurações recentes nesta sessão.", "recent-empty"));
    }
  }

  async function fetchSettings() {
    try {
      const response = await fetch("/api/settings/public", { method: "GET" });
      if (!response.ok) {
        throw new Error("Falha ao carregar regras");
      }
      const payload = await response.json();
      state.settings = payload;
      renderSettingsSummary(payload);
    } catch (error) {
      console.error(error);
    }
  }

  function setHealth(online, label) {
    if (!healthPill) return;
    healthPill.replaceChildren();
    healthPill.classList.toggle("pill-success", online);
    const dot = createElement("span", { className: "dot" });
    if (!online) {
      dot.style.background = "#dc2626";
      dot.style.boxShadow = "0 0 0 3px rgba(220,38,38,.18)";
    }
    healthPill.append(dot, document.createTextNode(label));
  }

  function setSubmitState(isBusy) {
    if (!submitBtn) return;
    submitBtn.disabled = isBusy;
    const label = submitBtn.querySelector(".btn-label");
    if (label) {
      label.textContent = isBusy ? "Processando…" : "Processar cartão";
    }
  }

  function setStatus(kind, message) {
    if (!statusEl) return;
    statusEl.hidden = false;
    statusEl.className = "status";
    if (kind) {
      statusEl.classList.add("is-" + kind);
    }

    const content = [];
    if (kind === "loading") {
      content.push(createElement("span", { className: "spinner", attrs: { "aria-hidden": "true" } }));
    }
    content.push(createElement("span", { text: message }));
    statusEl.replaceChildren.apply(statusEl, content);
  }

  function looksLikePdf(file) {
    if (!file) return false;
    return file.type === "application/pdf" || String(file.name || "").toLowerCase().endsWith(".pdf");
  }

  function updateDropzoneFromFile(file) {
    const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
    dropzone.classList.add("has-file");
    dzTitle.textContent = file.name;
    dzHint.textContent = "PDF selecionado · " + sizeMB + " MB";
  }

  function renderResults(payload) {
    renderPayload(payload, true);
  }

  function renderPayload(payload, shouldScroll) {
    if (payload.settings) {
      state.settings = payload.settings;
      renderSettingsSummary(payload.settings);
    }
    state.payload = payload;
    state.filter = "all";
    state.query = "";
    if (searchInput) {
      searchInput.value = "";
    }
    syncFilterButtons();

    employeeEl.textContent = payload.employeeName || "Colaborador não identificado";
    periodEl.textContent =
      "Período: " +
      formatDate(payload.periodStart) +
      " até " +
      formatDate(payload.periodEnd) +
      " · Processado em " +
      formatDateTime(payload.processedAt);

    renderSummary(payload.summary || {});
    renderInsights(payload);
    renderIssues(payload.days || []);
    renderDaysSection();
    renderExportLink(payload.reportId);

    resultsEl.hidden = false;
    if (shouldScroll) {
      resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function renderSummary(summary) {
    const cards = summaryConfig.map(function (config) {
      const label = config[0];
      const key = config[1];
      const tone = config[2];
      return renderMetric({
        label: label,
        value: Object.prototype.hasOwnProperty.call(summary, key) ? summary[key] : "—",
        tone: tone,
      });
    });
    summaryGrid.replaceChildren.apply(summaryGrid, cards);
  }

  function renderInsights(payload) {
    if (!insightsGrid) return;

    const diagnostics = payload.diagnostics || {};
    const meta = payload.meta || {};
    const cards = [
      {
        label: "Tempo de processamento",
        value: formatDuration(meta.processingDurationMs),
        note: "Do upload ao relatório pronto",
      },
      {
        label: "Dias com inconsistência",
        value: String(diagnostics.daysWithIssues || 0),
        note: "Pontos que merecem conferência manual",
      },
      {
        label: "Dias com extra paga",
        value: String(diagnostics.paidOvertimeDays || 0),
        note: "Dias fora do saldo normal de jornada",
      },
      {
        label: "Atrasos ou saídas antecipadas",
        value: String((diagnostics.lateDays || 0) + (diagnostics.earlyLeaveDays || 0)),
        note: "Ocorrências com impacto no banco",
      },
      {
        label: "Batidas incompletas",
        value: String(diagnostics.missingPunchDays || 0),
        note: "Dias em que não foi possível fechar intervalos",
      },
      {
        label: "Ignorados no período",
        value: String(diagnostics.ignoredDays || 0),
        note: summarizeIgnoredBreakdown(diagnostics.ignoredBreakdown || []),
      },
    ].map(renderInsightCard);

    insightsGrid.replaceChildren.apply(insightsGrid, cards);
  }

  function renderIssues(days) {
    const issueDays = days.filter(function (day) {
      return Array.isArray(day.issues) && day.issues.length;
    });

    issuesCount.textContent = String(issueDays.length);
    issuesCount.className = "badge " + (issueDays.length ? "badge-warning" : "badge-success");

    if (!issueDays.length) {
      issuesList.replaceChildren(
        createIssueItem(
          "Nenhuma inconsistência crítica",
          "Os dias úteis com batidas completas foram processados sem alertas.",
          true,
        ),
      );
      return;
    }

    issuesList.replaceChildren.apply(
      issuesList,
      issueDays.map(function (day) {
        return createIssueItem(
          formatDate(day.date) + " · " + (day.statusLabel || "Inconsistência"),
          day.issues.join(" · "),
          false,
        );
      }),
    );
  }

  function renderDaysSection() {
    if (!state.payload) {
      return;
    }

    const days = filterDays(state.payload.days || [], state.filter, state.query);
    renderTableStats(days, state.payload.days || []);

    if (!days.length) {
      const emptyRow = createElement("tr", { className: "empty-row" });
      const cell = createElement("td", {
        attrs: { colspan: "14" },
      });
      cell.appendChild(createEmptyState("Nenhum dia corresponde ao filtro atual.", "table-empty"));
      emptyRow.appendChild(cell);
      daysTable.replaceChildren(emptyRow);
      return;
    }

    daysTable.replaceChildren.apply(
      daysTable,
      days.map(renderDay),
    );
  }

  function renderTableStats(filteredDays, allDays) {
    if (!tableStats) return;
    const cards = [
      createStatPill("Mostrando", String(filteredDays.length) + " de " + String(allDays.length) + " dias"),
      createStatPill("Filtro", filterLabel(state.filter)),
      createStatPill("Busca", state.query ? "“" + state.query + "”" : "Sem busca"),
    ];
    tableStats.replaceChildren.apply(tableStats, cards);
  }

  function renderRecentReports(items) {
    if (!recentList || !recentCount) return;

    recentCount.textContent = String(items.length);
    recentCount.className = "badge " + (items.length ? "badge-success" : "badge-muted");

    if (!items.length) {
      recentList.replaceChildren(createEmptyState("Ainda não há apurações recentes nesta sessão.", "recent-empty"));
      return;
    }

    recentList.replaceChildren.apply(
      recentList,
      items.map(renderRecentItem),
    );
  }

  function renderSettingsSummary(settings) {
    if (ruleSchedule && settings && settings.defaultSchedule) {
      const normal = settings.journeySchedules && settings.journeySchedules["0004"];
      const compensation = settings.journeySchedules && settings.journeySchedules["0048"];
      ruleSchedule.textContent =
        "JRND 0004 normal " +
        formatShortSchedule(normal || settings.defaultSchedule) +
        " · JRND 0048 compensação " +
        formatShortSchedule(compensation || settings.defaultSchedule);
    }

    if (rulePaidHours && settings && settings.paidHours) {
      const parts = [];
      if (settings.paidHours.weekends) {
        parts.push("sábado e domingo");
      }
      if (settings.paidHours.holidays) {
        parts.push("feriado");
      }
      rulePaidHours.textContent =
        (parts.length ? capitalize(parts.join(", ")) : "Dias não úteis") +
        " com batida = hora paga · domingo JRND 0999";
    }
  }

  function formatShortSchedule(schedule) {
    if (!schedule) {
      return "—";
    }
    return schedule.start + "-" + schedule.end;
  }

  function renderMetric(metric) {
    const wrap = createElement("div", { className: "metric" });
    const head = createElement("div", { className: "metric-head" });
    const label = createElement("span", { className: "metric-label", text: metric.label });
    const icon = createElement("span", {
      className: "metric-icon" + (metric.tone ? " " + metric.tone : ""),
    });
    icon.appendChild(createIcon(metric.label));
    head.append(label, icon);

    const value = createElement("div", {
      className: "metric-value",
      text: String(metric.value),
    });

    wrap.append(head, value);
    return wrap;
  }

  function renderInsightCard(card) {
    const wrap = createElement("article", { className: "insight-card" });
    wrap.append(
      createElement("span", { className: "insight-label", text: card.label }),
      createElement("strong", { text: card.value }),
      createElement("span", { className: "insight-note", text: card.note }),
    );
    return wrap;
  }

  function renderRecentItem(item) {
    const wrap = createElement("article", { className: "recent-item" });
    const head = createElement("div", { className: "recent-item-head" });
    head.append(
      createElement("strong", { text: item.employeeName || "Colaborador não identificado" }),
      createElement("small", { text: item.filename || "Arquivo sem nome" }),
    );

    const meta = createElement("div", { className: "recent-item-meta" });
    meta.append(
      createElement("span", {
        text:
          "Período " +
          formatDate(item.periodStart) +
          " até " +
          formatDate(item.periodEnd),
      }),
      createElement("span", {
        text: "Processado em " + formatDateTime(item.processedAt || item.createdAt),
      }),
    );
    if (item.ownerUsername) {
      meta.append(
        createElement("span", {
          text: "Responsável " + (item.ownerDisplayName || item.ownerUsername),
        }),
      );
    }

    const metrics = createElement("div", { className: "recent-item-metrics" });
    metrics.append(
      createElement("span", {
        className: "recent-metric",
        text: "Saldo " + (item.summary && item.summary.balance ? item.summary.balance : "—"),
      }),
      createElement("span", {
        className: "recent-metric",
        text: "Inconsistências " + String((item.summary && item.summary.inconsistencyCount) || 0),
      }),
      createElement("span", {
        className: "recent-metric",
        text: "Extra paga " + ((item.summary && item.summary.paidOvertime) || "00:00"),
      }),
    );

    const actions = createElement("div", { className: "recent-item-actions" });
    const openButton = createElement("button", {
      className: "btn btn-secondary",
      text: "Abrir resultado",
      attrs: {
        type: "button",
      },
    });
    openButton.addEventListener("click", function () {
      loadReportFromHistory(item.reportId);
    });
    const exportButton = createElement("a", {
      className: "btn btn-secondary",
      text: "Exportar PDF",
      attrs: {
        href: "/api/export/" + encodeURIComponent(item.reportId || ""),
      },
    });
    actions.append(openButton, exportButton);

    wrap.append(head, meta, metrics, actions);
    return wrap;
  }

  async function loadReportFromHistory(reportId) {
    if (!reportId) {
      return;
    }

    setStatus("loading", "Carregando apuração salva…");
    try {
      const response = await fetch("/api/reports/" + encodeURIComponent(reportId), { method: "GET" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Não foi possível reabrir o relatório.");
      }
      renderPayload(payload, true);
      setStatus("success", "Apuração carregada a partir do histórico.");
    } catch (error) {
      console.error(error);
      setStatus("error", error && error.message ? error.message : "Falha ao carregar o histórico.");
    }
  }

  function renderDay(day) {
    const row = createElement("tr");
    if (day.issues && day.issues.length) {
      row.classList.add("row-issue");
    }
    if (day.ignored) {
      row.classList.add("row-ignored");
    }

    const alerts = buildAlerts(day);
    row.append(
      createCellWithDate(day),
      createCell(day.journeyCode || "-"),
      createCell(day.appliedSchedule || "-"),
      createStatusCell(day),
      createCell(day.firstEntry || "-"),
      createCell(day.lastExit || "-"),
      createCell(day.worked || "-"),
      createCell(day.balance || "-"),
      createCell(day.overtimeBeforeLunch || "-"),
      createCell(day.overtimeAfterLunch || "-"),
      createCell(day.paidOvertime || "-"),
      createCell(day.late || "-"),
      createCell(day.earlyLeave || "-"),
      createAlertsCell(alerts),
    );
    return row;
  }

  function createCell(value) {
    return createElement("td", { text: value });
  }

  function createCellWithDate(day) {
    const cell = document.createElement("td");
    cell.append(
      createElement("span", { className: "day-date", text: formatDate(day.date) }),
      createElement("span", { className: "day-weekday", text: day.weekday || "" }),
    );
    return cell;
  }

  function createStatusCell(day) {
    const cell = document.createElement("td");
    let badgeClass = "badge-success";
    if (day.issues && day.issues.length) {
      badgeClass = "badge-warning";
    } else if (day.ignored) {
      badgeClass = "badge-muted";
    }
    cell.appendChild(
      createElement("span", {
        className: "badge " + badgeClass,
        text: day.statusLabel || "—",
      }),
    );
    return cell;
  }

  function createAlertsCell(alerts) {
    const cell = document.createElement("td");
    const list = createElement("ul", { className: "alerts-list" });
    alerts.forEach(function (alert) {
      list.appendChild(createElement("li", { text: alert }));
    });
    cell.appendChild(list);
    return cell;
  }

  function createIssueItem(title, description, isSuccess) {
    const item = createElement("div", { className: "issue" });
    const icon = createElement("span", {
      className: "issue-icon",
      text: isSuccess ? "✓" : "!",
    });
    if (isSuccess) {
      icon.style.background = "var(--success-bg)";
      icon.style.color = "var(--success)";
    }
    const body = createElement("div", { className: "issue-body" });
    body.append(
      createElement("span", { className: "issue-title", text: title }),
      createElement("span", { className: "issue-desc", text: description }),
    );
    item.append(icon, body);
    return item;
  }

  function createStatPill(label, value) {
    const pill = createElement("span", { className: "stat-pill" });
    pill.append(
      createElement("strong", { text: label + ":" }),
      document.createTextNode(" " + value),
    );
    return pill;
  }

  function createEmptyState(message, className) {
    return createElement("div", { className: className, text: message });
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

  function filterDays(days, filter, query) {
    const predicate = filterPredicates[filter] || filterPredicates.all;
    return days.filter(function (day) {
      if (!predicate(day)) {
        return false;
      }
      if (!query) {
        return true;
      }
      return buildSearchText(day).includes(query);
    });
  }

  function buildSearchText(day) {
    return [
      day.date,
      day.weekday,
      day.journeyCode,
      day.appliedSchedule,
      day.statusLabel,
      day.firstEntry,
      day.lastExit,
      day.worked,
      day.balance,
      day.paidOvertime,
      day.late,
      day.earlyLeave,
      day.ignoredReason,
      day.holidayName,
      Array.isArray(day.issues) ? day.issues.join(" ") : "",
    ]
      .join(" ")
      .toLowerCase();
  }

  function syncFilterButtons() {
    if (!filterGroup) return;
    Array.prototype.forEach.call(filterGroup.querySelectorAll("[data-filter]"), function (button) {
      button.classList.toggle("is-active", button.getAttribute("data-filter") === state.filter);
    });
  }

  function renderExportLink(reportId) {
    exportLink.href = "/api/export/" + encodeURIComponent(reportId);
    exportLink.hidden = !reportId;
  }

  function summarizeIgnoredBreakdown(items) {
    if (!items.length) {
      return "Sem exclusões relevantes";
    }
    return items
      .slice(0, 2)
      .map(function (item) {
        return item.label + ": " + item.count;
      })
      .join(" · ");
  }

  function filterLabel(filter) {
    const labels = {
      all: "Todos os dias",
      issues: "Com inconsistência",
      ignored: "Ignorados",
      overtime: "Com extra paga",
      late: "Com atraso/saída antecipada",
    };
    return labels[filter] || "Todos os dias";
  }

  function formatDuration(value) {
    if (typeof value !== "number" || !isFinite(value)) {
      return "—";
    }
    if (value < 1000) {
      return String(value) + " ms";
    }
    return (value / 1000).toFixed(1) + " s";
  }

  function formatDate(isoDate) {
    if (!isoDate || String(isoDate).indexOf("-") === -1) {
      return isoDate || "—";
    }
    const parts = String(isoDate).split("-");
    return parts[2] + "/" + parts[1] + "/" + parts[0];
  }

  function formatDateTime(value) {
    if (!value) {
      return "—";
    }
    return String(value).replace("T", " ");
  }

  function capitalize(value) {
    if (!value) {
      return "";
    }
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function createIcon(label) {
    const text = String(label || "").toLowerCase();
    if (/hora|trabalh|jornada/.test(text)) return createSvgIcon("clock");
    if (/extra/.test(text)) return createSvgIcon("pulse");
    if (/falta|inconsist|ausente|atras/.test(text)) return createSvgIcon("alert");
    if (/dia|presen/.test(text)) return createSvgIcon("calendar");
    if (/saldo|total|banco/.test(text)) return createSvgIcon("list");
    return createSvgIcon("circle");
  }

  function createSvgIcon(kind) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "14");
    svg.setAttribute("height", "14");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");

    const shapes = {
      clock: [
        ["circle", { cx: "12", cy: "12", r: "9" }],
        ["polyline", { points: "12 7 12 12 15 14" }],
      ],
      pulse: [["polyline", { points: "22 12 18 12 15 21 9 3 6 12 2 12" }]],
      alert: [
        ["circle", { cx: "12", cy: "12", r: "9" }],
        ["line", { x1: "9", y1: "9", x2: "15", y2: "15" }],
        ["line", { x1: "15", y1: "9", x2: "9", y2: "15" }],
      ],
      calendar: [
        ["rect", { x: "3", y: "4", width: "18", height: "16", rx: "3" }],
        ["path", { d: "M3 10h18" }],
      ],
      list: [
        ["path", { d: "M3 12h18" }],
        ["path", { d: "M3 6h18" }],
        ["path", { d: "M3 18h18" }],
      ],
      circle: [["circle", { cx: "12", cy: "12", r: "9" }]],
    };

    (shapes[kind] || shapes.circle).forEach(function (shape) {
      const node = document.createElementNS("http://www.w3.org/2000/svg", shape[0]);
      Object.keys(shape[1]).forEach(function (key) {
        node.setAttribute(key, shape[1][key]);
      });
      svg.appendChild(node);
    });

    return svg;
  }

  function createElement(tag, options) {
    const element = document.createElement(tag);
    const config = options || {};
    if (config.className) {
      element.className = config.className;
    }
    if (config.text !== undefined) {
      element.textContent = config.text;
    }
    if (config.attrs) {
      Object.keys(config.attrs).forEach(function (key) {
        element.setAttribute(key, config.attrs[key]);
      });
    }
    return element;
  }
})();
