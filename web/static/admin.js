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
  const usersCount = document.getElementById("admin-users-count");
  const usersList = document.getElementById("admin-users-list");
  const userHistory = document.getElementById("admin-user-history");
  const userForm = document.getElementById("admin-user-form");
  const userFormTitle = document.getElementById("admin-user-form-title");
  const userStatus = document.getElementById("admin-user-status");
  const userResetButton = document.getElementById("admin-user-reset");
  const persistenceSummary = document.getElementById("admin-persistence-summary");
  const persistenceStatus = document.getElementById("admin-persistence-status");
  const persistenceJson = document.getElementById("admin-persistence-json");
  const storageCheckButton = document.getElementById("admin-storage-check");

  if (loginForm) {
    loginForm.addEventListener("submit", handleLoginSubmit);
  }

  if (settingsForm) {
    loadSettings();
    settingsForm.addEventListener("submit", handleSettingsSubmit);
  }

  if (persistenceSummary) {
    loadPersistenceStatus();
  }

  if (userForm) {
    resetUserForm();
    loadUsers();
    userForm.addEventListener("submit", handleUserSubmit);
  }

  if (userResetButton) {
    userResetButton.addEventListener("click", resetUserForm);
  }

  if (logoutButton) {
    logoutButton.addEventListener("click", handleLogout);
  }

  if (storageCheckButton) {
    storageCheckButton.addEventListener("click", handleStorageCheck);
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

  async function loadUsers() {
    if (!usersList || !usersCount) {
      return;
    }
    setStatus(userStatus, "loading", "Carregando usuários...");
    try {
      const response = await fetch("/api/admin/users", { method: "GET" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Falha ao carregar usuários.");
      }
      renderUsers(payload.items || []);
      await loadUserHistory();
      setStatus(userStatus, "success", "Usuários carregados.");
    } catch (error) {
      if (error.message && /Autenticacao/.test(error.message)) {
        window.location.href = "/admin/login";
        return;
      }
      renderUsers([]);
      setStatus(userStatus, "error", error.message || "Falha ao carregar usuários.");
    }
  }

  async function loadPersistenceStatus() {
    setStatus(persistenceStatus, "loading", "Consultando status da persistência...");
    try {
      const response = await fetch("/api/admin/persistence", { method: "GET" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Falha ao carregar persistência.");
      }
      renderPersistenceStatus(payload);
      setStatus(
        persistenceStatus,
        payload.enabled ? "success" : "error",
        payload.enabled ? "D1 pronto para uso em produção." : "D1 ainda não configurado.",
      );
    } catch (error) {
      setStatus(persistenceStatus, "error", error.message || "Falha ao carregar persistência.");
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

  async function handleUserSubmit(event) {
    event.preventDefault();
    const mode = document.getElementById("admin-user-mode").value;
    const username = document.getElementById("admin-user-username").value.trim();
    const originalUsername = document.getElementById("admin-user-original-username").value.trim();
    const password = document.getElementById("admin-user-password").value;
    const payload = {
      username: username,
      role: document.getElementById("admin-user-role").value,
      displayName: document.getElementById("admin-user-display-name").value.trim(),
      email: document.getElementById("admin-user-email").value.trim(),
      isActive: document.getElementById("admin-user-active").checked,
    };

    if (!username) {
      setStatus(userStatus, "error", "Informe o nome de usuário.");
      return;
    }
    if (mode === "create" && !password) {
      setStatus(userStatus, "error", "Defina uma senha para criar o usuário.");
      return;
    }
    if (password) {
      payload.password = password;
    }

    setStatus(userStatus, "loading", mode === "create" ? "Criando usuário..." : "Atualizando usuário...");
    try {
      const response = await fetch(
        mode === "create"
          ? "/api/admin/users"
          : "/api/admin/users/" + encodeURIComponent(originalUsername || username),
        {
          method: mode === "create" ? "POST" : "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      const responsePayload = await response.json();
      if (!response.ok) {
        throw new Error(responsePayload.detail || "Falha ao salvar usuário.");
      }
      resetUserForm();
      await loadUsers();
      setStatus(userStatus, "success", mode === "create" ? "Usuário criado com sucesso." : "Usuário atualizado com sucesso.");
    } catch (error) {
      setStatus(userStatus, "error", error.message || "Falha ao salvar usuário.");
    }
  }

  async function loadUserHistory() {
    if (!userHistory) {
      return;
    }
    try {
      const response = await fetch("/api/admin/users/history", { method: "GET" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Falha ao carregar auditoria de usuários.");
      }
      renderUserHistory(payload.items || []);
    } catch (error) {
      renderUserHistory([]);
    }
  }

  async function handleStorageCheck() {
    setStatus(persistenceStatus, "loading", "Executando teste de escrita, leitura e limpeza no storage...");
    try {
      const response = await fetch("/api/admin/storage/diagnostics", { method: "POST" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error((payload.storage && payload.storage.error) || payload.detail || "Falha ao testar o R2.");
      }
      renderPersistenceStatus(payload.status || {});
      if (persistenceJson) {
        persistenceJson.textContent = JSON.stringify(payload, null, 2);
      }
      setStatus(persistenceStatus, "success", "Teste de storage concluído com sucesso.");
    } catch (error) {
      setStatus(persistenceStatus, "error", error.message || "Falha ao testar o storage.");
    }
  }

  function populateForm(settings) {
    document.getElementById("schedule-start").value = settings.defaultSchedule.start;
    document.getElementById("schedule-lunch-start").value = settings.defaultSchedule.lunchStart;
    document.getElementById("schedule-lunch-end").value = settings.defaultSchedule.lunchEnd;
    document.getElementById("schedule-end").value = settings.defaultSchedule.end;
    populateJourneySchedule("0004", settings);
    populateJourneySchedule("0048", settings);
    populateJourneySchedule("0996", settings);
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
        "0996": collectJourneySchedule("0996"),
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
      summaryCard("JRND 0996", formatSchedule(settings.journeySchedules["0996"]), "Jornada usada para sábado."),
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

  function renderUsers(items) {
    if (!usersList || !usersCount) {
      return;
    }

    usersCount.textContent = String(items.length);
    usersCount.className = "badge " + (items.length ? "badge-success" : "badge-muted");

    if (!Array.isArray(items) || !items.length) {
      usersList.replaceChildren(
        createElement("div", {
          className: "admin-history-empty",
          text: "Nenhum usuário persistido ainda.",
        }),
      );
      return;
    }

    usersList.replaceChildren.apply(
      usersList,
      items.map(function (item) {
        const card = document.createElement("article");
        card.className = "admin-user-card";

        const meta = createElement("div", { className: "admin-user-meta" });
        meta.append(
          createElement("strong", { text: item.displayName || item.username }),
          createElement("span", {
            className: "badge " + (item.role === "admin" ? "badge-warning" : "badge-muted"),
            text: item.role === "admin" ? "Administrador" : "Usuário",
          }),
          createElement("span", {
            className: "badge " + (item.isActive ? "badge-success" : "badge-muted"),
            text: item.isActive ? "Ativo" : "Inativo",
          }),
        );

        const details = createElement("div", { className: "admin-user-details" });
        details.append(
          createElement("span", { text: "Login: " + item.username }),
          createElement("span", { text: "E-mail: " + (item.email || "não informado") }),
          createElement("span", { text: "Atualizado em " + formatDateTime(item.updatedAt) }),
        );

        const actions = createElement("div", { className: "admin-user-actions" });
        const editButton = createElement("button", {
          className: "btn btn-secondary",
          text: "Editar",
          attrs: { type: "button" },
        });
        editButton.addEventListener("click", function () {
          populateUserForm(item);
        });
        actions.append(editButton);

        card.append(meta, details, actions);
        return card;
      }),
    );
  }

  function renderPersistenceStatus(status) {
    if (!persistenceSummary) {
      return;
    }
    const storageProbe = status.storageProbe || null;
    const recordCounts = status.recordCounts || {};
    const d1Counts = recordCounts.d1 || {};
    const d1BindingName = status.d1BindingName || "—";
    const r2BindingName = status.r2BindingName || "—";
    const r2BucketName = status.r2BucketName || "—";
    const d1Mode = status.d1Mode || "disabled";
    const r2Mode = status.r2Mode || "local";
    const cards = [
      summaryCard("Backend atual", status.backend || "memory", "Estado visto pelo healthcheck do app."),
      summaryCard("Storage ativo", status.storageBackend || "local", "Backend atual dos arquivos de relatório."),
      summaryCard("D1 ativo", status.enabled ? "Sim" : "Não", "Ativa quando o binding nativo do D1 está configurado no Worker."),
      summaryCard("Modo de execução", status.runtimeMode || "memory", "Fluxo atual de persistência da aplicação."),
      summaryCard("Binding D1", d1BindingName, d1Mode === "native-binding" ? "Integração nativa detectada automaticamente." : "Nome do binding D1 conectado ao Worker."),
      summaryCard("Binding R2", r2BindingName, r2Mode === "native-binding" ? "Integração nativa detectada automaticamente." : "Nome do binding R2 conectado ao Worker."),
      summaryCard("Bucket R2", r2BucketName, "Bucket principal usado para PDFs e exportações."),
      summaryCard("Usuários no D1", String(d1Counts.users || 0), "Contas persistidas remotamente."),
      summaryCard("Relatórios no D1", String(d1Counts.reports || 0), "Apurações armazenadas no banco principal."),
      summaryCard("Regras atuais no D1", String(d1Counts.settingsCurrent || 0), "Escopos persistidos em settings_current."),
      summaryCard("Auditoria no D1", String((d1Counts.settingsAudit || 0) + (d1Counts.userAudit || 0)), "Soma de settings_audit e user_audit."),
      summaryCard("Fallback local", status.runtimeMode === "memory" ? "Ativo" : "Inativo", "Usado apenas quando o D1 não está disponível."),
    ];
    if (storageProbe) {
      cards.push(
        summaryCard(
          "Teste do storage",
          storageProbe.ok ? "OK" : "Falhou",
          storageProbe.bucket
            ? "Bucket " + storageProbe.bucket + " · chave " + (storageProbe.key || "—")
            : "Storage local de desenvolvimento",
        ),
      );
    }
    persistenceSummary.replaceChildren.apply(persistenceSummary, cards);
    if (persistenceJson) {
      persistenceJson.textContent = JSON.stringify(status, null, 2);
    }
  }

  function renderUserHistory(items) {
    if (!userHistory) {
      return;
    }

    if (!Array.isArray(items) || !items.length) {
      userHistory.replaceChildren(
        createElement("div", {
          className: "admin-history-empty",
          text: "Nenhuma alteração de usuário registrada ainda.",
        }),
      );
      return;
    }

    userHistory.replaceChildren.apply(
      userHistory,
      items.map(function (item) {
        const entry = document.createElement("article");
        entry.className = "admin-history-item";
        entry.append(
          createElement("div", {
            className: "admin-history-meta",
            text: (item.actor || "admin") + " · " + formatDateTime(item.changedAt),
          }),
          createElement("strong", {
            className: "admin-history-title",
            text: (item.action === "create" ? "Criação" : "Atualização") + " · " + item.targetUsername,
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

  function populateUserForm(user) {
    document.getElementById("admin-user-mode").value = "update";
    document.getElementById("admin-user-original-username").value = user.username || "";
    document.getElementById("admin-user-username").value = user.username || "";
    document.getElementById("admin-user-username").disabled = true;
    document.getElementById("admin-user-role").value = user.role || "user";
    document.getElementById("admin-user-display-name").value = user.displayName || "";
    document.getElementById("admin-user-email").value = user.email || "";
    document.getElementById("admin-user-password").value = "";
    document.getElementById("admin-user-active").checked = Boolean(user.isActive);
    if (userFormTitle) {
      userFormTitle.textContent = "Editar usuário";
    }
  }

  function resetUserForm() {
    if (!userForm) {
      return;
    }
    document.getElementById("admin-user-mode").value = "create";
    document.getElementById("admin-user-original-username").value = "";
    document.getElementById("admin-user-username").value = "";
    document.getElementById("admin-user-username").disabled = false;
    document.getElementById("admin-user-role").value = "user";
    document.getElementById("admin-user-display-name").value = "";
    document.getElementById("admin-user-email").value = "";
    document.getElementById("admin-user-password").value = "";
    document.getElementById("admin-user-active").checked = true;
    if (userFormTitle) {
      userFormTitle.textContent = "Novo usuário";
    }
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
