(function () {
  "use strict";
  var loading = false;

  // Solo se actualiza la lista; los formularios de registro no se interrumpen.
  async function refreshAppointments() {
    var panel = document.querySelector(".appointment-live-panel");
    if (loading || document.hidden || !panel || panel.querySelector("details[open]") ||
        (document.activeElement !== document.body && panel.contains(document.activeElement))) return;
    loading = true;
    try {
      var response = await fetch(window.location.href, {
        credentials: "same-origin", cache: "no-store"
      });
      if (!response.ok || response.redirected) return;
      var page = new DOMParser().parseFromString(await response.text(), "text/html");
      var updated = page.querySelector(".appointment-live-panel");
      if (!updated || !panel.isConnected || panel.querySelector("details[open]") ||
          (document.activeElement !== document.body && panel.contains(document.activeElement))) return;
      var oldScroll = panel.querySelector(".table-wrap");
      var scrollLeft = oldScroll ? oldScroll.scrollLeft : 0;
      panel.replaceWith(updated);
      var newScroll = updated.querySelector(".table-wrap");
      if (newScroll) newScroll.scrollLeft = scrollLeft;
    } catch (error) {
      // Una desconexión no modifica los estados ni borra la lista mostrada.
    } finally {
      loading = false;
    }
  }

  document.addEventListener("click", async function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    try {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(button.dataset.copy);
      } else {
        var area = document.createElement("textarea");
        area.value = button.dataset.copy;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
        button.focus();
      }
      button.title = "Código copiado";
    } catch (error) {
      button.title = "No se pudo copiar el código";
    }
  });
  window.setInterval(refreshAppointments, 30000);
  document.addEventListener("visibilitychange", refreshAppointments);
})();
