// Brings the saved Figma form's dropdowns to life for tests: real react-select (MIT), set up the way Greenhouse's
// job-boards form sets it up. Built into tests/fixtures/greenhouse_figma_live.html (see README.md here).
//
// What matters, as seen on the live form (2026-10-28, headless, GET requests only):
// - Greenhouse controls the menu itself (`menuIsOpen`). react-select asking to open it (a key-down, a mouse-down)
//   does nothing; Greenhouse opens it on key-up and mouse-up. A script that sends only key-down, mouse-down or
//   .click() never sees a menu, which is why the extension left these boxes under "Needs you" (#19).
// - Location (City) has no fixed options: typing calls Greenhouse's place lookup, and the menu shows its results
//   ("Boston, Massachusetts, United States", ...).
// - Each box has react-select's hidden "required" input until something is picked.
import React, { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import Select, { components } from "react-select";

const opts = labels => labels.map(l => ({ label: l, value: l }));

// The first few of the live form's 244, in its order, and the places its lookup returned for "Boston".
const COUNTRIES = [["United States +1", "us"], ["Afghanistan +93", "af"], ["Åland Islands +358", "ax"],
  ["Canada +1", "ca"], ["India +91", "in"], ["United Kingdom +44", "gb"]].map(([label, value]) => ({ label, value }));
const PLACES = ["Boston, Massachusetts, United States", "Boston District, England, United Kingdom",
  "Boston, England, United Kingdom", "East Boston, Massachusetts, United States", "Bostonia, California, United States",
  "Boston, Davao Oriental, Philippines", "Atlanta, Georgia, United States", "New York, New York, United States"];
const YES_NO = opts(["Yes", "No"]);

// react-select has no onKeyUp/onMouseUp of its own; Greenhouse passes them with its own components, like this.
const Container = props => (
  <components.SelectContainer {...props}
    innerProps={{ ...props.innerProps, onKeyUp: props.selectProps.onKeyUp, onMouseUp: props.selectProps.onMouseUp }} />
);

function GreenhouseSelect({ id, options, lookup }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(null);
  const [input, setInput] = useState("");
  const [found, setFound] = useState(options || []);
  const [loading, setLoading] = useState(false);
  const latest = useRef("");
  window.__lookups = window.__lookups || [];

  const search = q => {
    latest.current = q;
    if (q.trim().length < 2) { setFound([]); return; }
    setLoading(true);
    window.__lookups.push(q);
    setTimeout(() => {                       // the lookup answers after a moment; only the latest one counts
      if (latest.current !== q) return;
      setFound(opts(PLACES.filter(p => p.toLowerCase().includes(q.trim().toLowerCase()))));
      setLoading(false);
    }, 700);
  };

  return (
    <Select
      inputId={id} instanceId={id} className="select-shell" classNamePrefix="select" required
      aria-labelledby={`${id}-label`} placeholder="" isClearable={false}
      components={{ SelectContainer: Container }}
      options={found} isLoading={loading} filterOption={lookup ? null : undefined}
      value={value} inputValue={input} menuIsOpen={open}
      onMenuOpen={() => {}}                  // react-select's own request to open is ignored, as on the live form
      onMenuClose={() => setOpen(false)}
      onKeyUp={e => { if (e.key !== "Escape" && e.key !== "Tab") setOpen(true); }}
      onMouseUp={e => { if (!e.target.closest(".select__menu")) setOpen(o => !o); }}
      onInputChange={(v, meta) => {
        if (meta.action === "input-change") { setInput(v); if (lookup) search(v); }
        else if (meta.action === "menu-close" || meta.action === "input-blur") setInput("");
      }}
      onChange={v => { setValue(v); setInput(""); setOpen(false); }}
    />
  );
}

// Replace each saved (dead) box with a live one, keeping its label and place on the page.
const FIELDS = [["country", { options: COUNTRIES }], ["candidate-location", { lookup: true }],
  ["question_12497125004", { options: YES_NO }], ["question_12497126004", { options: YES_NO }]];
for (const [id, props] of FIELDS) {
  const shell = document.getElementById(id)?.closest(".select-shell");
  if (!shell) continue;
  const mount = document.createElement("div");
  shell.replaceWith(mount);
  createRoot(mount).render(<GreenhouseSelect id={id} {...props} />);
}
