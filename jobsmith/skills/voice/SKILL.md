---
name: jobsmith-voice
description: Teach Jobsmith how the user writes, from their own essays, cover letters and past answers, so applications sound like them even with a small local AI or none at all. Use when the user wants answers to sound like them, adds writing samples, or asks what stories they're missing.
title: Your voice
status: ready
order: 20
page: #/voice
command: jobsmith voice
---

# Your voice

Everything Jobsmith writes starts from you. Add writing you're proud of (an essay, a cover letter, answers you
wrote yourself) and Jobsmith keeps it on your computer, split into passages it can find again.

- **No AI needed.** For an open question, Jobsmith finds the passages you already wrote that fit it best and
  adapts them (the company, the role). Your words, not a model's.
- **With any AI, even a small one.** Your closest passages go into the prompt as examples, so a 4B model on
  your laptop writes like you instead of like a chatbot. Answers that drift from your style, or use stock
  phrases you never use, are held instead of sent.
- **Knows what's missing.** It sorts common questions (why this company, a time you led, a conflict, a failure,
  a project you're proud of) by whether you have material for them, and asks for the stories you don't.

```
jobsmith voice add my-essay.md         add writing (.md, .txt, .docx, .pdf)
jobsmith voice                         what it knows and which stories are missing
```

For an AI agent: `jobsmith_voice_examples` returns the user's closest passages for a question;
`jobsmith_voice_add` saves new writing the user gives you.
