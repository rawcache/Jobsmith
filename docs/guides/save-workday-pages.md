# Saving Workday's signed-in pages for test fixtures

For maintainers. About 20 minutes, once.

Jobsmith already has Workday's public pages, saved read-only from NVIDIA's "AI Systems Software Engineering Intern –
Summer 2027" posting: the posting, "Start Your Application", the sign-in choice, sign-in by email and Create Account
(`tests/fixtures/workday_nvidia_*.html`). Everything after sign-in needs an account, and signing in or making an account
is always yours (Jobsmith never types a password or creates an account). So the pages behind sign-in are saved from
your own Chrome. Phase 1 item 7d waits on this.

## Before you start

- Use Chrome on your own computer, and your own Workday account on any company's site (NVIDIA's is fine). Workday
  accounts are per company, so if you make one for this it's for that company only.
- Pick one internship posting and note its address. Use **Apply Manually**, not "Autofill with Resume" (that uploads
  your resume) or "Use My Last Application".
- Workday won't let you leave a page until its required fields are filled, and it keeps a draft in your account. So
  fill them with **made-up details only**: Alex Rivera, `alex.rivera@example.edu`, phone `617-555-0123`, address
  `1 Example Street, Boston, MA 02115`, and "I don't wish to answer" (or the closest) for every voluntary or
  self-identification question. Nothing true about you goes in. Afterwards you can delete the draft under
  **Candidate Home**.
- **Never press Submit.** The last page is Review; stop there.

## Saving a page

Save every page **as soon as it opens, before you type anything on it**, so it's saved blank. On each one:

1. Scroll to the bottom once, and open each dropdown once (then press Escape) so its options load. Don't pick anything.
2. Open the Console (View > Developer > JavaScript Console), paste this and press Enter:

   ```js
   (() => {
     const roots = [];
     const walk = n => n.querySelectorAll("*").forEach(e => { if (e.shadowRoot) { roots.push(e.shadowRoot); walk(e.shadowRoot); } });
     walk(document);
     const html = "<!doctype html>\n<html>" + document.documentElement.getHTML({ shadowRoots: roots }) + "</html>";
     copy(html.replace(/<script\b[\s\S]*?<\/script>/gi, ""));
     return `copied ${html.length} characters`;
   })()
   ```

3. Paste it into a new file **outside the Jobsmith folder**, numbered in order, for example
   `~/Desktop/jobsmith-pages/workday/1-my-information.html`. Never put these in the repo yourself.
4. Take a full-page screenshot next to it (in DevTools: Cmd/Ctrl+Shift+P, then "Capture full size screenshot").
5. Now fill the page's required fields with the made-up details above, and press **Save and Continue**.

The pages are usually, in this order (a company can add or drop some):

| # | Page | What to note |
| --- | --- | --- |
| 1 | My Information | How did you hear about us, previous worker, name, address, phone |
| 2 | My Experience | Work history, education, skills, resume upload (don't upload; leave it), websites |
| 3 | Application Questions | Work authorization, sponsorship, the company's own questions |
| 4 | Voluntary Disclosures | Gender, ethnicity, veteran status, terms checkbox |
| 5 | Self Identify | Disability form. Its name and date are a signature: if it won't continue without them, use Alex Rivera and today's date |
| 6 | Review | Save it **after** filling with made-up details only; it shows them all. Don't press Submit |

If a page shows an error after Save and Continue (a field it insists on), save that page again with the error showing:
the message is useful too (`multistep.page_errors` reads them).

## Then

Tell Claude Code where the folder is and which posting it was. It builds the fixtures the way the public Workday pages
were built (`tests/fixtures/src/workday_fixture.py`): nothing loaded from the network, account, tenant and tracking ids
blanked, every made-up detail checked to be Alex Rivera's, and it refuses any page with another email address or phone
number in it. It checks them for anything of yours before they're committed, and you can check too: the files are
plain HTML.

## If something stops you

A CAPTCHA, an emailed code or a bot check ("Access is temporarily restricted"): do it yourself if it's an ordinary
sign-in step, or stop and say so. Don't look for a way round one.
