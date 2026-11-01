# Saving a SmartRecruiters form for a test fixture

For maintainers. About five minutes, once.

Jobsmith's read-only capture can't see a SmartRecruiters application form. When a headless browser that sends nothing
opens one, SmartRecruiters shows DataDome's bot check ("Access is temporarily restricted") instead. Getting past that
check means letting its own requests through, and Jobsmith never tries to get past a bot check or a CAPTCHA. So the
form is saved from your own Chrome, where an ordinary visit is let in. Phase 1 item 7c waits on this.

## What you need

- Chrome (any recent version) on your own computer. You don't need to be signed in to anything.
- The posting Jobsmith uses for its tests: Bosch's "Quality Engineering Intern / Co-op - Spring 2027"
  (`https://jobs.smartrecruiters.com/BoschGroup/744000158818709-quality-engineering-intern-co-op-spring-2027`).
  If it's been taken down, any US internship on SmartRecruiters will do. Note which one. (It closed; the saved
  fixture is Bosch's "Application Engineer", 2026-10-31.)

## Steps

1. Open the posting and click **I'm interested**. The application form opens
   (`jobs.smartrecruiters.com/oneclick-ui/company/…/publication/…`).
2. **Don't type anything into the form, and don't use "Apply with LinkedIn", Indeed or a resume upload.** The saved
   page must hold no one's details. If a cookie banner shows, press its reject or "necessary only" button.
3. Scroll to the bottom once so every section loads, and open any dropdown once (then press Escape). Don't pick
   anything.
4. Open the Console (View > Developer > JavaScript Console), paste this and press Enter. It copies the form, including
   the parts drawn inside SmartRecruiters' components (a plain "Save Page As" leaves those out), with scripts removed:

   ```js
   (() => {
     const roots = [];
     const walk = n => n.querySelectorAll("*").forEach(e => { if (e.shadowRoot) { roots.push(e.shadowRoot); walk(e.shadowRoot); } });
     walk(document);
     const html = "<!doctype html>\n<html>" + document.documentElement.getHTML({ shadowRoots: roots }) + "</html>";
     copy(html.replace(/<script\b[\s\S]*?<\/script>/gi, ""));
     return `copied ${html.length} characters, ${roots.length} component parts`;
   })()
   ```

5. Paste it into a new file **outside the Jobsmith folder**, for example `~/Desktop/jobsmith-pages/smartrecruiters.html`.
   Never put it in the repo yourself: the raw page can hold tracking ids, and it's sanitized first.
6. Take a full-page screenshot (Cmd/Ctrl+Shift+P in DevTools, then "Capture full size screenshot") and save it next to
   it. It shows how the form should look, so the fixture can be checked against it.
7. Close the tab without pressing Submit.

Then tell Claude Code where the files are. It builds `tests/fixtures/smartrecruiters_bosch_form.html` from them the way
the Lever and Ashby fixtures are built (`tests/fixtures/src/`): only the rules the page uses, nothing loaded from the
network, tracking and account ids blanked, made-up Alex Rivera only. It also writes a stand-in for SmartRecruiters'
scripts from what the page does, then the adapter and its tests.

## If you can't get to the form either

If your own Chrome also gets "Access is temporarily restricted", don't retry and don't change networks to get round
it. Say so, and 7c stays open. Autopilot already treats that page as a stop: it holds the application under "Needs
you" with the line the site showed and doesn't try again (`tests/test_bot_walls.py`).
