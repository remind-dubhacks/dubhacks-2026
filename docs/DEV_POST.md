<!-- Title options:
1. We taught a robot arm to shuffle keychains for people with dementia
2. 60 demonstrations later: teaching a robot arm to play a memory game
3. A robot arm, Gemini Live, and a memory game for dementia care
4. Memory games for dementia that you play with your hands
5. ReMind: a talking memory-game companion with a robot arm
-->

_Built at DubHacks 2026 with [@maiaPaperTowns](https://github.com/maiaPaperTowns), [@alesia-cameron](https://github.com/alesia-cameron), [@matthewcflam](https://github.com/matthewcflam) and me [@lkim0402](https://github.com/lkim0402). ReMind supports engagement. It is not a diagnostic or treatment tool and hasn't been clinically tested._

A robot arm mixes up three keychains on a table. Someone puts them back in order by hand, and an AI that's been listening tells them how they did. A caregiver in the next room gets a short note about it.

That's ReMind, our DubHacks project. The arm took us the longest, so that's where most of this post goes.

## The problem

Several of us have a family member with dementia or memory loss, and they go to centers for older adults. Staff there run activities meant to keep people engaged and slow things down, or at least not make them worse.

Cognitive stimulation is a set of enjoyable activities that stimulate thinking and memory, usually in a group. It has a research base: a 2023 Cochrane review (Woods et al.) found small, short-term cognitive benefits for people with mild-to-moderate dementia. Digital tools for dementia exist too, but reviews of them keep pointing to the same gaps. These are the four we designed against:

1. **Not personal enough.** A review of reviews on digital assistive technology for dementia lists personalization as a challenge that keeps coming up. A 2026 exergame pilot notes that most exergaming systems lack features that support personalized care.
2. **Hard for older adults to use.** A 2026 usability study of exergames for older adults with mild cognitive impairment notes that existing exergames mostly target younger people and lack usability for older adults.
3. **People stop.** Facility-based exercise is often hard for people with cognitive impairment to reach, with up to half of sessions missed and low adherence to home programs, according to a 2026 trial abstract (AAN). A review protocol on home-based exergames also notes that adherence tends to decline over time.
4. **Thin evidence.** The same review of reviews flags an insufficient quantity and quality of randomized trials. One earlier review of exergaming in dementia found only three eligible studies, with very small samples. A 2020 review of ten trials (702 participants) found consistent cognitive benefits in seven low-bias studies, but high variation in duration, frequency and platform. It looks promising, but nobody has settled the details.

So we aimed for memory-jogging games based on cognitive science, built to fit older adults. You just talk, so there are no menus. The screen is calm and shows one photo or a few words. The caregiver stays in charge. And because we don't think a screen is enough, there's a real robot arm.

We make no medical claims. We're engineers, not clinicians. What ReMind can do is keep plain notes about each session ("talked about seeing Elvis films with her sister"), so a caregiver or researcher has something concrete to look at.

## How it works

![ReMind in one picture: a resident talks and plays with a voice companion, a calm screen and a robot arm; the caregiver gets summaries and alerts](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/a1cdpw7u9ae81r8a5vsv.png)

There are four parts: a voice companion that listens and replies in real time in short sentences, a calm screen, a robot arm with a camera, and the caregiver, who sets up each session, reads the summary afterwards and gets a text if something seems off.

Why an arm? Most digital activities sit behind a screen. The arm lets the resident do something with their hands, with real objects, and the activities stay really simple, like putting three things in order. We also see it as a starting point. We want to teach it more policies (new skills) over time, and each one could become a new hands-on game.

### The main game

![The main game in five steps: the robot arm mixes up three keychains, the resident reorders them, a camera checks, ReMind answers kindly, a note goes to the caregiver](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/rjz2ndxxbvfwdkivix1z.png)

1. The arm mixes up three keychains on a table.
2. The resident puts them back in the right order.
3. A camera reads the order they just made. The check returns a plain result: right or wrong, why, and how many tries are left.
4. The AI gets that result and answers in plain words, like "Almost! Try swapping the last two." The resident gets three tries. After that, ReMind shows the answer gently. There's no score and no timer.
5. A one-line note about how they did goes to the caregiver. It's an observation, not a grade.

The camera read is live, and it's the part we like most. The AI never decides on its own whether the order is right. It gets a result from what the camera sees and turns it into something kind.

### Keeping the AI on a leash

The AI never sends motor commands. It can only ask for things from a short list, our server checks each request, and the robot's own software checks again before it moves. Those rules live in code, not in the prompt, so the AI can't talk its way past them. "Stop" never reaches the AI at all. Our server catches the word and halts everything first.

## Teaching the arm

![How we taught the arm: show it, record it, let it learn, test it for real, and record more where it fails](https://dev-to-uploads.s3.us-east-2.amazonaws.com/uploads/articles/87k6oupd182eoppopkw1.png)

We wanted the arm to shuffle three keychains (black, white and purple) five ways: swap left and right, swap left and middle, swap middle and right, rotate everything one spot left, and rotate one spot right. They sit in a row of four slots, with the fourth left empty as a parking spot, because the arm needs somewhere to put one down. It works like a sliding puzzle.

We didn't program the movements. The arm is an SO-101, a cheap open-source one, and it learns from examples, a bit like teaching someone a card trick by showing them. One person moves a "leader" arm by hand and a second "follower" arm copies every move.

Two cameras film each try, one watching the table from the side and one on the gripper. A try is 35 seconds, and a computer voice tells whoever is recording what to do next ("Episode 3 of 4. Go." and "Reset the objects."), because you lose track fast. We recorded 60 tries, 12 for each shuffle, and uploaded them to Perceptron's cloud platform to train.

Then we test. We run it again and again on the real table and count how often it works. [TODO: your real number, e.g. "X out of Y shuffles worked".] When it fails in a specific spot, like a keychain sitting a bit too far left, we record more examples of that case and train again.

A few things we learned:

- The arm is picky about its surroundings. Table color, lighting and camera angle all have to match between recording and use, so we taped everything down.
- It copies how you move, speed included. We demonstrated slowly and gently, since it works near older adults.
- A bad try teaches a bad habit, so we redid those. We also nudged the keychains a little each time. Without that, the arm gets confused the moment something is slightly off.
- A flaky USB connection drops camera frames, which throws the video out of sync with the motion. A motor can also overload ("gripper fault") until you power-cycle it.
- We use soft, light objects only. No glass, no liquids. The power switch is the real emergency stop.

## The other games

The arm is one game. The rest run on voice alone, built on Gemini's Live API, which listens and talks at the same time and lets you interrupt. They follow session themes from Cognitive Stimulation Therapy:

- **Famous faces:** a photo appears, ReMind asks what they notice and what it reminds them of, then reveals the name.
- **Sayings:** ReMind starts a well-known saying ("A stitch in time saves...") and the resident finishes it.
- **Sounds:** ReMind plays an everyday sound, then asks what it was and what it brings to mind.

On the technical side, the browser streams the resident's voice to our backend, which relays it to Gemini so the API key stays off the browser. Gemini can call a short list of tools (`start_game`, `reveal`, `next_item`, `play_sound`, `show_message`, `note_response`, `end_game`, `stop`, `alert_caregiver`), and the screen shows only what those tools put there. The prompt asks it to ask for opinions and memories instead of facts, and never to test or correct anyone.

Real-time voice is mostly about when to stay quiet. By default it decides you're done talking too fast, so someone who pauses mid-thought gets cut off. We turned the end-of-speech sensitivity down and wait 1.2 seconds of silence:

```python
"realtimeInputConfig": {"automaticActivityDetection": {
    "endOfSpeechSensitivity": "END_SENSITIVITY_LOW", "silenceDurationMs": 1200}}
```

If it's quiet for 25 seconds, the backend nudges Gemini to carry on gently. After three nudges with no reply, it marks the person as withdrawn and rests the screen instead of talking to an empty chair.

## Texting the caregiver

If the resident says something worrying, we want the caregiver to know without scaring the resident. That's one more tool. Gemini decides whether something is worrying (pain, a fall, fear, feeling lost). If it is, it calls `alert_caregiver` with a short plain summary and no diagnosis, and calmly reassures the resident. The nurse enters a caregiver's phone number next to the patient's name, and the text looks like this:

```
ReMind alert, 3:53 AM, Margaret: Said her chest hurts and she feels dizzy.
```

It sends in the background, so a slow or failed text never interrupts the conversation.

We send it through [Photon](https://photon.codes). Its SDK is TypeScript and our backend is Python, so a small Node service turns a request into an iMessage. Our sends kept failing with `PERMISSION_DENIED: Target not allowed for this project`. On the free tier, a project can only text phones enrolled in it. We spent an hour blaming our own code before we tried Photon's starter project, which didn't work either. That told us it was account setup. If you use a vendor SDK, test their starter first.

Gemini's judgment is the weak spot. It might skip something borderline or fire on something mild, and nothing limits how many texts one worry can send yet.

## What broke

- A robot shuffle takes many seconds, and if the AI waited for it the conversation froze. Starting a game now returns immediately, and the backend speaks up when the robot finishes.
- Our alert tool used to say "a caregiver has been notified" even when no text went out. It now says exactly what happened.
- Gemini's free tier returned busy and quota errors, so the app retries, falls back to a lighter model, and finally to keyword rules so the demo never goes silent.

## What's next

- More skills for the arm. Each new policy we teach it could become a new hands-on game.
- A caregiver dashboard that shows plain facts for a whole room of residents, not a decline score.
- Games that adapt to each person, which is how we'd properly answer the personalization gap. Today we only pick games per person and use their name.
- Consent and data controls, and a pilot with a care facility and a clinician before we claim anything.

**Code:** [github.com/remind-dubhacks/dubhacks-2026](https://github.com/remind-dubhacks/dubhacks-2026)
