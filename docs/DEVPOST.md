# ReMind: Devpost writeup (draft)

Fill in the `[TODO]` items with things only the team knows (real numbers, quotes, what actually worked on demo day). Anything marked as simulated is simulated today; change the wording if that changes.

## Inspiration

A single nurse in a long-term care home may look after ten or more residents. Many of those residents are living with dementia, and the activities that help them (sorting, sequencing, familiar-object games, conversation) are exactly the ones a nurse has no time to run one-on-one. Cognitive stimulation programs for dementia are built around short, social, low-pressure activities, but they need a person sitting next to the resident.

We asked: what if the nurse could start an activity, walk away, and check in on the results? Not a screen that quizzes people, but a companion that talks, and a robot arm that takes part in the game physically, so the activity feels real and familiar.

[TODO: add any personal story or conversation with a caregiver that motivated the team.]

## What it does

ReMind is a caregiver-supervised companion for people living with dementia. A resident talks to ReMind, by voice or by typing. ReMind chats warmly and, when the resident asks to play, starts a game from a catalog.

The first game is **Reorder**: a robot arm mixes up a few everyday objects, and the resident puts them back in the right order. ReMind watches the result, says whether it's right, and if not, explains kindly what to fix. The resident gets three tries, then ReMind gently shows the answer. There is no score and no countdown.

- **Voice mode:** continuous, interruptible conversation. Press start once and just talk.
- **Chat mode:** the same assistant by text, for noisy rooms or residents who prefer typing.
- **Tool calling:** the assistant decides when to list games, start a game, check the table, call a caregiver, or stop. The user just speaks naturally.
- **Safety by design:** the AI never controls the robot. It can only call a short list of tools, the backend checks every request, and the robot only runs jobs on its own allowlist. "Stop" is handled by our server before the AI sees it.
- **Caregiver view:** supervision, live status and results (non-clinical wording only).

ReMind supports engagement. It is not a diagnostic or treatment tool and has not been clinically tested.

## How we built it

- **Frontend:** Next.js and React. One page with a Voice/Chat toggle, a conversation history, and a Tools menu that shows what the assistant can do and whether each tool is real or still simulated.
- **Conversation AI:** Google **Gemini**. Gemini Live gives always-listening, interruptible speech-to-speech conversation with function calling; the Gemini text model powers chat mode. **ElevenLabs** provides the natural voice for chat-mode read-aloud.
- **Backend:** FastAPI. A small tool layer (`list_games`, `start_game`, `check_arrangement`, `alert_caregiver`, `stop`) sits between the AI and the real world. It validates every call, tracks the game state and the three-try rule, and relays the live audio so the API key never reaches the browser.
- **Robotics:** an SO-101 arm driven through LeRobot, with policies trained and served by **Perceptron**. Our teammates built Robot Studio: teleoperation with a leader arm, recording demonstrations, a recording campaign with spoken operator prompts, dataset upload and training, plus colour-based object detection with teach-and-remember. A robot worker runs one allowlisted job at a time, and the backend talks to it over HTTP.
- **Testing:** automated tests for the game rules, the tool calling, the robot-job flow (with a fake worker), and the live-audio relay (with a fake Gemini server).

## Challenges we ran into

- **Making a physical robot fit a conversation.** A shuffle takes many seconds. If the AI waited for it, the conversation would freeze. We made `start_game` return immediately, then have the backend watch the job and make the agent speak up when the robot finishes.
- **Knowing the robot is "done" is not knowing it worked.** The policy API gives movements, not a success signal. The real answer has to come from the camera reading the table after the shuffle.
- **Sensitivity to the scene.** The robot's policy depends on lighting, camera height and table colour, so we had to lock down the setup.
- **Free-tier limits.** Gemini's free tier returned busy and quota errors, so the agent retries, falls back to a lighter model, and finally to keyword rules so the demo never goes silent.
- **Designing for people with dementia.** People may speak slowly and pause mid-sentence, so we tuned the silence detection to wait longer before deciding it's the AI's turn.
- **Several people, one repo.** We split the code into per-person folders and agreed that the robot code is owned by the robotics team: everything else adapts to it.

[TODO: add the real hardware and integration problems you hit.]

## Accomplishments that we're proud of

- A voice assistant that you can interrupt and that calls real tools, with the safety rules enforced in code instead of left to the prompt.
- A clear "this is real / this is simulated" label for every tool, visible in the product itself.
- A full recording-to-training pipeline for the robot arm, with spoken prompts for the operator.
- Automated tests around the parts that matter for safety (stop handling, allowlists, job flow).
- [TODO: the best demo moment, e.g. the first time the robot and the voice worked together, if it did.]

## What we learned

- Putting the AI behind a small, validated tool list is what makes it safe to connect to a physical robot.
- Real-time voice is mostly about turn-taking: when to speak, when to stay quiet, and how to be interrupted.
- For vulnerable users, tone matters as much as accuracy: no scores, no shaming, short sentences, and an easy way to stop or call a human.
- Robot demos fail on the environment (light, camera, table) more often than on the model, so the setup needs to be treated as part of the product.
- [TODO: team lessons about working in parallel, or about the APIs.]

## What's next for ReMind

- **Close the loop with the camera.** Today the shuffle and the final check are simulated in software. Next is reading the real table after the shuffle and after the resident reorders, so the feedback is based on what is actually there.
- **A trained shuffle skill** on the robot, so the game runs with a real physical shuffle.
- **More games in the catalog,** such as the memory games already in progress, and difficulty levels (fewer objects, a hint card).
- **A real caregiver dashboard** for ten residents at once, with live alerts delivered to a phone, and simple per-resident history shown as plain facts rather than a decline score.
- **Consent and data controls,** and a pilot with a care home and a clinician to learn what actually helps, before making any claims.
