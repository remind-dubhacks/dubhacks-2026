# ReMind - Product and Engineering Specification

DubHacks 2026 | v1.0 | Proposed design

- **Main track:** Community Kitchen
- **Sponsored:** Perceptron Robotics (primary), SpaceXAI (Grok Voice), Photon (optional)
- **Non-sponsored:** MongoDB

## 1. Executive summary

ReMind is a caregiver-supervised, conversational activity companion for people living with dementia. An AI agent engages a participant in short, familiar, research-informed activities. A physical SO-101 robotic arm presents and sorts lightweight everyday objects in response to the participant's choices. An opt-in memory layer remembers preferences for future sessions. The product supports meaningful engagement, not diagnosis, treatment, or replacing human caregivers.

**Pitch:** "ReMind is an AI companion that doesn't just talk - it helps people participate in familiar activities through real-world interaction."

## 2. User problem and personas

- **Participant:** A person with mild-to-moderate dementia who may benefit from accessible, meaningful social and cognitive activities without pressure to perform on a memory test.
- **Caregiver / activity coordinator:** Needs practical ways to facilitate personalized engagement while supervising safety.
- **Family member (future):** Can optionally contribute familiar interests and topics with appropriate consent.

**Core job to be done:** Help a participant choose and complete a familiar, low-pressure physical activity while having a supportive conversation.

## 3. Research rationale and claims

The design draws on three approaches used in dementia care:

1. **Cognitive Stimulation Therapy (CST):** Structured, socially engaging activities involving thinking, language and discussion. Evidence supports modest cognitive benefits for some people with mild-to-moderate dementia in established programs.
2. **Reminiscence:** Familiar themes and objects may prompt autobiographical conversation; outcomes vary by context.
3. **Person-centered meaningful activity:** Tailor engagement to personal interests, strengths and preferences.

**Evidence boundary:** A robot-guided sorting session is inspired by, not equivalent to, validated CST. ReMind has not been clinically tested; do not claim it improves memory, slows dementia, reduces loneliness, or treats any condition.

References for deck: NICE dementia guideline NG97; Cochrane review of cognitive stimulation.

## 4. Product concept: Sort & Share

**Hackathon prop set:** Two identical lightweight rigid boxes labeled TEA and COFFEE, one serving tray, one optional SUGAR box, paper labels and a camera. These should be easy to find on site. Do not use hot liquids, medicine, fragile objects, or people inside the robot workspace.

**Example interaction:**

1. Agent: "Would you like to arrange a few things together?"
2. Participant: "Sure."
3. Agent: "Would you like tea or coffee?"
4. Participant: "Tea."
5. Software validates `tea_box` and requests an approved robot action.
6. SO-101 picks up the tea box from a fixed source and puts it in the tray.
7. Only after robot completion, agent says: "We put the tea in the tray. Did you enjoy tea with family or friends? You can skip if you'd like."
8. Participant may continue, ask for help, switch topics, or stop.

**Cognitive processes intended to engage:** familiar-object recognition, semantic association, simple choice-making, sequencing, language and optional reminiscence. These are engagement goals, not measured clinical outcomes.

**Adaptation:** Remember preferred themes; if a participant asks for help, offer fewer choices or demonstrate a step. Do not interpret response latency as a diagnosis or assign a clinical score.

## 5. User experience and screens

**Participant screen:** One large prompt, two large choice cards, Repeat, Help, Stop, subtitles, robot status and no countdown or score. Typed/tap controls must work without voice.

**Caregiver screen:** Select pseudonymous profile and activity; approve session; supervise robot; view nonclinical session summary; delete profile data.

**Session states:**

```
idle -> consented -> prompting -> choice_received -> validated -> queued -> moving -> verifying -> complete -> prompting
```

Any state can transition to `stopped`; hardware errors transition to `needs_staff`.

**Agent conversation rules:** One short question at a time. Never shame, correct personal memories, invent biographical facts, impersonate clinicians, or make medical promises. Offer to pause and request a human caregiver when needed.

## 6. Hardware and robotics scope

**Hardware:** Perceptron-provided SO-101 robot arm, computer and approved teleoperation setup, one fixed tabletop workspace, one known pickup zone, one drop tray.

