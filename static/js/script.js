document.addEventListener("DOMContentLoaded", function () {
  var toggle = document.getElementById("navToggle");
  var nav = document.querySelector(".site-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      nav.classList.toggle("open");
    });
    document.querySelectorAll(".site-nav a").forEach(function (link) {
      link.addEventListener("click", function () {
        nav.classList.remove("open");
      });
    });
  }

  // Reveal the contact email from a reversed string (defeats naive scrapers)
  var mailEl = document.getElementById("contact-email");
  if (mailEl && mailEl.dataset.emailRev) {
    var email = mailEl.dataset.emailRev.split("").reverse().join("");
    mailEl.href = "mailto:" + email;
    mailEl.textContent = email;
  }

  // Auto-dismiss flash messages
  document.querySelectorAll(".flash").forEach(function (el) {
    setTimeout(function () {
      el.style.transition = "opacity .4s ease";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 400);
    }, 5000);
  });

  // Skill bar animation on load
  document.querySelectorAll(".skill-bar-fill").forEach(function (el) {
    var target = el.style.width;
    el.style.width = "0";
    requestAnimationFrame(function () {
      setTimeout(function () { el.style.transition = "width .8s ease"; el.style.width = target; }, 100);
    });
  });

  // Scroll-reveal (respects reduced motion via CSS)
  var revealEls = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("revealed");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add("revealed"); });
  }

  // ---------------------------------------------------------------
  // Admin: project reordering (drag & drop + arrow buttons, auto-save)
  // ---------------------------------------------------------------
  var table = document.getElementById("projectsTable");
  if (table) {
    var body = document.getElementById("projectsBody");
    var dragRow = null;
    var savedTimer = null;

    function showToast(text) {
      var old = document.querySelector(".reorder-toast");
      if (old) old.remove();
      var toast = document.createElement("div");
      toast.className = "reorder-toast";
      toast.textContent = text;
      document.body.appendChild(toast);
      clearTimeout(savedTimer);
      savedTimer = setTimeout(function () {
        toast.classList.add("hide");
        setTimeout(function () { toast.remove(); }, 400);
      }, 1800);
    }

    function renumber() {
      Array.prototype.forEach.call(body.rows, function (row, i) {
        var num = row.querySelector(".pos-num");
        if (num) num.textContent = String(i + 1).padStart(2, "0");
      });
    }

    function saveOrder() {
      var ids = Array.prototype.map.call(body.rows, function (row) {
        return parseInt(row.dataset.id, 10);
      });
      fetch("/admin/projects/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: ids })
      }).then(function (res) {
        if (res.ok) showToast("Order saved");
        else showToast("Could not save order");
      }).catch(function () {
        showToast("Could not save order");
      });
    }

    function moveRow(row, direction) {
      if (!row) return;
      var target = direction === "up" ? row.previousElementSibling : row.nextElementSibling;
      if (!target) return;
      body.insertBefore(row, direction === "up" ? target : target.nextElementSibling);
      renumber();
      saveOrder();
    }

    body.addEventListener("click", function (e) {
      var btn = e.target.closest(".move-up, .move-down");
      if (!btn) return;
      var row = btn.closest("tr");
      moveRow(row, btn.classList.contains("move-up") ? "up" : "down");
    });

    body.addEventListener("dragstart", function (e) {
      dragRow = e.target.closest("tr");
      if (!dragRow) return;
      dragRow.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
    });

    body.addEventListener("dragend", function () {
      if (!dragRow) return;
      dragRow.classList.remove("dragging");
      dragRow = null;
      renumber();
      saveOrder();
    });

    body.addEventListener("dragover", function (e) {
      e.preventDefault();
      var target = e.target.closest("tr");
      if (!target || !dragRow || target === dragRow) return;
      var rect = target.getBoundingClientRect();
      var after = e.clientY > rect.top + rect.height / 2;
      body.insertBefore(dragRow, after ? target.nextElementSibling : target);
      renumber();
    });
  }
});