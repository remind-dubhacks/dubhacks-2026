# Training the SO-101 for ReMind

**Goal:** one reliable skill. A participant chooses **tea** or **coffee**, and the follower arm picks up that box from its fixed spot and places it gently in the tray. Everything else in ReMind (conversation, memory, caregiver view) is built around this one physical action, so it has to be dependable more than clever.

Each skill is its own trained policy. The Grok agent never drives the motors: it picks an allowlisted skill, and the robot worker runs the matching policy (see [SPEC.md](SPEC.md) §7).

## 1. Set the scene once, then don't touch it

Policies are very sensitive to the environment. The Perceptron mentors' advice: the table colour, the camera type, height and angle, the lighting, and the resolution all need to match between training and the demo.

- **Tape everything down:** the arm base, the side camera, the tray, and two pickup spots (tea on the left, coffee on the right). Mark the spots with tape so boxes always go back to the same place.
- **Props:** lightweight rigid boxes only, labelled TEA / COFFEE. The arm can't apply much force, so weight and shape matter more than size. No liquids, mugs, glass or anything fragile, since this is for people with dementia, and keep the area clear of hands.
- **Cameras:** the side camera must see the arm, both boxes and the tray. The wrist camera sees what the gripper is about to grab. Check both in the Studio previews or in Rerun before you record.
- **USB:** plug the cameras and arms into the **high-throughput adapter** Perceptron gave us, not a cheap hub. Dropped frames misalign camera images with actions and hurt the policy.
- Record where the demo will happen, under the same lighting.

## 2. What a good demonstration looks like

The policy copies how you move, including how fast you move, so demonstrate the way you want it to act in front of a person with dementia:

- **Slow and smooth.** No jerky moves, and lower the box gently into the tray.
- Every episode does the whole task: start at a rest pose → reach → grasp → lift → move over the tray → release → return to the rest pose.
- **Use the same rest pose** at the start and end of every episode.
- **Add small variations** across episodes: nudge the box a few cm or rotate it slightly within its taped spot, and start from slightly different arm poses. Without variation the policy breaks the moment a box is slightly off.
- **If an episode goes wrong** (dropped box, clumsy grasp), stop and redo it. Bad demonstrations teach bad behaviour.

## 3. Record in Robot Studio

Start the worker from **Terminal.app** (it needs Terminal's camera access) and open http://localhost:3000/studio.

1. Run **Check motors**. All 12 must be OK. If one reports an overload, see Troubleshooting.
2. Do a quick **teleop + Rerun** warm-up and confirm both camera feeds look right.
3. In **Record episodes**, fill in:

   | Field | Tea run | Coffee run |
   |---|---|---|
   | Dataset | `<hf-user>/remind-sort` | `<hf-user>/remind-sort` (same one; it appends) |
   | Task instruction | `pick up the tea box and place it in the tray` | `pick up the coffee box and place it in the tray` |
   | Episodes | 10 per batch | 10 per batch |
   | Seconds per episode | 20 | 20 |
   | Reset seconds | 10 | 10 |

   **Copy the task instructions exactly.** The robot worker sends these same strings to the policy at run time (`ALLOWED` in [robot_worker/worker/main.py](../robot_worker/worker/main.py)). If you change one, change both.
4. Press **Start recording**. While the bar says *Recording*, do the task with the leader. When it says *Reset*, put the box back on its tape. Run batches of 10 so you can take breaks and check quality.

**How many episodes:** the mentors put the minimum at **about 50 per skill**. Plan on **50 tea + 50 coffee**, which is about 50 minutes of recording. If time runs short, do 50 tea first and get one skill working before adding coffee.

## 4. Upload and train on Perceptron

Put `PERCEPTRON_API_KEY` in `robot_worker/.env` and restart the worker.

1. **Datasets → Upload** on your dataset. Wait for the status to reach `finalized`, then click **Use for training**.
2. **Check dataset**: the validation must pass. Common failures are a missing camera or a training/validation split that's too small.
3. **Start training.** Start with the default 1,000 steps for a quick check that the pipeline works, then retrain with more steps once it does.
4. Use **Refresh jobs & deployments** to follow progress. When training succeeds, a deployment appears. Wait until it shows `ready`.

## 5. Test the policy before the app uses it

1. In `robot_worker/.env`, set `PERCEPTRON_DEPLOYMENT_ID=<ready deployment id>` and `ROBOT_MODE=perceptron`, then restart the worker.
2. Run at least **10 controlled trials per object** (from the app, or directly against the worker) and **write down the success rate**. The judges and our own honesty both need the real number (spec §13). One success is a valid prototype, but it isn't evidence of reliability.
3. **If it fails, look at how it fails.** If it goes the right way but misses the box, record 10–20 more episodes covering that case (for example, the box slightly further left) and retrain. That's the normal loop: record → train → test → record what's missing.

## 6. How it fits the dementia use case

- The agent offers **two choices only** (tea or coffee), and asks one short question at a time.
- The robot moves **only after** the backend has validated the choice. The UI says "done" **only after** the robot finishes *and* a caregiver confirms the box is in the tray (`REQUIRE_VERIFICATION=true`).
- On any failure the session goes to **needs staff**, with no automatic retries. Stop is always available, and the physical power switch is the real emergency stop.
- **Backup for the demo:** a taught sequence (`ROBOT_MODE=scripted`, see [robot_worker/README.md](../robot_worker/README.md)) or a pre-recorded video of the real policy, **clearly labelled** as such.
- **Later skills** (setting the table, sorting garden items) each get their own dataset and policy, plus an entry in the activity catalogue. Grok only ever picks from that catalogue.

## Troubleshooting

| Symptom | Fix |
|---|---|
| A motor shows **Overload** in Check motors | It strained against something. Clear the jaw or joint, unplug that arm's **DC power** (not USB) for 10 s, and let a hot motor cool. If it persists, ask in the team chat: we cleared a stale gripper target with a small script once. |
| `Missing motor IDs` when teleop starts | Same as above: that motor isn't answering. |
| No cameras / "not authorized" | Turn on Terminal in System Settings → Privacy & Security → Camera, quit Terminal (⌘Q) and restart the worker from it. |
| Wrist camera is black | Check that its cable is seated and that it isn't facing the gripper body. Look at it in the Studio previews. |
| Follower jumps when teleop starts | It snaps to the leader's pose. Hold the leader in roughly the follower's pose before you press Start. |
