# Find & Remember: an object memory activity

A short, caregiver-supervised activity. The person chooses an object, watches it being moved, finds it with as much help as they need, does something with it, and is invited to share a memory about it. Code: [`backend/app/games/find_remember.py`](../backend/app/games/find_remember.py). Tests: [`backend/tests/test_find_remember.py`](../backend/tests/test_find_remember.py).

> **Evidence boundary.** This activity is *built from* established dementia-care methods (below). The activity as a whole has not been clinically evaluated. It is for engagement and enjoyment, not diagnosis, assessment or treatment. It produces no score, never records response times, and must not be described as improving memory or slowing dementia.

## One round (about 2–3 minutes)

| Step | ReMind says (example) | Why |
|---|---|---|
| 1. Meet the objects | "We have the pink pen on the left and the white keycap on the right. Which one would you like us to keep an eye on?" | Choice and real, familiar objects (CST, Montessori) |
| 2. An opinion, not a quiz | "What would you write with a pen like this?" | Opinions over facts, so there's no right answer (CST) |
| 3. Watch the move | "Hands resting on your lap, please. The pink pen goes to the right." | Narrating the move supports encoding; hands away from the robot for safety |
| 4. Find it | "Where is the pink pen now?" | Recall, kept short |
| 4a. If unsure or a different spot | "That's okay. Is the pink pen on the left, or on the right?" | Errorless learning: give support before an error. Never "wrong". |
| 4b. If still unsure | "Let's find it together. The pink pen is on the right, next to the keychain. There it is." | Every round ends in success |
| 5. Do something | "Could you pick up the pink pen and put it in the tray?" | Hands-on, purposeful action (Montessori) |
| 6. Share a memory (optional) | "Did you ever write letters or cards to someone special? You can skip this one if you like." | Reminiscence, always skippable, never corrected |
| 7. Spaced recall (some rounds) | "What was the first thing we put in the tray?" | Spaced retrieval: the gap grows after success and shrinks after support |

**Difficulty adapts gently.** Level 1 is 2 objects and 1 move, level 2 is 3 objects and 1 move, and level 3 is 3 objects and 2 moves. It steps up only after two finds with no help, and steps down as soon as a find needed showing. A session is at most 4 rounds, about 10 minutes, and always ends on a success with a thank-you.

**Language rules, enforced by tests.** It never says *wrong, incorrect, mistake, fail, test, score* or "no,". It asks one question at a time, uses the person's choice whenever possible, and never corrects a personal memory.

**Safety comes first in the code.** "Stop" ends everything. Words like *upset, scared, tired, I want to stop* pause the activity and alert a caregiver before any game logic runs.

## Evidence it draws on

| Method | What it means here | Key sources |
|---|---|---|
| Cognitive Stimulation Therapy (CST) | Themed, enjoyable activities with real objects; opinions over facts; respect and choice | Spector et al. (2003), *Br J Psychiatry* 183:248–254; Woods et al. (2012), Cochrane CD005562 (updated 2023); NICE guideline NG97 (2018) recommends group CST for mild-to-moderate dementia |
| Errorless learning | Prevent guessing errors by giving cues early, and show the answer rather than letting someone fail | Clare & Jones (2008), *Neuropsychology Review* 18:1–23; de Werd et al. (2013), *Clinical Interventions in Aging* 8:1177–1190 |
| Spaced retrieval | Recall the same information at expanding intervals; after support, shorten the interval | Hopper et al. (2005), evidence-based practice recommendations, *J Med Speech-Language Pathology* 13(4) |
| Reminiscence | Objects as prompts for personal memories, shared voluntarily | Woods et al. (2018), Cochrane CD001120 (*Reminiscence therapy for dementia*) |
| Montessori-based activities | Familiar materials, one step at a time, purposeful roles, success-oriented | Sheppard, McArthur & Hitzig (2016), *JAMDA* 17:117–122 (systematic review) |

Evidence for these methods comes mainly from group programmes and studies of mild-to-moderate dementia, and results vary. ReMind adapts their principles to a one-to-one tabletop activity. Before any real use, a care team (for example an occupational therapist or speech-language therapist) should review it.

## Running it

- **Start:** say "Let's play Find and Remember" on the voice page. With a Gemini key, Gemini starts it via the `start_game` tool. Without a key, the offline rules start it. **Every later turn is run by the exercise engine, not the language model**, so the wording above is guaranteed.
- **Objects:** `FIND_REMEMBER_OBJECTS=blue keychain,pink pen,white keycap`. Any names in `OBJECTS` work, including `tea box` and `coffee box`.
- **Who moves the objects:** `FIND_REMEMBER_MOVER` is one of:
  - `simulated`: prototype; the move is instant and on-screen.
  - `caregiver`: ReMind asks the caregiver to make the move, then the caregiver says "moved".
  - `robot`: the SO-101 moves them. This needs a trained or taught move skill; until then the caregiver does it.
- **Caregiver summary:** `state.exercise.summary` gives rounds played, finds without help, finds with a choice, finds together, and memories shared. These are engagement notes only.

## Before using it with a person

- **Small objects:** keyrings, keycaps and pen caps can be a choking risk for someone who puts things in their mouth. Use larger objects for anyone with that history, and always supervise.
- **The robot:** while it moves, hands stay on the lap, a caregiver stays within reach of the power switch, and the robot never moves while hands are in the workspace.
- **Comfort:** stop at the first sign of frustration or fatigue. A good session is a short, happy one.
- **Data:** use only synthetic or pseudonymous profiles in the demo. No recordings of the person are kept.
