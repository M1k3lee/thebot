document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-toggle-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.getAttribute("data-toggle-target");
      const target = document.getElementById(targetId);
      if (!target) return;
      target.classList.toggle("is-hidden");
    });
  });

  document.querySelectorAll("[data-confirm]").forEach((button) => {
    button.addEventListener("click", (event) => {
      const message = button.getAttribute("data-confirm");
      if (message && !window.confirm(message)) {
        event.preventDefault();
      }
    });
  });
});
