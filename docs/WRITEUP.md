# May 6 or June 5?

A student types: *"program end 05/06/2027, when is my OPT deadline?"*

If you grew up in the US, that's May 6. If you grew up almost anywhere else, which describes most people asking about OPT (the work permit international students apply for after graduating), it's June 5. Same five characters, two deadlines a month apart. File a day late and the application is denied.

I built [optwise](https://github.com/slvx17/optwise), a small tool that tells students when to file. It is a simple project: five rules from one regulation, some date math, a web page. But it ran into the one problem every AI product in a high-stakes corner eventually meets.

## The helpful intern problem

Language models are wonderful at reading messy questions. "graduating may 2027 whens the last day i can aply??" is no trouble at all.

They are also eager. Ask one about `05/06/2027` and it will not ask which you meant. It will pick one, confidently, and move on. Most of the time that's a feature. Here, a confident guess is the worst possible answer, because the student has no way to know it was a guess.

So the whole design came down to one sentence: **the model may read, but it may not decide.**

## How that works

Every date the student sees is computed by plain code from the regulation's text. The model gets two narrow jobs:

1. **Point at the dates in the question.** Not interpret them, point at them: "this bit is the program end date". Code then reads that bit. If it says `05/06/2027`, code notices it can be read two ways and asks, with two buttons: *May 6, 2027* or *June 5, 2027*. If it says "summer 2027", code says that's somewhere between June 1 and August 31, and tells the student where the exact date is printed (their I-20, page 1).
2. **Explain the plan in words.** Then code checks the explanation. Any date or number in it must have come from the plan or from the student. If it didn't, the explanation is thrown away and the student sees the plan without it.

The plan itself never depends on the model. If the AI is down, slow, or over budget, the page still works; it just gets quieter.

## The intern, caught in the act

I wrote 67 test questions, the messy kind real students ask, and ran them through. The checks above caught the model doing exactly what I feared:

- It picked May 6 for `05/06/2027`, without asking.
- A student wrote "commencement is may 20". The model helpfully added "2027". The student never said 2027.
- Asked how many unemployment days were left after using 80, it did the subtraction itself: 70. Correct, as it happens. Also the one thing it isn't allowed to do, because next time it might not be.

None of those guesses reached a student. The explanation was dropped, and the page showed the plan, or asked for the date it needed.

My favourite catch came from comparing models. A cheaper one scored 78% against 98%, which looks like "a bit worse". Then I split the mistakes into two kinds: *asked when it didn't need to* (costs the student a click) and *stated a wrong date with confidence* (costs the student their status). The cheaper model's 5% of the second kind was the real story. It had filed someone's program end date as the date their work card expires. Averages hide exactly the mistake you care about, so that one now has its own target: zero.

## What I'd tell myself at the start

The AI part of this project is small. Most of the work went into deciding what the AI is *not* allowed to do, and building checks that notice when it tries anyway.

In practice, the most useful thing the assistant says isn't a date. It's:

> *"05/06/2027" can be read two ways. Which one?*

Try it at [optwise.onrender.com](https://optwise.onrender.com) (the first visit can take up to a minute while the free server wakes up). Not legal advice; ask your school's international office.