**P0 robotic task:** Learn or execute a reliable single-object pick-and-place action from a known pickup position to a known tray. Use Perceptron's provided checkpoint and/or fine-tuning endpoints following mentor instructions. Record teleoperation demonstrations and capture a real working video.

**P1:** Support two object choices using two tested pickup positions or a supervised prop-loading step. Never imply arbitrary object grasping works if it has not been demonstrated.

**Safety:** Supervised use only; clear work envelope, accessible physical emergency stop, robot command allowlist, no movement while hands are inside workspace, and no autonomous retries after an error.

## 7. Architecture

```
Participant Web UI (Next.js / React)
          |
       FastAPI
          |
    Session Orchestrator -------- MongoDB Atlas
       |        |                     |
   Agent       Robot Worker       Profiles / Sessions
 (Grok Voice)  (LeRobot / Perceptron policy)
       |        |
   speech      SO-101 arm
       |
 Optional Photon caregiver notification
```

**Critical rule:** LLM text must never control motors directly. Agent emits structured intent; server checks consent, object whitelist, robot readiness and approved action before sending to robot worker.

**Agent structured output:**

```json
{"reply":"Would you like the tea box?","intent":"select_object","objectId":"tea_box","requestedAction":"move_known_object","needsConfirmation":false}
```

**Robot job lifecycle:** `queued`, `running`, `succeeded`, `failed`, `stopped`. UI and agent must wait for confirmed completion before saying the robot succeeded.

## 8. Sponsor integrations

| Track | Integration | Proof for judges | Priority |
| --- | --- | --- | --- |
| Community Kitchen | Person-centered activity and accessible interface | Full user journey, respectful interaction, caregiver supervision | P0 |
| Perceptron Robotics | SO-101 manipulation with checkpoint / fine-tuning | Actual working robot video, teleop data, inference results | P0 |
| SpaceXAI | Grok Voice for conversational turns and spoken choices | Real voice API calls and responses | P1 |
| Photon | Opt-in caregiver messaging agent for assistance requests | One real message triggered by participant request | P2 |
| MongoDB | Profiles, preferences, sessions, robot jobs | Data persists across restart and can be deleted | P0 |

Sponsor eligibility and API specifics must be confirmed with mentors. Photon is optional and must not block the main experience.

## 9. MongoDB data design

- **participants:** `_id`, `alias`, `interestTags`, `communicationPreferences`, `consentFlags`, `createdAt`
- **activities:** `_id`, `theme`, `prompts`, `objectIds`, `allowedActionIds`
- **sessions:** `_id`, `participantId`, `activityId`, `startedAt`, `endedAt`, `helpRequested`, `optInSummary`
- **robot_jobs:** `_id`, `sessionId`, `actionId`, `objectId`, `status`, `errorCode`, timestamps
- **messages (optional):** `sessionId`, `role`, `text`, `expiresAt`; avoid persistent raw transcripts by default

Use pseudonymous synthetic demo participants. No diagnosis, real patient data, biometric inference or raw voice recording required. Apply access controls, TLS, environment-managed secrets, retention limits and delete operations.

## 10. Proposed API endpoints

| Method / route | Purpose |
| --- | --- |
| `POST /api/sessions` | Start consented activity session |
| `POST /api/agent/turn` | Process typed/voice input; return response and structured intent |
| `POST /api/robot/jobs` | Validate and enqueue allowlisted action |
| `GET /api/robot/jobs/{id}` | Return robot job status |
| `POST /api/robot/stop` | Request software stop; physical emergency stop remains primary |
| `GET /api/participants/{id}` | Retrieve authorized preferences |
| `POST /api/feedback` | Store optional nonclinical session feedback |
| `DELETE /api/participants/{id}` | Delete demo profile and associated retained records |

## 11. MVP acceptance criteria

- SO-101 can be calibrated and teleoperated safely.
- At least one learned or approved checkpoint-driven pick-and-place works on the real robot and is filmed.
- Participant can select one object via buttons; voice is a stretch goal.
- Backend validates the selected object and triggers a robot job.
- UI shows queued, moving, completed or failed correctly; never fabricates success.
- A session preference is stored and read back from MongoDB.
- Help and Stop always work; failure asks for human assistance.
- A demo can run without real patient data or medical claims.

