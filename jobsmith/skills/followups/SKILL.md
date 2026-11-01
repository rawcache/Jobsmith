---
name: jobsmith-followups
description: Read replies from employers (read-only email), enter the code a job site emails to verify an application Jobsmith just submitted (never a sign-in or account code), and draft follow-ups for applications that went quiet. Use when the user asks what companies replied, or which applications to follow up on.
title: Inbox and follow-ups
status: ready
order: 40
page: #/followups
command: jobsmith followups
---

# Inbox and follow-ups

Reads your inbox read-only (Gmail, Outlook / Microsoft 365, or any IMAP server), on your computer:

- Types the code a job site emails to verify an application, only when Jobsmith pressed that application's Submit
  itself, the email is from that job site, arrived within 15 minutes and names the company or role. Never a sign-in,
  two-step, password-reset or account code: those, and anything else, wait for you.
- Moves applications along when a company replies: received, assessment, interview, offer, rejected.
- A week after you applied with no reply, drafts a short follow-up for you to send.

For an AI agent: `jobsmith_tracker` returns every application with its stage and the replies so far.
