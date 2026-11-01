// Stand-in for iCIMS's scripts on the saved IDEMIA pages (tests/fixtures/icims_idemia_*.html). None of iCIMS's code:
// it does what the live pages were seen doing on 2026-10-31 (headless, every non-GET blocked, nothing typed):
//   - the careers page draws the posting in its "icims_content_iframe" frame;
//   - in that frame, "Apply for this job online" shows "Enter Your Information" (Email, Next) in the same frame;
//   - "Returning Candidate? Log back in!" opens iCIMS's login (login.icims.com) in place of the whole page;
//   - Next and every Continue on the login never send anything here: window.__signInPresses (in the frame or page
//     the button is on) counts them, so a test can check Jobsmith never pressed one.
(() => {
  const page = document.documentElement.dataset.jobsmithPage;
  const here = name => location.href.replace(/icims_idemia_[a-z_]+\.html/, `icims_idemia_${name}.html`);
  window.__signInPresses = 0;
  const press = ev => { ev.preventDefault(); window.__signInPresses++; };
  if (page === "posting") {
    document.querySelectorAll("a.iCIMS_ApplyOnlineButton").forEach(a => a.addEventListener("click", ev => {
      ev.preventDefault(); location.href = here("email_frame");
    }));
    [...document.querySelectorAll("a")].filter(a => /log back in/i.test(a.textContent)).forEach(a =>
      a.addEventListener("click", ev => { ev.preventDefault(); window.top.location.href = here("login"); }));
  }
  if (page === "email") {
    document.querySelectorAll("form").forEach(f => f.addEventListener("submit", press));
    document.querySelectorAll("#enterEmailSubmitButton").forEach(b => b.addEventListener("click", press));
  }
  if (page === "login") {
    document.querySelectorAll("form").forEach(f => f.addEventListener("submit", press));
  }
})();
