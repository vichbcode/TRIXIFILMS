// rating.js
document.addEventListener("DOMContentLoaded", function() {
    const interactive = document.getElementById("interactive-stars");
    const top = interactive.querySelector(".stars-top");
    const noteInput = document.getElementById("note-input");
    const prenomInput = document.getElementById("prenom");
    const submitBtn = document.getElementById("rating-submit");
    const ratingMsg = document.getElementById("rating-msg");
  
    // calcule valeur (0.5..5) en fonction du offsetX
    function computeValueFromEvent(e) {
      const rect = interactive.getBoundingClientRect();
      const x = (e.clientX || (e.touches && e.touches[0] && e.touches[0].clientX)) - rect.left;
      let ratio = x / rect.width;
      if (ratio < 0) ratio = 0;
      if (ratio > 1) ratio = 1;
      // convert to 0.5 increments
      let val = Math.round(ratio * 10) / 10; // 0..1 step 0.1
      // nearest 0.5
      val = Math.round(val * 10) / 10; // ensure
      val = Math.round(val * 10) / 10;
      val = Math.round(val * 2 * 5) / 10; // keep numeric stable (safe)
      // simpler: ratio*5 -> round to 0.5
      val = Math.round((ratio * 5) * 2) / 2;
      if (val < 0.5) val = 0.5;
      return val;
    }
  
    function updateTopWidthForValue(val) {
      const pct = (val / 5) * 100;
      top.style.width = pct + "%";
    }
  
    // preview on move
    interactive.addEventListener("mousemove", function(e) {
      const v = computeValueFromEvent(e);
      updateTopWidthForValue(v);
      interactive.setAttribute("aria-valuenow", v);
    });
  
    interactive.addEventListener("touchmove", function(e) {
      const v = computeValueFromEvent(e);
      updateTopWidthForValue(v);
      interactive.setAttribute("aria-valuenow", v);
      e.preventDefault();
    }, {passive:false});
  
    // reset preview when leaving
    interactive.addEventListener("mouseleave", function() {
      const current = noteInput.value ? parseFloat(noteInput.value) : 0;
      if (current) updateTopWidthForValue(current);
      else top.style.width = "0%";
      interactive.removeAttribute("aria-valuenow");
    });
  
    // click to set rating
    interactive.addEventListener("click", function(e) {
      const v = computeValueFromEvent(e);
      noteInput.value = v;
      updateTopWidthForValue(v);
      interactive.setAttribute("aria-valuenow", v);
      // enable submit when prenom present
      if (prenomInput.value && prenomInput.value.trim().length > 0) {
        submitBtn.disabled = false;
      }
    });
  
    // enable/disable submit based on prenom
    prenomInput.addEventListener("input", function() {
      if (prenomInput.value && prenomInput.value.trim().length > 0 && noteInput.value) {
        submitBtn.disabled = false;
      } else {
        submitBtn.disabled = true;
      }
    });
  
    // intercept form submit -> AJAX
    const form = document.getElementById("rating-form");
    form.addEventListener("submit", function(evt) {
      evt.preventDefault();
      ratingMsg.textContent = "";
      submitBtn.disabled = true;
  
      const fd = new FormData(form);
      // send with fetch, include X-Requested-With so backend retourne JSON
      fetch(form.action, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest"
        },
        body: fd,
        credentials: "same-origin"
      })
      .then(r => {
        if (!r.ok) return r.json().then(j => { throw j; });
        return r.json();
      })
      .then(data => {
        if (data && data.status === "ok") {
          // update summary
          const avgEl = document.getElementById("avg-value");
          const votesEl = document.getElementById("votes-count");
          avgEl.textContent = data.avg !== null ? data.avg : "—";
          votesEl.textContent = data.votes;
          // animate stars of summary (if exists)
          const summaryTop = document.querySelector(".rating-summary .stars-top");
          if (summaryTop) {
            summaryTop.style.width = ((data.avg || 0) / 5 * 100) + "%";
          }
          ratingMsg.textContent = data.message || "Merci !";
          ratingMsg.style.color = "green";
          // keep selected value visible
          updateTopWidthForValue(parseFloat(data.user_note));
        } else {
          ratingMsg.textContent = data.message || "Erreur.";
          ratingMsg.style.color = "crimson";
        }
      })
      .catch(err => {
        ratingMsg.textContent = (err && err.message) ? err.message : "Erreur serveur.";
        ratingMsg.style.color = "crimson";
      })
      .finally(() => {
        submitBtn.disabled = false;
      });
    });
  });
  