// Stand-in for Ashby's own script on a saved application form (tests/fixtures/ashby_ramp_form.html). None of
// Ashby's code: it does what the live form was seen doing on 2026-10-29 (headless, every non-GET blocked except
// the two read queries in scripts/capture/capture.py):
//   - a Yes/No button sets aria-pressed="true" and the _active class on itself, clears them on the other, and
//     ticks the hidden checkbox for Yes, unticks it for No;
//   - each answer is autosaved with a POST (ApiSetFormValue), which is not a submission;
//   - Submit Application sends ApiSubmitSingleApplicationFormAction, the submission. The form then gives way to
//     Ashby's thank-you text (the words are from Ashby's own page script; the live submit was never pressed).
// window.__submits counts Submit clicks, so a test can check autofill never presses it.
(() => {
  const API = "/api/non-user-graphql";
  const post = op => fetch(`${API}?op=${op}`, { method: "POST", body: JSON.stringify({ operationName: op }) }).catch(() => {});
  window.__submits = 0;
  for (const box of document.querySelectorAll(".ashby-application-form-input-yesno")) {
    const buttons = [...box.querySelectorAll("button[data-option]")];
    const tick = box.querySelector("input[type=checkbox]");
    for (const b of buttons) {
      b.addEventListener("click", e => {
        e.preventDefault();
        for (const o of buttons) {
          const on = o === b;
          o.setAttribute("aria-pressed", String(on));
          o.classList.toggle("_active_1svni_57", on);
        }
        tick.checked = b.dataset.option === "yes";
        post("ApiSetFormValue");
      });
    }
  }
  for (const el of document.querySelectorAll(".ashby-application-form-field-entry input:not([type=checkbox]), " +
                                             ".ashby-application-form-field-entry textarea")) {
    el.addEventListener("change", () => post("ApiSetFormValue"));
  }
  document.querySelector(".ashby-application-form-submit-button").addEventListener("click", e => {
    e.preventDefault();
    window.__submits++;
    post("ApiSubmitSingleApplicationFormAction");
    const form = e.target.closest(".ashby-application-form-container") || e.target.parentElement;
    form.innerHTML = "<p>Your application was successfully submitted. We'll contact you if there are next steps.</p>";
  });
})();
