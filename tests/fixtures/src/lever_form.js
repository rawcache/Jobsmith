// Stand-in for Lever's own scripts on a saved application form (tests/fixtures/lever_palantir_form.html). None of
// Lever's code: it does what the live form's scripts were read to do, and seen doing, on 2026-10-30 (headless,
// every non-GET blocked):
//   - choosing a resume shows its file name in place of "ATTACH RESUME/CV";
//   - a required group of checkboxes (Languages) stays required until one is ticked;
//   - Current location is a lookup: typing shows a list after a pause, and picking one fills the box and the
//     hidden selectedLocation. Leaving the box while the list is open, without picking, empties it. The lookup's
//     answers here are the ones Lever gave for "Boston";
//   - any answer to Disability status (even "I do not want to answer") shows Name and Date below it and makes
//     them required: a signature;
//   - the cookie banner (cookieconsent, fixed along the bottom of the window, over whatever field is scrolled
//     there) closes on Deny or Accept and stores the choice in the cookieconsent_status cookie, as Lever's does;
//     window.__cookieChoice records it so a test can check which was pressed;
//   - Submit application runs an invisible hCaptcha, then clicks a hidden submit button so the browser checks
//     every required field; the form then POSTs to its own address and Lever shows "Application submitted!".
//     Here the captcha passes at once (window.__captchaChallenge = true shows a challenge frame instead, as when
//     hCaptcha asks a person), and the POST is sent with fetch so nothing navigates.
// window.__submits counts submissions, so a test can check autofill never sends one.
(() => {
  const BOSTON = [
    { name: "Boston, MA, USA", id: "2a146b7736f3b664f43da6c210ab54351b5c4ab6" },
    { name: "Boston, Lincolnshire, England, GBR", id: "e2faf2b278a798a1e7774478f2fe39ab8e688949" },
    { name: "Boston, Davao Oriental, Davao Region, PHL", id: "831b75c2959ac05a871fe5b7a37d38f4c67d4657" },
    { name: "Boston, NY, USA", id: "0022709e82fc00cdc68c57fdeeb860bd929dfa2f" },
  ];
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const show = (sel, on) => $$(sel).forEach(e => { e.style.display = on ? "flex" : "none"; });
  window.__submits = 0;

  for (const input of $$(".application-file-input")) {
    input.addEventListener("change", () => {
      const box = input.parentElement;
      const name = input.files.length ? input.files[0].name : "";
      box.querySelector(".filename").textContent = name;
      box.querySelector(".filename").style.display = name ? "" : "none";
      box.querySelector(".default-label").style.display = name ? "none" : "";
      box.classList.toggle("has-file", !!name);
    });
  }

  const groups = () => [...new Set($$(".required-field input[type=checkbox]").map(c => c.name))];
  const sync = name => {
    const group = $$(".required-field input[type=checkbox]").filter(c => c.name === name);
    const needs = !group.some(c => c.closest(".hidden")) && !group.some(c => c.checked);
    group.forEach(c => { c.required = needs; });
  };
  groups().forEach(sync);
  document.addEventListener("change", e => {
    if (e.target.matches(".required-field input[type=checkbox]")) sync(e.target.name);
  });

  const loc = $("input.location-input"), picked = $("#selected-location");
  let found, timer;
  const empty = () => { $(".dropdown-results").innerHTML = ""; show(".dropdown-no-results, .dropdown-loading-results", false); found = undefined; };
  const choose = i => {
    show(".dropdown-container", false);
    loc.value = found[i].name;
    picked.value = JSON.stringify(found[i]);
    empty();
  };
  const search = () => {
    empty();
    const q = loc.value.trim().toLowerCase();
    if (!q) return;
    found = q.length >= 2 && "boston".startsWith(q.split(",")[0].trim()) ? BOSTON : [];
    found.forEach((l, i) => $(".dropdown-results").insertAdjacentHTML("beforeend",
      `<div class="break-word dropdown-location width-full py1 px2" id="location-${i}">${l.name}</div>`));
    if (!found.length) show(".dropdown-no-results", true);
  };
  loc.addEventListener("input", () => show(".dropdown-container", true));
  loc.addEventListener("keydown", e => {
    const opts = $$(".dropdown-location"), at = opts.findIndex(o => o.classList.contains("dropdown-location-active"));
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (at >= 0) opts[at].classList.remove("dropdown-location-active");
      const next = e.key === "ArrowDown" ? (at + 1) % opts.length : (at <= 0 ? opts.length - 1 : at - 1);
      opts[next]?.classList.add("dropdown-location-active");
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (at >= 0 && found) choose(at);
    } else {
      clearTimeout(timer);
      timer = setTimeout(search, 500);
    }
  });
  loc.addEventListener("blur", () => {
    if ($(".dropdown-container").style.display !== "none" && $(".dropdown-container").style.display !== "") {
      show(".dropdown-container", false);
      empty();
      loc.value = "";
      picked.value = "";
    }
  });
  document.addEventListener("mousedown", e => {
    const o = e.target.closest(".dropdown-location");
    if (o && found) choose(+o.id.split("-")[1]);
  });

  const disability = $("#disabilitySelectElement"), signature = $("#disabilitySignatureSection");
  disability.addEventListener("change", () => {
    signature.style.display = disability.value ? "" : "none";
    signature.querySelectorAll("input").forEach(i => { i.required = !!disability.value; });
  });

  window.__cookieChoice = null;
  for (const btn of $$(".cc-window .cc-btn")) {
    btn.addEventListener("click", e => {
      e.preventDefault();
      const choice = btn.classList.contains("cc-deny") ? "deny" : "allow";
      window.__cookieChoice = choice;
      document.cookie = `cookieconsent_status=${choice}; path=/`;
      $(".cc-window").style.display = "none";
    });
  }

  const form = $("#application-form"), token = $("#hcaptchaResponseInput");
  $("#btn-submit").addEventListener("click", e => {
    e.preventDefault();
    if (window.__captchaChallenge) {
      document.body.insertAdjacentHTML("beforeend", '<iframe title="hCaptcha challenge" ' +
        'src="about:blank#https://newassets.hcaptcha.com/captcha/v1/static/hcaptcha.html#frame=challenge" ' +
        'style="position:fixed;top:20%;left:30%;width:400px;height:580px;border:1px solid #ccc;background:#fff"></iframe>');
      return;
    }
    token.value = "stand-in-token";
    $("#hcaptchaSubmitBtn").click();                 // the browser checks required fields first, as on Lever
  });
  form.addEventListener("submit", e => {
    e.preventDefault();
    if (!token.value) return;                       // Lever runs the captcha first (Enter in a text box lands here)
    window.__submits++;
    fetch(form.action || location.href, { method: "POST", body: new FormData(form) }).catch(() => {});
    document.querySelector(".application-page, .content, body").innerHTML =
      '<div class="section page-centered application-confirmation"><h3>Application submitted!</h3>' +
      "<p>Return to the main page</p></div>";
  });
})();
