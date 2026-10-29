# Sources for built fixtures

## `greenhouse_select.jsx` → `../greenhouse_figma_live.html`

`greenhouse_board_posting.html` is the saved Figma application form (Greenhouse job-boards, blank). It has no
scripts, so its dropdowns can't open. `greenhouse_figma_live.html` is the same page with a script at the end. The
script replaces Country, Location (City) and two Yes/No boxes with real react-select (MIT), set up the way the live
form sets it up:

- Greenhouse controls the menu. It opens on key-up and mouse-up, not on react-select's own key-down or mouse-down.
- Location (City) searches a place lookup as you type. The lookup's answers here are the ones the live form gave for
  "Boston".
- Each box has react-select's hidden "required" input until something is picked.

That behaviour was observed on the live form on 2026-10-28, headless, with every non-GET request blocked. The script
contains none of Greenhouse's code.

To rebuild after changing the source:

```bash
mkdir -p /tmp/gh-select && cp tests/fixtures/src/greenhouse_select.jsx /tmp/gh-select/ && cd /tmp/gh-select
npm init -y >/dev/null && npm install react@18.3.1 react-dom@18.3.1 react-select@5.8.0 esbuild@0.21.5
npx esbuild greenhouse_select.jsx --bundle --minify --format=iife --jsx=automatic \
  --define:process.env.NODE_ENV='"production"' --legal-comments=eof --outfile=bundle.js
cd - && python3 -c "
html = open('tests/fixtures/greenhouse_board_posting.html').read(); js = open('/tmp/gh-select/bundle.js').read()
open('tests/fixtures/greenhouse_figma_live.html', 'w').write(html.replace('</body>', '<script>' + js + '</script></body>', 1))"
```

## `ashby_form.js` + `ashby_fixture.py` → `../ashby_ramp_form.html`

`ashby_ramp_form.html` is Ramp's application form for "Software Engineer, Frontend" on Ashby
(`jobs.ashbyhq.com/ramp/4e64ab86-4e30-403b-b1b9-41dc052570ce/application`), saved blank on 2026-10-29. Ashby builds
the form in the browser from two GraphQL reads, so it was saved with `scripts/capture/capture.py`, which lets
those two reads through and blocks every other non-GET (see the rule in `docs/PHASE1.md`). The capture has Ashby's
scripts removed; `ashby_fixture.py` inlines Ashby's stylesheet (so the hidden Yes/No checkboxes stay hidden),
drops everything that would load from the network, adds `ashby_form.js`, and refuses to write a page with an email
address or phone number in it other than Ashby's placeholders.

`ashby_form.js` is our stand-in for Ashby's script, none of Ashby's code. It does what the live form was seen
doing: a Yes/No button sets `aria-pressed` and ticks the hidden checkbox for Yes; each answer is autosaved with a
POST (`ApiSetFormValue`, not a submission); Submit Application sends `ApiSubmitSingleApplicationFormAction` and
the form gives way to Ashby's thank-you text (taken from Ashby's page script; the live Submit was never pressed).

To rebuild (the stylesheet is the `<link rel=stylesheet>` on the live page, saved with a plain GET):

```bash
uv run python scripts/capture/capture.py \
  https://jobs.ashbyhq.com/ramp/4e64ab86-4e30-403b-b1b9-41dc052570ce/application /tmp/ashby/captured.html
curl -s -o /tmp/ashby/ashby.css "<the page's stylesheet URL>"
uv run python tests/fixtures/src/ashby_fixture.py /tmp/ashby/captured.html /tmp/ashby/ashby.css \
  tests/fixtures/ashby_ramp_form.html
```

Check the result has no real person's details in it (the builder only catches emails and phone numbers).
