# Design: autopilot in your own Chrome

Status: proposal. Not built in Phase 1. The roadmap's risk list says to build it if the confirmed-submission rate
(`jobsmith stats`) is low, because sites treat Jobsmith's own browser as a bot.

## The problem

Autopilot fills and submits in a browser Jobsmith starts itself: Playwright's Chromium (or your installed Chrome)
with a separate profile in the data folder, usually in the background. That browser:

- has none of your sign-ins, so a Workday or iCIMS portal you're signed into in Chrome asks you to sign in again;
- has a short history and few cookies, and runs under automation, which some sites' bot checks score badly;
- can be stopped or slowed by CAPTCHAs that never appear in your everyday Chrome.

The result we'd see in `jobsmith stats` is a low confirmed rate: Submit clicked, but no confirmation page and no
confirmation email, because the site quietly dropped or flagged the submission.

## The idea

Let autopilot drive the Chrome you already use, through the Jobsmith extension, instead of a browser of its own.
The engine decides what to apply to and what to answer, exactly as now. The extension, already in your Chrome and
already able to fill forms, opens the posting in a tab, fills it, and (only when the engine says every answer
passed) clicks Submit, then reports the confirmation page back.

```
engine (127.0.0.1:8765)                      your Chrome
  picks a job, drafts, checks answers  ──►  extension service worker
  "apply to job X, these answers"            opens a tab in a separate window
                                             content script fills the form
  ◄── fields seen, values set, page text     (same code as Autofill today)
  traps / AI-policy / caps check again
  "submit" or "hold"                    ──►  clicks Submit, or leaves the tab for you
  ◄── confirmation page (url, title, text)
  logs the submission and its audit trail
```

## How it would work

1. **Pairing stays as it is.** The extension already talks only to `127.0.0.1`. Add a per-install secret the app
   shows once and the extension stores, so another local program can't ask the extension to submit.
2. **A job queue the extension polls.** `GET /api/ext/next` returns at most one job at a time, with the answers and
   files. The extension never decides anything on its own; it carries out one job and reports back.
3. **Its own window.** Each job opens in a new, unfocused window (`chrome.windows.create({focused: false})`), so
   autopilot never takes over the tab you're reading. You can watch it, or close it to cancel.
4. **Same fill code.** The content script's existing Autofill fills the form. Fields it can't fill go back to the
   engine, which holds the application under "Needs you" as today.
5. **Submit only on the engine's word.** Before Submit, the content script sends the page's visible and hidden text
   (the same `PAGE_JS` walk `traps.py` uses) and the filled values. The engine runs the trap check, the AI-policy
   check, the caps and `draft.readiness`, and answers `submit` or `hold` with the reason. The extension clicks only
   on `submit`.
6. **Confirmation.** The submit watcher the extension already has (`THANKS` in `content.js`) reports the
   confirmation page's URL, title and text; the engine logs it with `audit.log_confirmation`, same as autopilot
   today.
7. **Human pace.** One application at a time, with pauses between fields and between jobs, and the daily and
   per-company caps unchanged.

## What doesn't change

- Sign-ins, account creation, CAPTCHAs and emailed codes are still yours. When the extension sees a sign-in page
  or a CAPTCHA it stops, leaves the window open, and rings the bell. It never types a password, even though
  Chrome's password manager could fill one.
- No LinkedIn. The extension's host list never includes linkedin.com, and the queue refuses LinkedIn URLs.
- Page text is data. The trap and AI-policy checks run in the engine on what the extension reports, before Submit.
- Nothing leaves your computer: the extension talks only to the app on `127.0.0.1`.

## Tradeoffs

| | Jobsmith's own browser (today) | Your Chrome, through the extension |
| --- | --- | --- |
| Looks like you to the site | Less: fresh profile, automation flags | Yes: your profile, history and cookies |
| Signed-in portals (Workday, iCIMS) | You sign in again in Jobsmith's window | Already signed in |
| Runs while Chrome is closed | Yes | No: Chrome must be open |
| Runs while you use the computer | In the background, unseen | In its own window; you may notice it |
| Can read confirmation pages | Yes | Yes |
| Hidden-text check before Submit | Playwright evaluates `PAGE_JS` | Content script runs the same walk |
| Real clicks for react-select and autocomplete | Yes (Playwright mouse and keyboard) | Synthetic events only; some widgets ignore them (#19) |
| Files (resume upload) | Playwright sets the file input | `DataTransfer` into the input; works on most sites, not all |
| Cross-origin frames (iCIMS) | Playwright reaches any frame | Needs host permission for each frame's site (#15–#17) |
| Risk if something goes wrong | Confined to a separate profile | Acts in your real profile, next to your own tabs and sign-ins |
| Web Store review | Not involved | An extension that submits forms gets closer review |

The biggest cost is trust: an extension that can click Submit in your everyday browser has to be held to a higher
bar than one that only fills. That's why the engine, not the extension, makes every submit decision, and why the
pairing secret matters.

## Options considered

- **Chrome DevTools Protocol on your Chrome** (`--remote-debugging-port`). Full control, but Chrome must be
  restarted with a flag, any local program could then drive it, and Chrome now refuses remote debugging on the
  default profile. Rejected.
- **Copying your Chrome cookies into Jobsmith's browser.** Gets sign-ins but not the history and reputation, needs
  the keychain (the "Chromium Safe Storage" prompt we removed in 0.4.5), and copies secrets around. Rejected.
- **Extension-driven, as above.** Chosen: no flags, no copied secrets, and the extension already fills forms.

## When to build it

Only if the confirmed rate stays low once Phase 1's sites are in: say, under 85% of autopilot's submissions with a
confirmation page or email over 50 real submissions, with the misses clustered on sites that flag automation. Until
then it's this note. If built, it's opt-in ("Apply in my Chrome" in Settings), off by default, and the current
browser stays the default.

## Tests it would need

- The extension, loaded in Playwright's Chromium, takes a job from a fake engine and fills the saved fixtures.
- It never clicks Submit without `submit` from the engine, including when the engine is slow or unreachable.
- It stops on a sign-in page and a CAPTCHA fixture.
- A hidden trap on the page makes the engine answer `hold`.
- A wrong pairing secret is refused.
