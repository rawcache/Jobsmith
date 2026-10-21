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
