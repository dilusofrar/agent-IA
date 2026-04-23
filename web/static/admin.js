(function () {
  "use strict";

  const loginForm = document.getElementById("admin-login-form");
  const loginStatus = document.getElementById("admin-login-status");
  const settingsForm = document.getElementById("admin-settings-form");
  const settingsStatus = document.getElementById("admin-settings-status");
  const logoutButton = document.getElementById("admin-logout");
  const summaryGrid = document.getElementById("admin-settings-summary");
  const historyList = document.getElementById("admin-settings-history");
  const jsonPreview = document.getElementById("admin-settings-json");

  if (loginForm) {
    loginForm.addEventListener("submit", handleLoginSubmit);
  }

  if (settingsForm) {
    loadSettings();
    settingsForm.addEventListener("submit", handleSettingsSubmit);
  }

  if (logoutButton) {
    logoutButton.addEventListener("click", handleLogout);
  }

  async function handleLoginSubmit(event) {
    event.preventDefault();
    const username = document.getElementById("admin-username").value.trim();
    const password = document.getElementById("admin-password").value;

    setStatus(loginStatus, "loading", "Validando credenciais…");
    try {
      const response = await fetch("/api/admin/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username, password: password }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Falha ao autenticar.");
      }
      setStatus(loginStatus, "success", "Acesso liberado. Redirecionando…");
      window.location.href = "/admin";
    } catch (error) {
      setStatus(loginStatus, "error", error.message || "Falha ao autenticar.");
    }
  }

  async function loadSettings() {
    setStatus(settingsStatus, "loading", "Carregando regras persistentes…");
    try {
      const responses = await Promise.all([
        fetch("/api/settings", { method: "GET" }),
        fetch("/api/settings/history", { method: "GET" }),
      ]);
      const payloads = await Promise.all(responses.map(function (response) {
        return response.json();
      }));
      if (!responses[0].ok) {
        throw new Error(payloads[0].detail || "Falha ao carregar regras.");
      }
      if (!responses[1].ok) {
        throw new Error(payloads[1].detail || "Falha ao carregar histórico.");
      }
      populateForm(payloads[0]);
      renderSummary(payloads[0]);
      renderHistory(payloads[1].items || []);
      setStatus(settingsStatus, "success", "Regras carregadas.");
    } catch (error) {
      if (error.message && /Autenticacao/.test(error.message)) {
        window.location.href = "/admin/login";
        return;
      }
      setStatus(settingsStatus, "error", error.message || "Falha ao carregar regras.");
    }
  }

  async function handleSettingsSubmit(event) {
    event.preventDefault();
    const payload = collectSettingsPayload();
    setStatus(settingsStatus, "loading", "Salvando regras de apuração…");

    try {
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const responsePayload = await response.json();
      if (!response.ok) {
        throw new Error(responsePayload.detail || "Falha ao salvar regras.");
      }
      populateForm(responsePayload);
      renderSummary(responsePayload);
      await refreshHistory();
      setStatus(settingsStatus, "success", "Regras salvas com sucesso.");
    } catch (error) {
      setStatus(settingsStatus, "error", error.message || "Falha ao salvar regras.");
    }
  }

  async function handleLogout() {
    await fetch("/api/admin/session", { method: "DELETE" });
    window.location.href = "/admin/login";
  }

  function populateForm(settings) {
    document.getElementById("schedule-start").value = settings.defaultSchedule.start;
    document.getElementById("schedule-lunch-start").value = settings.defaultSchedule.lunchStart;
    document.getElementById("schedule-lunch-end").value = settings.defaultSchedule.lunchEnd;
    document.getElementById("schedule-end").value = settings.defaultSchedule.end;
    populateJourneySchedule("0004", settings);
    populateJourneySchedule("0048", settings);
    populateJourneySchedule("0999", settings);
    document.getElementById("paid-weekends").checked = Boolean(settings.paidHours.weekends);
    document.getElementById("paid-holidays").checked = Boolean(settings.paidHours.holidays);
    document.getElementById("paid-status-codes").value = (settings.paidHours.statusCodes || []).join(", ");
    document.getElementById("journey-0004-tolerance").value =
      settings.journeyRules && settings.journeyRules["0004"]
        ? String(settings.journeyRules["0004"].lateToleranceMinutes || 0)
        : "0";
    document.getElementById("journey-0004-extra-before").checked =
      Boolean(
        settings.journeyRules &&
        settings.journeyRules["0004"] &&
        settings.journeyRules["0004"].countOvertimeBeforeStart
      );

    Array.prototype.forEach.call(document.querySelectorAll(".weekday-grid input[type='checkbox']"), function (input) {
      input.checked = Array.isArray(settings.workingWeekdays)
        ? settings.workingWeekdays.indexOf(Number(input.value)) >= 0
        : false;
    });
  }

  function collectSettingsPayload() {
    const workingWeekdays = Array.prototype.map
      .call(document.querySelectorAll(".weekday-grid input[type='checkbox']:checked"), function (input) {
        return Number(input.value);
      })
      .sort();

    return {
      defaultSchedule: {
        start: document.getElementById("schedule-start").value,
        lunchStart: document.getElementById("schedule-lunch-start").value,
        lunchEnd: document.getElementById("schedule-lunch-end").value,
        end: document.getElementById("schedule-end").value,
      },
      workingWeekdays: workingWeekdays,
      paidHours: {
        weekends: document.getElementById("paid-weekends").checked,
        holidays: document.getElementById("paid-holidays").checked,
        statusCodes: document.getElementById("paid-status-codes").value
          .split(",")
          .map(function (item) { return item.trim().toUpperCase(); })
          .filter(Boolean),
      },
      journeySchedules: {
        "0004": collectJourneySchedule("0004"),
        "0048": collectJourneySchedule("0048"),
        "0999": collectJourneySchedule("0999"),
      },
      journeyRules: {
        "0004": {
          countOvertimeBeforeStart: document.getElementById("journey-0004-extra-before").checked,
          lateToleranceMinutes: Number(document.getElementById("journey-0004-tolerance").value || 0),
        },
      },
    };
  }

  function renderSummary(settings) {
    if (!summaryGrid || !jsonPreview) {
      return;
    }

    const cards = [
      summaryCard("Jornada padrão", settings.defaultSchedule.start + "-" + settings.defaultSchedule.lunchStart + " / " + settings.defaultSchedule.lunchEnd + "-" + settings.defaultSchedule.end, "Base usada quando o PDF não informar outra jornada."),
      summaryCard("JRND 0004", formatSchedule(settings.journeySchedules["0004"]), "Jornada normal padrão."),
      summaryCard("JRND 0048", formatSchedule(settings.journeySchedules["0048"]), "Jornada de compensação."),
      summaryCard("JRND 0999", formatSchedule(settings.journeySchedules["0999"]), "Jornada usada para domingo."),
      summaryCard("Dias úteis", (settings.workingWeekdays || []).map(weekdayLabel).join(", "), "Dias considerados úteis para cálculo normal."),
      summaryCard("Fim de semana", settings.paidHours.weekends ? "Pago" : "Ignorado", "Sábado e domingo com batida."),
      summaryCard("Feriado", settings.paidHours.holidays ? "Pago" : "Ignorado", "Feriado com batida."),
      summaryCard("Status pagos", (settings.paidHours.statusCodes || []).join(", ") || "Nenhum", "Status que geram hora paga fora da rotina."),
      summaryCard("Regra 0004", (settings.journeyRules["0004"].lateToleranceMinutes || 0) + " min de tolerância", settings.journeyRules["0004"].countOvertimeBeforeStart ? "Conta extra antes do início." : "Não conta extra antes do início."),
    ];
    summaryGrid.replaceChildren.apply(summaryGrid, cards);
    jsonPreview.textContent = JSON.stringify(settings, null, 2);
  }

  async function refreshHistory() {
    try {
      const response = await fetch("/api/settings/history", { method: "GET" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Falha ao carregar histórico.");
      }
      renderHistory(payload.items || []);
    } catch (error) {
      renderHistory([]);
    }
  }

  function renderHistory(items) {
    if (!historyList) {
      return;
    }

    if (!Array.isArray(items) || !items.length) {
      historyList.replaceChildren(
        createElement("div", {
          className: "admin-history-empty",
          text: "Nenhuma alteração registrada ainda.",
        }),
      );
      return;
    }

    historyList.replaceChildren.apply(
      historyList,
      items.map(function (item) {
        const entry = document.createElement("article");
        entry.className = "admin-history-item";
        entry.append(
          createElement("div", {
            className: "admin-history-meta",
            text: formatHistoryMeta(item),
          }),
          createElement("strong", {
            className: "admin-history-title",
            text: buildHistoryTitle(item),
          }),
          createHistoryChanges(item.changes || []),
        );
        return entry;
      }),
    );
  }

  function summaryCard(label, value, note) {
    const card = document.createElement("article");
    card.className = "insight-card";
    card.append(
      createElement("span", { className: "insight-label", text: label }),
      createElement("strong", { text: value }),
      createElement("span", { className: "insight-note", text: note }),
    );
    return card;
  }

  function populateJourneySchedule(code, settings) {
    const schedule = settings.journeySchedules && settings.journeySchedules[code] ? settings.journeySchedules[code] : null;
    if (!schedule) {
      return;
    }
    document.getElementById("journey-" + code + "-start").value = schedule.start;
    document.getElementById("journey-" + code + "-lunch-start").value = schedule.lunchStart;
    document.getElementById("journey-" + code + "-lunch-end").value = schedule.lunchEnd;
    document.getElementById("journey-" + code + "-end").value = schedule.end;
  }

  function collectJourneySchedule(code) {
    return {
      start: document.getElementById("journey-" + code + "-start").value,
      lunchStart: document.getElementById("journey-" + code + "-lunch-start").value,
      lunchEnd: document.getElementById("journey-" + code + "-lunch-end").value,
      end: document.getElementById("journey-" + code + "-end").value,
    };
  }

  function formatSchedule(schedule) {
    if (!schedule) {
      return "—";
    }
    return schedule.start + "-" + schedule.lunchStart + " / " + schedule.lunchEnd + "-" + schedule.end;
  }

  function createHistoryChanges(changes) {
    const list = document.createElement("ul");
    list.className = "admin-history-changes";
    (changes.length ? changes : ["Alteração registrada sem resumo disponível."]).forEach(function (change) {
      const item = document.createElement("li");
      item.textContent = change;
      list.append(item);
    });
    return list;
  }

  function buildHistoryTitle(item) {
    const totalChanges = Array.isArray(item.changes) ? item.changes.length : 0;
    return totalChanges === 1
      ? "1 regra atualizada"
      : totalChanges + " ajustes registrados";
  }

  function formatHistoryMeta(item) {
    const actor = item.actor || "admin";
    const changedAt = item.changedAt ? formatDateTime(item.changedAt) : "momento não informado";
    return actor + " · " + changedAt;
  }

  function formatDateTime(value) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return parsed.toLocaleString("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
    });
  }

  function weekdayLabel(value) {
    return ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"][Number(value)] || "?";
  }

  function setStatus(target, kind, message) {
    if (!target) {
      return;
    }
    target.hidden = false;
    target.className = "status";
    if (kind) {
      target.classList.add("is-" + kind);
    }
    target.textContent = message;
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
    return element;
  }
})();
