(function () {
  "use strict";

  const form = document.getElementById("app-login-form");
  const usernameInput = document.getElementById("app-username");
  const passwordInput = document.getElementById("app-password");
  const statusEl = document.getElementById("app-login-status");

  checkExistingSession();

  if (form) {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();

      const username = String(usernameInput && usernameInput.value || "").trim();
      const password = String(passwordInput && passwordInput.value || "");
      if (!username || !password) {
        setStatus("error", "Preencha usuário e senha para continuar.");
        return;
      }

      setStatus("loading", "Validando acesso...");
      try {
        const response = await fetch("/api/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: username, password: password }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Não foi possível autenticar.");
        }
        setStatus("success", "Acesso liberado. Redirecionando...");
        window.location.href = "/";
      } catch (error) {
        setStatus("error", error && error.message ? error.message : "Falha ao entrar.");
      }
    });
  }

  async function checkExistingSession() {
    try {
      const response = await fetch("/api/session", { method: "GET" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      if (payload && payload.authenticated) {
        window.location.replace("/");
      }
    } catch (error) {
      console.error(error);
    }
  }

  function setStatus(kind, message) {
    if (!statusEl) {
      return;
    }
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
