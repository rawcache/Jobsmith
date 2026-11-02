// Stand-in for iCIMS's scripts on the saved IDEMIA pages (tests/fixtures/icims_idemia_*.html). None of iCIMS's code:
// it does what the live pages were seen doing on 2026-10-31 (headless, every non-GET blocked, nothing typed):
//   - the careers page draws the posting in its "icims_content_iframe" frame;
//   - in that frame, "Apply for this job online" shows "Enter Your Information" (Email, Next) in the same frame;
//   - "Returning Candidate? Log back in!" opens iCIMS's login (login.icims.com) in place of the whole page;
//   - Next and every Continue on the login never send anything here: window.__signInPresses (in the frame or page
//     the button is on) counts them, so a test can check Jobsmith never pressed one.
// Signed in, the Candidate Profile (step 1 of 5, saved from the maintainer's Chrome on 2026-11-01, Simplify off):
//   - iCIMS's search dropdowns: the <select> is hidden and a link shows the choice; clicking it opens a list, and
//     picking from it fills the <select> (iCIMS loads the values as you pick; here a choice's value is its words).
//     Picking a country fills its State list from a short list of ours (the saved one was empty);
//   - a resume chosen shows "Parsing resume, please wait..." a moment later, then what was read replaces the form's
//     boxes (iCIMS's page says so); here nothing is read, so they're drawn again empty. window.__resumeRead counts it;
//   - Submit Profile makes the account from the Login and Password typed here: it never sends anything, and
//     window.__signInPresses counts it.
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
  if (page === "profile") {
    // the page's own inline handlers call iCIMS's functions (its scripts aren't kept): they do nothing here
    window.icimsChangeParent = () => {};
    window.icimsDisableSaveAndSubmitButtons = () => {};
    // iCIMS's stylesheet isn't kept: the rules its widgets need to hide what they hide
    const css = document.createElement("style");
    css.textContent = ".dropdown-hide, .dropdown-invisible, .iCIMS_NoDisplay { display: none !important; }" +
      ".dropdown-container { position: relative; z-index: 5; background: #fff; } .dropdown-results { overflow-y: auto; }";
    document.head.appendChild(css);
    // iCIMS's search dropdown: the <select> is hidden; its link shows the choice and opens a list (li[role=option],
    // the choice's words in its title). Picking one puts it in the <select> (the saved page has no values for them:
    // iCIMS loads those as you pick, so here each choice's value is its own words) and closes the list
    const STATES = ["Massachusetts", "Michigan", "Minnesota", "New York"];       // ours: the saved list was empty
    const pickIn = (select, title) => {
      [...select.options].forEach(o => { if (o.value) o.remove(); });
      if (title) select.add(new Option(title, title, true, true));
      select.value = title || "";
      const shown = document.getElementById(`${select.id}_fakeSelected_icimsDropdown`);
      if (shown) shown.innerHTML = title ? "" : '<span class="dropdown-placeholder">— Make a Selection —</span>';
      if (shown && title) shown.textContent = title;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    };
    const listOf = select => document.getElementById(`${select.id}_dropdown-results`);
    const wire = (select, li) => li.addEventListener("click", ev => {
      ev.preventDefault();
      pickIn(select, li.getAttribute("dropdown-index") === "-1" ? "" : li.getAttribute("title"));
      document.getElementById(`${select.id}_icimsDropdown_ctnr`).classList.add("dropdown-invisible");
      const child = select.dataset.dddChildLink && document.querySelector(`select[id$="_${select.dataset.dddChildLink}"]`);
      if (child && listOf(child)) {                      // the country's states, in the state's list
        pickIn(child, "");
        const ul = listOf(child);
        ul.innerHTML = "";
        (select.value === "United States" ? STATES : []).forEach((s, i) => {
          const o = document.createElement("li");
          Object.assign(o, { id: `result-selectable_${child.id}_${i}`, className: "dropdown-result result-selectable",
                             title: s, textContent: s });
          o.setAttribute("role", "option"); o.setAttribute("dropdown-index", String(i));
          ul.appendChild(o); wire(child, o);
        });
      }
    });
    document.querySelectorAll("select.dropdown-hide").forEach(select => {
      const link = document.getElementById(`${select.id}_icimsDropdown`);
      const box = document.getElementById(`${select.id}_icimsDropdown_ctnr`);
      if (!link || !box) return;
      link.addEventListener("click", ev => { ev.preventDefault(); box.classList.toggle("dropdown-invisible"); });
      listOf(select)?.querySelectorAll("li[role=option]").forEach(li => wire(select, li));
    });
    // A resume chosen is read by iCIMS ("Parsing resume, please wait..."), and what it reads replaces what's in the
    // form (the page says so). Here the notice comes a moment after the file is chosen, the read takes a moment more
    // and finds nothing, and the boxes are drawn again, empty: new boxes, as iCIMS draws them, not the ones that
    // were there. window.__parseDelay and window.__parseTime (ms) let a test make either longer
    const resume = document.getElementById("PortalProfileFields.Resume_File");
    const busy = document.getElementById("PortalProfileFields.Resume_Loading");
    const boxes = '#profileForm input[type="text"], #profileForm input[type="email"]';
    const drawn = new Map([...document.querySelectorAll(boxes)].map(i => [i.id, i.outerHTML]));
    resume?.addEventListener("change", () => setTimeout(() => {
      busy.classList.remove("iCIMS_NoDisplay");
      setTimeout(() => {
        document.querySelectorAll(boxes).forEach(i => {
          if (/Login/.test(i.id) || !drawn.has(i.id)) return;
          const t = document.createElement("template");
          t.innerHTML = drawn.get(i.id);
          const fresh = t.content.firstElementChild;
          fresh.value = "";
          i.replaceWith(fresh);
        });
        busy.classList.add("iCIMS_NoDisplay");
        window.__resumeRead = (window.__resumeRead || 0) + 1;
      }, window.__parseTime ?? 1500);
    }, window.__parseDelay ?? 600));
    // Submit Profile makes the account with the login and password typed here: never sent from here, counted
    document.querySelectorAll("#profileForm").forEach(f => f.addEventListener("submit", press));
    document.querySelectorAll("#cp_form_submit_i").forEach(b => b.addEventListener("click", press));
  }
})();
