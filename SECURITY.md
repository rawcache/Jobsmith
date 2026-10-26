# Security

Jobsmith runs on your computer and holds sensitive things: your resume, your answers, AI keys, and (if you connect
it) read access to your email. Please report anything that could expose them.

**Report privately:** use GitHub's "Report a vulnerability" button on the Security tab. Don't open a public issue.

Never paste keys, tokens, passwords or your real resume into an issue, a pull request, or a log you share.

What counts:
- Anything that sends your data somewhere other than the job site you're applying to, your chosen AI, or your own email.
- The engine or dashboard being reachable from outside your computer (it should bind to 127.0.0.1 only).
- Keys or tokens shown unmasked in the dashboard, logs, or the MCP server.
- The extension running on pages it shouldn't, or leaking page content.

## What the extension may reach

The Chrome extension's `manifest.json` asks for as little as it can:

- **Its page panel and autofill** (`content_scripts`) run on the pages you open, so the panel can appear on any
  company's careers page. They only read the page you're on and talk to Jobsmith on your computer.
- **`activeTab` and `scripting`**: when you click the toolbar button, the extension may add its script to the page
  you're looking at. That only matters for a tab that was open before the extension was loaded.
- **`host_permissions`**, the sites the extension may reach on its own:
  - `http://127.0.0.1/*` and `http://localhost/*`: the Jobsmith engine on your computer.
  - `https://*.greenhouse.io/*`, `https://*.lever.co/*`, `https://*.ashbyhq.com/*`, `https://*.myworkdayjobs.com/*`,
    `https://*.icims.com/*`, `https://*.smartrecruiters.com/*`: job sites whose application forms companies show
    inside a frame on their own careers page. Clicking the toolbar button reaches the page you're on but not a frame
    from another site, so without these the extension couldn't fill an embedded form in a tab that was open
    before it was loaded.

A form in a frame from any other site gets "Reload this page" instead: a reload brings the page panel back in
every frame, with no extra permission. Adding a site to this list widens what the extension may reach; it needs a
reason here and a test in `tests/test_extension.py`.
