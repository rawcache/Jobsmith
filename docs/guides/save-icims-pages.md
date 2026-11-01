# Saving iCIMS's signed-in pages for test fixtures

For maintainers. About 20 minutes, once.

Jobsmith already has iCIMS's public pages, saved read-only from IDEMIA's "Full Stack Software Engineering
Internship" posting: the posting, "Enter Your Information" (Email, then Next) and iCIMS's login
(`tests/fixtures/icims_idemia_*.html`). Next finds your account or starts a new one, and signing in or making an
account is always yours (Jobsmith never types a password or creates an account). So the application pages behind it
are saved from your own Chrome. Phase 1 item 7e waits on this.

## Before you start

- Use Chrome on your own computer. iCIMS accounts are per company: an IDEMIA one is fine, or any company's iCIMS
  posting (`<something>.icims.com/jobs/…`). Pick one internship and note its address.
- Don't use "Apply with LinkedIn", Indeed or a resume parse if offered; enter details by hand.
- iCIMS won't let you leave a page until its required fields are filled, and it keeps your profile in your account.
  So fill them with **made-up details only**: Alex Rivera, `alex.rivera@example.edu`, phone `617-555-0123`, address
  `1 Example Street, Boston, MA 02115`, and "I don't wish to answer" (or the closest) for every voluntary or
  self-identification question. Nothing true about you goes in. Afterwards you can withdraw the application draft
  and delete the profile from the candidate portal.
- **Never press Submit.** Stop at the last page before it.

## Saving a page

iCIMS draws the application in a frame of the company's careers page, so the snippet has to run in that frame. Save
every page **as soon as it opens, before you type anything on it**, so it's saved blank. On each one:

1. Scroll to the bottom once, and open each dropdown once (then press Escape) so its options load. Don't pick anything.
2. Open the Console (View > Developer > JavaScript Console). In the box at the top of the Console that says **top**,
   choose **icims_content_iframe** (if the page has no such frame, leave it on top). Paste this and press Enter:

   ```js
   (() => {
     const roots = [];
     const walk = n => n.querySelectorAll("*").forEach(e => { if (e.shadowRoot) { roots.push(e.shadowRoot); walk(e.shadowRoot); } });
     walk(document);
     const html = "<!doctype html>\n<html>" + document.documentElement.getHTML({ shadowRoots: roots }) + "</html>";
     copy(html.replace(/<script\b[\s\S]*?<\/script>/gi, ""));
     return `copied ${html.length} characters from ${location.href.split("?")[0]}`;
   })()
   ```

3. Paste it into a new file **outside the Jobsmith folder**, numbered in order, for example
   `~/Desktop/jobsmith-pages/icims/1-contact-information.html`. Never put these in the repo yourself.
4. Take a full-page screenshot next to it (in DevTools: Cmd/Ctrl+Shift+P, then "Capture full size screenshot").
5. Now fill the page's required fields with the made-up details above, and press **Next** (or Save and Continue).

Pages differ by company. Usually: contact information, resume or profile, work history and education, the company's
questions (work authorization, sponsorship), voluntary disclosures (gender, ethnicity, veteran status), disability
self-identification, an e-signature, then a review page. An e-signature page is yours: save it blank and type Alex
Rivera only if it won't continue without one. If a page shows an error after Next, save it again with the error
showing (`multistep.page_errors` reads them).

## Then

Tell Claude Code where the folder is and which posting it was. It builds the fixtures the way the public iCIMS pages
were built (`tests/fixtures/src/icims_fixture.py`): nothing loaded from the network, account, customer and tracking
ids and keys blanked, every made-up detail checked to be Alex Rivera's, and it refuses any page with another email
address or phone number in it. You can check the files too: they are plain HTML.

## If something stops you

A CAPTCHA, an emailed code or a bot check: do it yourself if it's an ordinary sign-in step, or stop and say so.
Don't look for a way round one.
