# Usability test: three people, fifteen minutes

The third check of the Phase 1 gate: **3 people who aren't developers reach their first real application in under
15 minutes without help.** This is the script for watching them. Run it three times, with three different people,
and fill in the table at the end.

"Reach their first real application" means: Jobsmith is installed on their computer, setup is finished with their
own resume, and one real application is filled and waiting for them to approve (autopilot) or submit (copilot).
They don't have to send it. The clock stops when that filled application is on their screen.

## Who to ask

- Someone applying for internships or new-grad jobs now, or who will within a few months.
- Not a developer: they don't use a terminal for work or study and have never used Jobsmith. A CS student who has
  never opened Terminal counts; someone who has installed command-line tools before doesn't.
- Their own Mac or Windows laptop, with Chrome and their resume as a PDF on it.
- Not someone who helped build or test Jobsmith, and not someone who has watched it being used.

Aim for at least one Windows and one Mac user among the three.

## Before they sit down

- Ask them: "You'll install an app that fills in job applications, using your real resume, on your own laptop.
  Nothing leaves your laptop except to the job sites you apply on. I'll watch and take notes on where the app is
  confusing. I'm testing the app, not you. You can stop at any point." Go on only if they say yes.
- Their resume and answers are theirs. Don't copy, photograph or keep anything from their screen. Notes record
  what was confusing, never what they typed. No screen recording unless they offer, and then it stays with them.
- They decide whether anything is sent. If they'd rather not apply for real, stop the clock at the filled
  application and have them press Skip.
- Have a timer, this page, and the notes table. Sit where you can see the screen. Don't touch the keyboard.

## What to say

Read this out, then start the timer:

> "This is the page for a tool called Jobsmith. Use it to get to the point where one job application is filled in
> and waiting for you. Think out loud as you go: say what you're looking at and what you expect to happen. I can't
> answer questions while you work, but tell me anything that's confusing. Go ahead."

Give them only this link: <https://github.com/rawcache/Jobsmith#quick-start> (the README, which leads to
[Getting started](../getting-started.md)). Don't point at anything.

## While they work

**Don't help.** That's the test. If they ask what to do, say: "What would you do if I weren't here?" If they're
stuck for two full minutes and say they would give up, note the time and where, give the smallest hint that gets
them moving, and mark the run **helped**. A helped run doesn't count toward the gate, however fast it finishes.

Only two things are not "help": telling them which file on their laptop is their resume, and anything about their
laptop that isn't Jobsmith (Wi-Fi, a full disk, their Mac's login password for a system prompt).

Write down the time on the timer when each of these happens:

| Moment | What you see |
|---|---|
| Install starts | They paste the install line and press Enter |
| Installed | They type `jobsmith` and it opens |
| Resume read | Setup shows what it read from their PDF |
| Questions answered | They get past "Questions forms ask" |
| Looking for | They see the number of matches and continue |
| Setup done | They press "Fill my first application" |
| **First application** | A filled application is on screen, waiting for them. **Stop the clock.** |

And for the whole run, note each time they:

- stop for more than 20 seconds (where, and what they said),
- read something twice or say they don't know what a word means (write the word),
- do something the app didn't expect (which button, what happened),
- see an error or a system prompt (the exact words),
- say what they expected, when it wasn't what happened.

Things to watch for in particular, because they went wrong before: the macOS keychain prompt ("Chromium Safe
Storage"); not knowing whether to choose the terminal or the browser for setup; the three questions with no
default; a match count of zero or in the thousands; a pile of "Needs you" instead of one application; closing the
terminal window by accident.

## Afterwards (five minutes)

Ask, and write down their words:

1. "What was the most confusing moment?"
2. "Was there a point where you weren't sure what Jobsmith was about to do with your information?"
3. "Looking at the filled application: is there an answer you wouldn't have given?"
4. "Would you let it send applications for you tomorrow? What would have to be true first?"
5. "If you had to explain to a friend what 'Needs you' is for, what would you say?"

Thank them. If they want to keep using it, show them `jobsmith demo` for a safe place to explore, and the
[troubleshooting section](../getting-started.md#5-if-something-goes-wrong).

## Did the run pass?

A run passes when all of these are true:

- the clock stopped under **15:00**,
- it was not **helped**,
- the application on screen is for a real posting and was filled from their own resume,
- they didn't have to type anything into a terminal beyond the install line and `jobsmith`.

The gate passes when three runs pass, each with a different person. A failed or helped run isn't thrown away: it
says what to fix. Fix it, then test again with someone new (a person who has seen Jobsmith can't be a first-time
user twice).

## Results

No names: a letter per person. Times as minutes:seconds on the timer.

| | Person A | Person B | Person C |
|---|---|---|---|
| Date | | | |
| Mac or Windows | | | |
| Jobsmith version | | | |
| Installed | | | |
| Resume read | | | |
| Questions answered | | | |
| Setup done | | | |
| **First application** | | | |
| Helped? (where) | | | |
| Passed? | | | |

**What confused people** (one line each, most common first, with the issue opened for it):

-

Every problem seen becomes an issue on the Phase 1 milestone, labelled `usability`, written as what the person saw
and expected, never with anything from their resume or answers.
