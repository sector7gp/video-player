const configEditor = document.getElementById("config-editor");
const configMsg = document.getElementById("config-msg");
const uploadMsg = document.getElementById("upload-msg");
const countdown = document.getElementById("countdown");
const videoPath = document.getElementById("video-path");

function showMsg(el, text, ok) {
  el.textContent = text;
  el.classList.remove("hidden", "ok", "err");
  el.classList.add(ok ? "ok" : "err");
}

async function apiFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("No autenticado");
  }
  if (res.status === 503) {
    throw new Error("Ventana de administración cerrada.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const det = data.detalles ? "\n" + data.detalles.join("\n") : "";
    throw new Error((data.error || "Error") + det);
  }
  return data;
}

async function refreshStatus() {
  const data = await apiFetch("/api/status");
  countdown.textContent = `${data.segundos_restantes}s restantes`;
  if (data.video_path) {
    videoPath.textContent = data.video_path;
  }
  if (!data.ventana_abierta) {
    countdown.textContent = "Ventana cerrada";
  }
}

async function loadConfig() {
  const data = await apiFetch("/api/config");
  configEditor.value = JSON.stringify(data, null, 2);
  if (data.video && data.video.path) {
    videoPath.textContent = data.video.path;
  }
}

document.getElementById("reload-btn").addEventListener("click", () => {
  loadConfig().catch((e) => showMsg(configMsg, e.message, false));
});

document.getElementById("save-btn").addEventListener("click", async () => {
  configMsg.classList.add("hidden");
  let parsed;
  try {
    parsed = JSON.parse(configEditor.value);
  } catch (e) {
    showMsg(configMsg, "JSON inválido: " + e.message, false);
    return;
  }
  try {
    await apiFetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(parsed),
    });
    showMsg(configMsg, "Config guardada. Reproductor reiniciado.", true);
  } catch (e) {
    showMsg(configMsg, e.message, false);
  }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  await fetch("/logout", { method: "POST" });
  window.location.href = "/login";
});

document.getElementById("upload-btn").addEventListener("click", () => {
  const input = document.getElementById("video-file");
  const file = input.files[0];
  if (!file) {
    showMsg(uploadMsg, "Seleccioná un archivo MP4.", false);
    return;
  }

  uploadMsg.classList.add("hidden");
  const wrap = document.getElementById("progress-wrap");
  const bar = document.getElementById("upload-progress");
  const text = document.getElementById("progress-text");
  wrap.classList.remove("hidden");
  bar.value = 0;
  text.textContent = "0%";

  const form = new FormData();
  form.append("video", file);

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/video");
  xhr.upload.onprogress = (ev) => {
    if (ev.lengthComputable) {
      const pct = Math.round((ev.loaded / ev.total) * 100);
      bar.value = pct;
      text.textContent = pct + "%";
    }
  };
  xhr.onload = () => {
    wrap.classList.add("hidden");
    let data = {};
    try {
      data = JSON.parse(xhr.responseText);
    } catch (_) {
      /* ignore */
    }
    if (xhr.status === 401) {
      window.location.href = "/login";
      return;
    }
    if (xhr.status >= 200 && xhr.status < 300) {
      showMsg(uploadMsg, "Video subido. Reproductor reiniciado.", true);
      input.value = "";
      loadConfig().catch(() => {});
      return;
    }
    showMsg(uploadMsg, data.error || "Error al subir video.", false);
  };
  xhr.onerror = () => {
    wrap.classList.add("hidden");
    showMsg(uploadMsg, "Error de red al subir.", false);
  };
  xhr.send(form);
});

loadConfig().catch((e) => showMsg(configMsg, e.message, false));
refreshStatus().catch(() => {});
setInterval(() => refreshStatus().catch(() => {}), 5000);
