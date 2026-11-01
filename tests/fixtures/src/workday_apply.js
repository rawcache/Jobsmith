// Stand-in for Workday's scripts on the saved NVIDIA application pages, signed in (tests/fixtures/
// workday_nvidia_my_information.html … _review.html). None of Workday's code, and none of its lists: the pages were
// saved with every list closed, so the choices below are ours, a few per box, enough for Alex Rivera's answers and a
// wrong one beside each. What it does:
//   - a dropdown (<button aria-haspopup="listbox">) opens a list of choices (role="option") under it; picking one
//     shows it on the button, as Workday does;
//   - a search box (Workday's multiSelectContainer: How Did You Hear About Us?, Country Phone Code, Field of Study,
//     Skills) shows the choices that match what's typed once Enter is pressed, in a list Workday calls
//     activeListContainer; picking one adds it as a pill (selectedItem), as on the saved pages;
//   - Save and Continue moves to the next page, Back to the one before, after keeping what this page holds in
//     window.name, so a test can read every page once the run reaches Review;
//   - Submit, on Review, sends nothing: window.__submitPresses counts it.
(() => {
  const page = document.documentElement.dataset.jobsmithPage;
  const ORDER = ["my_information", "my_experience", "application_questions", "voluntary_disclosures", "review"];
  if (!ORDER.includes(page)) return;
  const LISTS = {
    country: ["Canada", "United Kingdom", "United States of America"],
    countryRegion: ["California", "Massachusetts", "New York", "Texas"],
    phoneType: ["Home", "Mobile", "Work"],
    degree: ["Associate's Degree", "Bachelor's Degree", "Master's Degree", "Doctorate"],
    ethnicity: ["Asian (United States of America)", "Black or African American (United States of America)",
                "White (United States of America)", "I do not wish to answer. (United States of America)"],
    gender: ["Woman", "Man", "I do not wish to answer."],
    veteranStatus: ["I am not a protected veteran", "I identify as one or more of the classifications of protected veteran",
                    "I do not wish to self-identify"],
  };
  const QUESTIONS = ["Yes", "No"];                   // the two application questions
  const PROMPTS = {
    source: ["Career Fair", "Company Website", "Glassdoor", "Indeed", "LinkedIn", "Referral"],
    countryPhoneCode: ["Canada (+1)", "United Kingdom (+44)", "United States of America (+1)"],
    fieldOfStudy: ["Computer Engineering", "Computer Science", "Electrical Engineering", "Mechanical Engineering"],
    skills: ["C", "C++", "Docker", "OpenCV", "Python", "PyTorch", "SQL"],
  };
  const keyOf = id => (id || "").split("--").pop();
  const closeLists = () => document.querySelectorAll("[data-jobsmith-list]").forEach(e => e.remove());

  const state = (() => { try { return JSON.parse(window.name || "{}"); } catch (_) { return {}; } })();
  window.__submitPresses = 0;

  // dropdowns
  document.querySelectorAll('button[aria-haspopup="listbox"]').forEach(btn => {
    const choices = LISTS[keyOf(btn.id)] || QUESTIONS;
    btn.addEventListener("click", ev => {
      ev.preventDefault(); closeLists();
      const ul = document.createElement("ul");
      ul.setAttribute("role", "listbox"); ul.dataset.jobsmithList = "";
      ul.style.cssText = "position:relative;z-index:10;background:#fff;border:1px solid #ccc;list-style:none;margin:0;padding:4px";
      choices.forEach(text => {
        const li = document.createElement("li");
        li.setAttribute("role", "option"); li.innerHTML = `<div>${text}</div>`; li.style.padding = "4px";
        li.addEventListener("click", e => {
          e.preventDefault();
          btn.textContent = text;
          btn.setAttribute("aria-label", btn.getAttribute("aria-label").replace(/Select One|$/, text).replace(/\s+/g, " "));
          btn.value = text; closeLists();
        });
        ul.appendChild(li);
      });
      btn.parentElement.after(ul);
    });
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeLists(); });

  // search boxes with pills
  document.querySelectorAll('[data-automation-id="multiSelectContainer"] input').forEach(input => {
    const box = input.closest('[data-automation-id="multiSelectContainer"]');
    const key = keyOf(input.id);
    const choices = PROMPTS[key] || [];
    const show = () => {
      closeLists();
      const q = input.value.trim().toLowerCase();
      const list = document.createElement("div");
      list.dataset.automationId = "activeListContainer"; list.dataset.jobsmithList = "";
      list.setAttribute("role", "listbox");
      list.style.cssText = "position:relative;z-index:10;background:#fff;border:1px solid #ccc;padding:4px";
      const hits = choices.filter(c => !q || c.toLowerCase().includes(q));
      if (!hits.length) list.innerHTML = '<p data-automation-id="promptNoResults">No Items.</p>';
      hits.forEach(text => {
        const opt = document.createElement("div");
        opt.setAttribute("role", "option");
        opt.innerHTML = `<p data-automation-id="promptOption" data-automation-label="${text}">${text}</p>`;
        opt.addEventListener("click", e => {
          e.preventDefault();
          let ul = box.querySelector('[data-automation-id="selectedItemList"]');
          if (!ul) {                                         // Workday draws the list once something is picked
            ul = document.createElement("ul");
            ul.setAttribute("role", "listbox"); ul.dataset.automationId = "selectedItemList";
            ul.setAttribute("aria-label", "items selected");
            box.querySelector('[data-automation-id="multiselectInputContainer"]').appendChild(ul);
          }
          if (key !== "skills") ul.innerHTML = "";                // one pick, except Skills
          const li = document.createElement("li");
          li.setAttribute("role", "presentation"); li.dataset.automationId = "menuItem";
          li.innerHTML = `<div role="option" data-automation-id="selectedItem" aria-label="${text}, press delete to clear value."><p data-automation-id="promptOption" data-automation-label="${text}">${text}</p></div>`;
          ul.appendChild(li);
          input.value = ""; closeLists();
        });
        list.appendChild(opt);
      });
      box.after(list);
    };
    input.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); show(); } });
    input.addEventListener("click", () => show());
  });

  // what this page holds, kept for the test before moving on
  const held = () => {
    const out = {};
    document.querySelectorAll("input, button[aria-haspopup='listbox']").forEach(el => {
      const id = el.id || el.name || el.dataset.automationId; if (!id) return;
      if (el.tagName === "BUTTON") out[id] = el.textContent.trim() === "Select One" ? "" : el.textContent.trim();
      else if (el.type === "checkbox" || el.type === "radio") { if (el.checked) out[el.name || id] = el.type === "radio" ? (document.querySelector(`label[for="${el.id}"]`)?.innerText || el.value) : "checked"; }
      else if (el.type === "file") out[id] = [...(el.files || [])].map(f => f.name).join(", ");
      else if (!el.closest('[data-automation-id="multiSelectContainer"]')) out[id] = el.value;
    });
    document.querySelectorAll('[data-automation-id="multiSelectContainer"]').forEach(box => {
      const input = box.querySelector("input");
      out[input.id] = [...box.querySelectorAll('[data-automation-id="selectedItem"] [data-automation-id="promptOption"]')].map(p => p.textContent).join(", ");
    });
    return out;
  };
  const go = step => {
    state[page] = held();
    window.name = JSON.stringify(state);
    location.href = location.href.replace(/workday_nvidia_[a-z_]+\.html/, `workday_nvidia_${ORDER[ORDER.indexOf(page) + step]}.html`);
  };
  const on = (id, f) => document.querySelectorAll(`[data-automation-id="${id}"]`).forEach(e =>
    e.addEventListener("click", ev => { ev.preventDefault(); f(); }));
  if (page === "review") on("pageFooterNextButton", () => { window.__submitPresses++; });
  else on("pageFooterNextButton", () => go(1));
  on("pageFooterBackButton", () => go(-1));
})();
