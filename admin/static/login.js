async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (res.status === 503) {
      document.getElementById("status-line").textContent =
        "Ventana de administración cerrada.";
      return;
    }
    const data = await res.json();
    const el = document.getElementById("status-line");
    if (data.ventana_abierta) {
      el.textContent = `Tiempo restante: ${data.segundos_restantes}s · SSID: ${data.ssid}`;
    }
  } catch (_) {
    /* ignore */
  }
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const errEl = document.getElementById("login-error");
  errEl.classList.add("hidden");

  const body = {
    usuario: form.usuario.value,
    clave: form.clave.value,
  };

  try {
    const res = await fetch("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.error || "Error de login.";
      errEl.classList.remove("hidden");
      return;
    }
    window.location.href = "/";
  } catch (err) {
    errEl.textContent = "No se pudo conectar al portal.";
    errEl.classList.remove("hidden");
  }
});

fetchStatus();
setInterval(fetchStatus, 5000);
