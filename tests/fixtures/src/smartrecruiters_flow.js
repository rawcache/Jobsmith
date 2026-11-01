// Stand-in for SmartRecruiters' scripts on the saved Bosch form (tests/fixtures/smartrecruiters_bosch_form.html). None
// of SmartRecruiters' code. The page's own markup holds the phone's country-code list (245 countries, United States
// picked, as saved); this adds only what its scripts did:
//   - the country-code button opens and closes that list, and picking a country marks it picked and shows its code
//     on the button;
//   - City suggests places as you type, in its own list (role="option" in menu-…, as saved but empty), from a short
//     list of ours; picking one puts it in the box;
//   - the footer's Next (data-test="footer-next") sends nothing: window.__nextPresses counts it.
(() => {
  if (document.documentElement.dataset.jobsmithPage !== "smartrecruiters") return;
  // every shadow root on the page, the page first
  const roots = [document];
  for (let i = 0; i < roots.length; i++)
    for (const e of roots[i].querySelectorAll("*")) if (e.shadowRoot) roots.push(e.shadowRoot);
  const all = sel => roots.flatMap(r => [...r.querySelectorAll(sel)]);

  const button = all('button[aria-label="Country code"]')[0];
  const menu = button && all(`#${CSS.escape(button.getAttribute("aria-controls"))}`)[0];
  const options = all("spl-select-option");
  const shown = open => { if (menu) menu.hidden = !open; if (button) button.setAttribute("aria-expanded", String(open)); };
  if (button) {
    shown(false);
    button.addEventListener("click", e => { e.preventDefault(); shown(menu.hidden); });
    const show = o => {
      const code = (o.textContent.match(/\+\s*\d+/) || [""])[0].replace(/\s/g, "");
      button.dataset.picked = o.getAttribute("value");
      let label = button.querySelector("[data-jobsmith-code]");
      if (!label) { label = document.createElement("span"); label.dataset.jobsmithCode = ""; button.prepend(label); }
      label.textContent = `${o.getAttribute("label")} ${code}`;
    };
    options.forEach(o => o.addEventListener("click", e => {
      e.preventDefault();
      options.forEach(x => x.shadowRoot?.querySelector("spl-dropdown-item")?.removeAttribute("selected"));
      o.shadowRoot?.querySelector("spl-dropdown-item")?.setAttribute("selected", "");
      show(o); shown(false);
    }));
    const picked = options.find(o => o.shadowRoot?.querySelector("spl-dropdown-item[selected]"));
    if (picked) show(picked);
  }
  const PLACES = ["Boston, MA, USA", "Boston, Lincolnshire, UK", "Bossier City, LA, USA", "Plymouth, MI, USA"];
  const city = all('input[data-sr-id="location-autocomplete-search-search-input"]')[0];
  const list = city && all(`#${CSS.escape(city.getAttribute("aria-controls"))}`)[0];
  if (city && list) city.addEventListener("input", () => {
    const q = city.value.trim().toLowerCase().split(",")[0];
    list.innerHTML = "";
    if (!q) return;
    PLACES.filter(p => p.toLowerCase().startsWith(q)).forEach(p => {
      const o = document.createElement("div");
      o.setAttribute("role", "option"); o.textContent = p;
      o.addEventListener("click", () => { city.value = p; list.innerHTML = ""; city.dispatchEvent(new Event("change", { bubbles: true })); });
      list.appendChild(o);
    });
  });
  window.__nextPresses = 0;
  all('[data-test="footer-next"] button, [data-test="footer-next"]').forEach(b =>
    b.addEventListener("click", e => { e.preventDefault(); e.stopPropagation(); window.__nextPresses++; }, true));
})();
