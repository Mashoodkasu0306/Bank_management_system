(function () {
  function byId(id) { return document.getElementById(id); }
  function show(id, on) {
    var el = byId(id);
    if (el) { el.style.display = on ? "block" : "none"; }
  }
  function checked(selector) {
    var el = document.querySelector(selector);
    return !!(el && el.checked);
  }

  // ---- Approve / Reject radio buttons: show the matching fields ----
  var RULES = {
    loan: function () {
      var ok = checked('input[name="action"][value="approve"]');
      show("loan-approve-fields", ok);
      show("loan-reject-fields", !ok);
    },
    atm: function () {
      var ok = checked('input[name="approval_status"][value="APPROVED"]');
      show("atm-rejection-fields", !ok);
    },
    cheque: function () {
      var ok = checked('input[name="approval_status"][value="APPROVED"]');
      show("cheque-approve-fields", ok);
      show("cheque-reject-fields", !ok);
    },
    kyc: function () {
      var ok = checked('input[name="verification_status"][value="VERIFIED"]');
      show("kyc-reject-fields", !ok);
    }
  };

  function runRule(name) {
    if (RULES[name]) { RULES[name](); }
  }

  // ---- Payment mode dropdowns ----
  function paymentFields(select) {
    var mode = select.value;
    show("netbanking-fields", mode === "NETBANKING");
    show("upi-fields", mode === "UPI");
    show("card-fields", mode === "CARD");
  }

  function upiFields(select) {
    var isUpi = select.value === "UPI";
    show("upi_field", isUpi);
    show("account_field", !isUpi);
    var account = byId("account_select");
    if (account) { account.required = !isUpi; }
  }

  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t || !t.matches) { return; }
    if (t.matches("[data-rule]")) { runRule(t.getAttribute("data-rule")); }
    else if (t.matches("[data-payment-toggle]")) { paymentFields(t); }
    else if (t.matches("[data-upi-toggle]")) { upiFields(t); }
  });

  // Run each rule once when the page opens, as the old inline scripts did.
  var seen = {};
  var rated = document.querySelectorAll("[data-rule]");
  for (var i = 0; i < rated.length; i++) {
    var name = rated[i].getAttribute("data-rule");
    if (!seen[name]) { seen[name] = true; runRule(name); }
  }

  // ---- "Are you sure?" popups on forms ----
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var message = form && form.getAttribute ? form.getAttribute("data-confirm") : null;
    if (message && !window.confirm(message)) { e.preventDefault(); }
  }, true);

  // ---- Retry button on the offline page ----
  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest("[data-reload]")) { window.location.reload(); }
  });

  // ---- Audit log: swap the Action list when the user type changes ----
  var mapEl = byId("action-map");
  var typeSelect = byId("user-type");
  var actionSelect = byId("action-select");
  if (mapEl && typeSelect && actionSelect) {
    var map = JSON.parse(mapEl.textContent);
    typeSelect.addEventListener("change", function () {
      var list = map[typeSelect.value] || map[""];
      var keep = actionSelect.value;
      actionSelect.innerHTML = "";

      var all = document.createElement("option");
      all.value = "";
      all.textContent = "All actions";
      actionSelect.appendChild(all);

      list.forEach(function (a) {
        var opt = document.createElement("option");
        opt.value = a;
        opt.textContent = a;
        if (a === keep) { opt.selected = true; }
        actionSelect.appendChild(opt);
      });
    });
  }
})();