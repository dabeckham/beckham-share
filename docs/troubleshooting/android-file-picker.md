# Troubleshooting: "why is the upload page asking for my microphone?"

A walkthrough of how I diagnosed a confusing bug report on Beckham Share. It's written so the
*method* is reusable on any problem — the specific bug matters less than the way through it.

## The report
On an Android phone (Samsung, Firefox), signing in and tapping **Upload** popped up a system
prompt: *"Allow Firefox to record audio?"* Nothing on a file-share upload page should need a
microphone. So: what's actually going on, and is it dangerous?

## Step 1 — Separate fact from fear: what is actually on the page?
Before theorizing, I checked the code. A microphone can only be reached through specific browser
APIs — `getUserMedia`, `AudioContext`, `mediaDevices`. I searched the whole app for them:

```
grep -rE "getUserMedia|AudioContext|mediaDevices" app/
```

Nothing. The page has no audio code at all. That one check reframed the problem: the page isn't
*trying* to record audio — something else is triggering the prompt.

> **Lesson:** verify what the system actually contains before you explain its behavior. Rule
> things out with evidence, not assumptions.

## Step 2 — Find the only suspect
What could a browser associate with capture on this page? The file input:

```
<input type="file">
```

That's the only element involved in "Upload." Hypothesis: the browser treats a file input as a
possible *capture* source (camera / camcorder / voice memo) and pre-emptively asks for the
permissions those would need.

## Step 3 — A fix attempt that failed (and why that's useful)
My first instinct was to constrain the input with `accept="*/*"`. I shipped it and tested — and it
got **worse**: the chooser now offered only Camera / Camcorder / Photos & Videos, with no file
browser at all. I reverted immediately.

> **Lesson:** a plausible fix is a hypothesis, not a solution — especially on a platform you can't
> test from your own desk. Confirm before you trust it, and be ready to undo.

## Step 4 — Read the primary sources
Instead of guessing again, I read the authoritative references on how `<input type="file">` and
`accept` behave on Android:

- **Mozilla bug 1337692** — `accept="image/*"` requests camera, `audio/*` requests microphone,
  `video/*` requests both, and **no `accept` should request only file storage**.
- **Mozilla bug 1362919** — if camera/mic permission is *denied at the app level*, older Firefox
  wouldn't open the plain file picker at all.
- A cross-browser writeup on Android file inputs and the `accept` attribute.

Now I had a model: the prompt is the browser's doing, driven by `accept`, and the permission
*state* on the device matters too.

## Step 5 — When you can't reproduce, build the smallest decisive test
I couldn't reproduce the Samsung behavior on my own machine, and theory said no-`accept` should
already be fine. The bottleneck was empirical data from the device that *does* reproduce it. So I
built a tiny page with the same file input repeated under six different `accept` values, each
showing the file you picked so you can tell whether it actually worked:

[`picker-test.html`](./picker-test.html)

Then I had the person with the phone tap each one and report what happened.

> **Lesson:** when a bug only appears in an environment you don't have, stop guessing — hand that
> environment a controlled experiment that isolates one variable at a time.

## Step 6 — Read the results, land the resolution
The results were clear. **No `accept`** opened the full file picker showing all files in both
Chrome and Firefox. `application/octet-stream` hid recent files in Firefox; extension lists
over-filtered the picker. And the prompt itself is unavoidable from HTML — the browser asks
because the file chooser *can* capture media. The real fix lives on the device:

> Set the browser's **Camera + Microphone permission to "Don't allow"** in the Android app
> settings. It persists, the prompt stops, and the file picker opens every time. (Hitting **Back**
> also dismisses a single prompt.)

So the app needed **no change** — it was already at the correct setting (no `accept`).

## The takeaways
1. **Verify before you explain.** A ten-second `grep` reframed the entire problem.
2. **Treat a fix as a hypothesis** until it's confirmed in the failing environment.
3. **Read primary sources** instead of guessing repeatedly.
4. **Isolate one variable at a time** — the test page changed only `accept`.
5. **When you can't reproduce, ship an experiment, not a guess.**
6. **The fix isn't always code.** Sometimes the answer is a setting, and "no change needed" is a
   valid, well-earned resolution.

The diagnostic page from Step 5 is kept here for reference: [`picker-test.html`](./picker-test.html).
Open it from a checkout (or download it and open it in a browser) to experiment on any device.
