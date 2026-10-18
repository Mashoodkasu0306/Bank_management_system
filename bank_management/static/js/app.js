(function () {
  var body = document.body;
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-nav-toggle]")) { body.classList.toggle("nav-open"); }
    else if (e.target.closest("[data-nav-close]")) { body.classList.remove("nav-open"); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { body.classList.remove("nav-open"); }
  });
})();
(function () {
  document.addEventListener("click", function (e) {
    var link = e.target.closest("[data-back]");
    if (!link) { return; }
    var cameFromHere = document.referrer && document.referrer.indexOf(window.location.origin) === 0;
    if (window.history.length > 1 && cameFromHere) {
      e.preventDefault();
      window.history.back();
    }
  });
})();
(function () {
  if (!("serviceWorker" in navigator)) { return; }
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
  });
})();

(function () {
  var deferred = null;
  var btn = document.getElementById("install-app");
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    if (btn) { btn.hidden = false; }
  });
  if (btn) {
    btn.addEventListener("click", function () {
      if (!deferred) { return; }
      deferred.prompt();
      deferred.userChoice.then(function () { deferred = null; btn.hidden = true; });
    });
  }
  window.addEventListener("appinstalled", function () { if (btn) { btn.hidden = true; } });
})();