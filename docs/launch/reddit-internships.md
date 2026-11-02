# r/internships draft

Check the rules first. This sub is mostly students who aren't developers, so the install line matters more than the
stack. Keep it short.

**Title:**

> I built a free tool for my own internship search that fills out applications for you (open source, runs on your laptop)

**Body:**

I built this for my own internship search and made it free and open source: https://github.com/rawcache/Jobsmith

You give it your resume and a list of jobs. It finds the roles you qualify for, fills in the application (name,
school, links, work authorization, your answers) and submits it on Greenhouse, Ashby and Lever job sites, up to 20 a
day. The first one on each site waits for you to look it over.

The rules it follows:

- It never makes things up. Every answer is built from your resume, your profile or your own writing, and is checked
  before it's sent.
- Work authorization and sponsorship answers come only from what you confirmed.
- It never creates accounts, types passwords or touches LinkedIn. Anything like that comes to you.
- It runs on your computer, with no account to make. Your resume goes only to the job sites you apply on and, if
  you connect one, the AI you pick (Gemini, Claude or OpenAI); with a local model or no AI, it never leaves.

What it can't do yet: Workday, iCIMS and SmartRecruiters applications are only partly filled, so those are still
yours to finish.

Install is one line on Mac, Windows or Linux (it's on the page above), and `jobsmith demo` lets you try it with a
made-up student first. Happy to answer questions.
