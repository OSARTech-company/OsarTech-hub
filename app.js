const PYTHON_RUNTIME_URL = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/pyodide.js";

const starterCode = {
  python: `name = "OsarTech"\nprint("Hello,", name)\nprint("Start coding now!")\n`,
  html: `<main>\n  <h1>Hello World</h1>\n  <p>Edit this HTML and run.</p>\n</main>`,
  css: `body {\n  margin: 0;\n  min-height: 100vh;\n  display: grid;\n  place-items: center;\n  font-family: Arial, sans-serif;\n}\n\n.card {\n  padding: 20px;\n  border-radius: 12px;\n  background: #1f5eff;\n  color: white;\n  font-weight: bold;\n}`,
  javascript: `const title = "JavaScript works";\nconsole.log(title);\n`,
};

const storageKey = "osartech-runner-drafts-v1";

const elements = {
  editor: document.getElementById("code-editor"),
  runBtn: document.getElementById("run-btn"),
  resetBtn: document.getElementById("reset-btn"),
  textOutputPanel: document.getElementById("text-output-panel"),
  previewPanel: document.getElementById("preview-panel"),
  textOutput: document.getElementById("text-output"),
  previewFrame: document.getElementById("preview-frame"),
  runtimeStatus: document.getElementById("runtime-status"),
  langButtons: Array.from(document.querySelectorAll(".lang-btn")),
};

const state = {
  language: "python",
  drafts: loadDrafts(),
  pyodideReadyPromise: null,
  isRunning: false,
  loadingTimerId: null,
  pyodideWarmStarted: false,
  pyodideReady: false,
};

function loadDrafts() {
  try {
    const data = JSON.parse(localStorage.getItem(storageKey) || "{}");
    return {
      python: typeof data.python === "string" ? data.python : starterCode.python,
      html: typeof data.html === "string" ? data.html : starterCode.html,
      css: typeof data.css === "string" ? data.css : starterCode.css,
      javascript: typeof data.javascript === "string" ? data.javascript : starterCode.javascript,
    };
  } catch {
    return { ...starterCode };
  }
}

function saveDrafts() {
  localStorage.setItem(storageKey, JSON.stringify(state.drafts));
}

function setRunningState(isRunning, label = "Loading...") {
  state.isRunning = isRunning;
  elements.runBtn.disabled = isRunning;
  elements.resetBtn.disabled = isRunning;

  if (state.loadingTimerId) {
    clearInterval(state.loadingTimerId);
    state.loadingTimerId = null;
  }

  if (isRunning) {
    let dots = 0;
    elements.runBtn.textContent = label;
    state.loadingTimerId = setInterval(() => {
      dots = (dots + 1) % 4;
      elements.runBtn.textContent = `${label}${".".repeat(dots)}`;
    }, 320);
  } else {
    elements.runBtn.textContent = "Run";
  }
}

function activateLanguage(language) {
  state.language = language;
  elements.editor.value = state.drafts[language];

  elements.langButtons.forEach((button) => {
    const active = button.dataset.lang === language;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });

  const previewMode = language === "html" || language === "css" || language === "javascript";
  elements.previewPanel.hidden = !previewMode;
  elements.textOutputPanel.hidden = previewMode;
  elements.runtimeStatus.textContent = "Ready";
}

function ensurePyodide() {
  if (window.loadPyodide) {
    return state.pyodideReadyPromise || (state.pyodideReadyPromise = window.loadPyodide());
  }

  if (!state.pyodideReadyPromise) {
    state.pyodideReadyPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = PYTHON_RUNTIME_URL;
      script.onload = async () => {
        try {
          resolve(await window.loadPyodide());
        } catch (error) {
          reject(error);
        }
      };
      script.onerror = () => reject(new Error("Could not load Python runtime."));
      document.head.appendChild(script);
    });
  }

  return state.pyodideReadyPromise;
}

function warmPythonRuntime() {
  if (state.pyodideWarmStarted || state.pyodideReady) {
    return;
  }
  state.pyodideWarmStarted = true;

  ensurePyodide()
    .then(() => {
      state.pyodideReady = true;
      if (state.language === "python" && !state.isRunning) {
        elements.runtimeStatus.textContent = "Python ready";
      }
    })
    .catch(() => {
      // Keep silent here. The run flow already shows actionable errors.
    });
}

