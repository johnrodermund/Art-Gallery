// Small progressive enhancements. The site works without JavaScript.
(function () {
  "use strict";

  // Ask before destructive actions.
  document.addEventListener("submit", function (event) {
    var message = event.target.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  });

  // Status drop-downs on the dashboard save as soon as they change.
  document.querySelectorAll("select[data-autosubmit]").forEach(function (select) {
    select.addEventListener("change", function () { select.form.submit(); });
  });

  // Show a preview of the chosen painting photo before it is uploaded.
  document.querySelectorAll("input[type=file][data-preview]").forEach(function (input) {
    input.addEventListener("change", function () {
      var preview = document.getElementById(input.getAttribute("data-preview"));
      var file = input.files && input.files[0];
      if (!preview || !file) { return; }
      preview.src = URL.createObjectURL(file);
      preview.removeAttribute("hidden");
    });
  });

  // Artists see new buyer requests without reloading (polls this site only).
  var url = document.body.getAttribute("data-unread-url");
  var badge = document.querySelector("[data-unread-badge]");
  if (url && badge && window.fetch) {
    window.setInterval(function () {
      if (document.hidden) { return; }
      fetch(url, { credentials: "same-origin", cache: "no-store" })
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(function (data) {
          if (!data) { return; }
          badge.textContent = data.unread;
          badge.hidden = !data.unread;
        })
        .catch(function () { /* the next poll will try again */ });
    }, 30000);
  }
})();
