// Stand-in for Workday's scripts on the saved NVIDIA pages (tests/fixtures/workday_nvidia_*.html). None of Workday's
// code: it does what the live pages were seen doing on 2026-10-31 (headless, every non-GET blocked, nothing typed):
//   - on the posting, Apply opens "Start Your Application" (Autofill with Resume, Apply Manually, Use My Last
//     Application); its close button shuts it;
//   - Apply Manually and Autofill with Resume both lead to the sign-in choice (Google, LinkedIn, or email); Use My
//     Last Application does too, since it needs your account;
//   - Sign in with email shows Email Address and Password with Create Account below; Create Account shows the new
//     account form (Email, Password, Verify, "I agree");
//   - Sign In and Create Account never send anything here: window.__signInPresses counts them, so a test can check
//     Jobsmith never pressed one. Which start button was pressed is kept in window.name.
// Each page also has Workday's hidden "This input is for robots only" box, a honeypot.
(() => {
  const page = document.documentElement.dataset.jobsmithPage;
  const go = name => { location.href = location.href.replace(/workday_nvidia_[a-z_]+\.html/, `workday_nvidia_${name}.html`); };
  const on = (id, f) => document.querySelectorAll(`[data-automation-id="${id}"]`).forEach(e =>
    e.addEventListener("click", ev => { ev.preventDefault(); f(); }));
  const box = open => document.querySelectorAll('[data-automation-id^="wd-popup-"]').forEach(e => { e.hidden = !open; });
  window.__signInPresses = 0;
  if (page === "posting") {
    on("adventureButton", () => box(true));
    on("closeButton", () => box(false));
    // the choice is kept for the next page (window.name survives the move), so a test can see which was pressed
    ["applyManually", "autofillWithResume", "useMyLastApplication"].forEach(id => on(id, () => { window.name = id; go("signin"); }));
  }
  on("SignInWithEmailButton", () => go("signin_email"));
  on("createAccountLink", () => go("create_account"));
  on("signInLink", () => go("signin_email"));
  on("backToJobPosting", () => go("posting"));
  ["signInSubmitButton", "createAccountSubmitButton", "GoogleSignInButton", "LinkedInSignInButton"]
    .forEach(id => on(id, () => { window.__signInPresses++; }));
})();