async function runPython(code) {
  setRunningState(true, "Loading...");
  elements.runtimeStatus.textContent = state.pyodideReady ? "Running Python..." : "Loading Python engine (first run can take time)...";
  elements.textOutput.textContent = "Running...";
  try {
    const pyodide = await ensurePyodide();
    state.pyodideReady = true;
    const output = [];

    pyodide.setStdout({
      batched(message) {
        output.push(message);
      },
    });

    pyodide.setStderr({
      batched(message) {
        output.push(`Error: ${message}`);
      },
    });

    await pyodide.runPythonAsync(code);
    elements.textOutput.textContent = output.join("\n") || "Python ran successfully.";
    elements.runtimeStatus.textContent = "Python ready";
  } catch (error) {
    elements.textOutput.textContent = `Error: ${error.message}`;
    elements.runtimeStatus.textContent = "Python error";
  } finally {
    setRunningState(false);
  }
}

function buildWebPreviewDocument(options = {}) {
  const html = state.drafts.html || "<main><h1>Hello World</h1></main>";
  const css = state.drafts.css || "";
  const js = state.drafts.javascript || "";
  const runJs = Boolean(options.runJs);

  if (!runJs) {
    return `
      <!doctype html>
      <html lang="en">
        <head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <style>${css}</style>
        </head>
        <body>
          ${html}
        </body>
      </html>
    `;
  }

  return `
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>${css}</style>
      </head>
      <body>
        ${html}
        <main style="font-family: Arial, sans-serif; padding: 1rem;">
          <h2>JavaScript Console Output</h2>
          <pre id="log" style="background:#101624;color:#e8eefc;padding:0.75rem;border-radius:8px;"></pre>
        </main>
        <script>
          const lines = [];
          const logEl = document.getElementById("log");
          const write = (msg) => {
            lines.push(msg);
            logEl.textContent = lines.join("\\n");
          };
          console.log = (...args) => write(args.map(String).join(" "));
          window.onerror = (message) => write("Error: " + message);
          try {
            ${js}
            if (!lines.length) write("JavaScript ran successfully.");
          } catch (e) {
            write("Error: " + e.message);
          }
        <\/script>
      </body>
    </html>
  `;
}

async function runCurrentLanguage() {
  if (state.isRunning) {
    return;
  }

  setRunningState(true, "Loading...");
  const code = elements.editor.value;
  state.drafts[state.language] = code;
  saveDrafts();

  if (state.language === "python") {
    await runPython(code);
    return;
  }

  if (state.language === "html") {
    elements.runtimeStatus.textContent = "Rendering preview...";
    elements.previewFrame.srcdoc = buildWebPreviewDocument({ runJs: false });
    setRunningState(false);
    return;
  }

  if (state.language === "css") {
    elements.runtimeStatus.textContent = "Rendering preview...";
    elements.previewFrame.srcdoc = buildWebPreviewDocument({ runJs: false });
    setRunningState(false);
    return;
  }

  elements.runtimeStatus.textContent = "Running JavaScript...";
  elements.previewFrame.srcdoc = buildWebPreviewDocument({ runJs: true });
  setRunningState(false);
}

function resetCurrentLanguage() {
  state.drafts[state.language] = starterCode[state.language];
  saveDrafts();
  elements.editor.value = state.drafts[state.language];
  if (state.language === "python") {
    elements.textOutput.textContent = "Reset complete. Run code again.";
    elements.runtimeStatus.textContent = "Ready";
  } else {
    runCurrentLanguage();
  }
}

function attachEvents() {
  elements.langButtons.forEach((button) => {
    button.addEventListener("click", () => {
      activateLanguage(button.dataset.lang);
      if (button.dataset.lang === "python") {
        warmPythonRuntime();
      }
    });
  });

  elements.editor.addEventListener("input", () => {
    state.drafts[state.language] = elements.editor.value;
    saveDrafts();
  });

  elements.runBtn.addEventListener("click", runCurrentLanguage);
  elements.resetBtn.addEventListener("click", resetCurrentLanguage);
}

function init() {
  attachEvents();
  activateLanguage("python");
  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(() => warmPythonRuntime(), { timeout: 2500 });
  } else {
    setTimeout(() => warmPythonRuntime(), 1200);
  }
}

init();