## 12. Build plan

- **First hour:** Finalize one prop and workspace. With Perceptron mentors, confirm arm calibration, teleop and safe stop. In parallel build basic React activity UI and mocked job API.
- **Hours 2-4:** Record robot demonstrations, train or test checkpoint, run the first real pick-and-place. Build FastAPI job lifecycle and MongoDB session storage. Film any early working success.
- **Hours 4-6:** Connect UI -> orchestrator -> robot worker. Add conversational agent and Grok Voice if credentials and SDK work. Keep typed buttons as fallback.
- **Final hours:** Stabilize one real action, run end-to-end tests, record submission video, prepare pitch. Photon only if core loop is working.

**Team split:** Robotics owner; backend/integration owner; frontend/agent owner; product/demo/testing owner. The robot owner should request mentor help early rather than spend hours blocked on calibration.

## 13. Testing, reliability and failure handling

| Scenario | Expected behavior |
| --- | --- |
| Unrecognized spoken object | Ask user to choose from supported objects |
| Participant says Stop | No new robot actions; stop request issued; staff can intervene |
| Robot fails grasp | UI says action failed; invite caregiver; no fabricated completion |
| MongoDB unavailable | Continue ephemeral demo without claiming preferences saved |
| Grok Voice unavailable | Typed choice + on-screen text fallback |
| Photon unavailable | No dependency on messaging for safe robot operation |
| Person reaches into workspace | Staff pauses physical robot immediately |

Measure robot success across repeated controlled trials and disclose actual results. A single success is a valid prototype demo but not evidence of deployment reliability.

## 14. 75-second judge demo

| Time | Beat |
| --- | --- |
| 0-10s | Introduce the problem and load a synthetic participant profile with a tea preference. |
| 10-25s | Agent welcomes judge, asks tea or coffee. |
| 25-40s | Judge chooses tea; UI displays validated object and queued robot action. |
| 40-55s | SO-101 physically moves the tea box to the tray. |
| 55-65s | Agent acknowledges completion and asks an optional reminiscence question. |
| 65-75s | Show persisted preference and caregiver view; demonstrate Stop. |

**Backup:** a prerecorded real robot demonstration may be shown if live inference fails, but it must be explicitly labeled prerecorded.

## 15. Differentiation and scalability

ReMind is not a generic chatbot, a stand-alone memory quiz or a robot sorting random blocks. The differentiated prototype combines conversational personalization, a low-pressure activity and a physically responsive robot.

- **Phase 1:** One controlled tabletop activity with staff supervision.
- **Phase 2:** Curated activity library (gardening, sorting school supplies, table setting) and caregiver feedback.
- **Phase 3:** Pilot with care facilities to study usability, acceptability, safety and engagement before any clinical benefit claims.
- **Long-term:** A configurable physical activity platform for care facilities; expansion to broader robotic assistance requires separate hardware, reliability and safety work.

**Business hypothesis:** Care facilities may value staff-supervised personalized activities, but willingness to pay, setup burden and resident outcomes remain unvalidated.

## 16. Pitch script

> "Imagine your grandmother is living with dementia. She used to love making tea with family, but familiar activities can become harder and care staff cannot always provide one-on-one engagement. ReMind is an AI companion that talks with her, remembers her interests and guides simple, meaningful activities. When she chooses an object, our SO-101 robot physically moves it so they can participate together. We're inspired by research on cognitive stimulation, reminiscence and person-centered care. We're not claiming to treat dementia or replace caregivers. We're building a more personal way to bring conversation and real-world activities together."

## 17. Submission checklist

- [ ] Confirm track eligibility and all sponsor integration requirements.
- [ ] Demonstrate actual Perceptron SO-101 robot action and submit working video.
- [ ] Record teleoperation / training setup and disclose real success rate.
- [ ] Show end-to-end interaction with voice or transparent typed fallback.
- [ ] Show MongoDB persistence and consent-aware data handling.
- [ ] Explain evidence accurately without clinical overclaims.
- [ ] Include demo video, repository, architecture diagram, limitations and future roadmap.
