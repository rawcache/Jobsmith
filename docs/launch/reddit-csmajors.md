# r/csMajors draft

Check the rules for self-promotion first; if there's a dedicated thread for projects or tools, use it.

**Title:**

> I got tired of filling in the same Greenhouse form over and over, so I built an open-source tool that applies for me

**Body:**

Internship season means the same form again and again: name, school, graduation date, links, work authorization, "why
this company?". I built Jobsmith for my own search to do that part, and I'm open-sourcing it (MIT):
https://github.com/rawcache/Jobsmith

- Point it at the SimplifyJobs-style GitHub lists or a company's job board, and it scores every role against your
  resume.
- It fills and submits on **Greenhouse, Ashby and Lever** while you're in class, up to 20 a day and 3 per company a
  week by default, and the first one on each site waits for you to check.
- Your saved answers to "Why {company}?" and "Why this role?" go in exactly as you wrote them, with the company and
  role filled in. Optional essay boxes are left blank rather than filled with AI filler.
- It never makes up a number or a skill: everything is checked against your resume first, and `jobsmith audit`
  shows where each sent answer came from.
- Free: Gemini's free tier (it stays under a daily budget), a local model, or no AI.

Honest status: Workday, iCIMS and SmartRecruiters are only partly working (it stops before their later pages), the
Chrome extension isn't in the Web Store yet, and I'm still measuring it on my own search ({{SUBMITTED}} applications
so far).

To try it without your data: install, then run `jobsmith demo`, which opens a practice copy with a made-up student.

If you want to help, there are good first issues with the files to touch listed:
https://github.com/rawcache/Jobsmith/labels/good%20first%20issue
