/* TAO Swarm landing — micro-interactions
 *
 * Strictly local. No network. No tracking. No localStorage.
 * Honours `prefers-reduced-motion`. Every effect degrades to a
 * still page if JS is off.
 */
(function () {
  "use strict";

  var doc = document.documentElement;
  var reduce = window.matchMedia &&
               window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* 1. Scroll-progress bar */
  function setupProgress() {
    var bar = document.querySelector(".progress-bar");
    if (!bar) return;
    var update = function () {
      var st = window.pageYOffset || doc.scrollTop;
      var max = (doc.scrollHeight - window.innerHeight) || 1;
      var pct = Math.min(100, Math.max(0, (st / max) * 100));
      bar.style.width = pct + "%";
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
  }

  /* 2. Reveal-on-scroll using IntersectionObserver */
  function setupReveals() {
    var els = document.querySelectorAll(".reveal");
    if (!els.length) return;
    if (reduce || !("IntersectionObserver" in window)) {
      els.forEach(function (el) { el.classList.add("visible"); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    els.forEach(function (el) { io.observe(el); });
  }

  /* 3. Card spotlight — track mouse for radial highlight */
  function setupSpotlight() {
    if (reduce) return;
    var cards = document.querySelectorAll(".card");
    cards.forEach(function (card) {
      card.addEventListener("mousemove", function (e) {
        var r = card.getBoundingClientRect();
        var x = ((e.clientX - r.left) / r.width) * 100;
        var y = ((e.clientY - r.top) / r.height) * 100;
        card.style.setProperty("--mx", x + "%");
        card.style.setProperty("--my", y + "%");
      });
      card.addEventListener("mouseleave", function () {
        card.style.removeProperty("--mx");
        card.style.removeProperty("--my");
      });
    });
  }

  /* 4. Metric count-up — numeric-only labels animate from 0 */
  function setupCountUp() {
    if (reduce || !("IntersectionObserver" in window)) return;
    var metrics = document.querySelectorAll(".metric-value");
    var seen = new WeakSet();
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting || seen.has(entry.target)) return;
        seen.add(entry.target);
        var el = entry.target;
        var raw = (el.textContent || "").trim();
        // Only animate if the cell is a clean integer like "547" or "10".
        if (!/^\d+$/.test(raw)) return;
        var target = parseInt(raw, 10);
        if (!isFinite(target) || target <= 0) return;
        var dur = 900;
        var start = performance.now();
        var step = function (now) {
          var p = Math.min(1, (now - start) / dur);
          // ease-out-quart
          var eased = 1 - Math.pow(1 - p, 4);
          el.textContent = Math.round(target * eased).toString();
          if (p < 1) requestAnimationFrame(step);
          else el.textContent = target.toString();
        };
        requestAnimationFrame(step);
      });
    }, { threshold: 0.4 });
    metrics.forEach(function (el) { io.observe(el); });
  }

  /* 5. Legal-page language toggle (inline so legal pages don't need
   *    a separate script tag). Skip when no toggle exists.
   */
  function setupLegalLangToggle() {
    var de = document.getElementById("de-content");
    var en = document.getElementById("en-content");
    var tabDe = document.getElementById("tab-de");
    var tabEn = document.getElementById("tab-en");
    if (!de || !en || !tabDe || !tabEn) return;
    function show(lang) {
      var isDe = lang === "de";
      de.classList.toggle("active", isDe);
      en.classList.toggle("active", !isDe);
      tabDe.classList.toggle("active", isDe);
      tabEn.classList.toggle("active", !isDe);
    }
    tabDe.addEventListener("click", function (e) {
      e.preventDefault(); show("de");
      history.replaceState(null, "", "#de");
    });
    tabEn.addEventListener("click", function (e) {
      e.preventDefault(); show("en");
      history.replaceState(null, "", "#en");
    });
    if (location.hash === "#en" ||
        (navigator.language || "").slice(0, 2) === "en") {
      show("en");
    }
  }

  /* Boot */
  function boot() {
    setupProgress();
    setupReveals();
    setupSpotlight();
    setupCountUp();
    setupLegalLangToggle();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
