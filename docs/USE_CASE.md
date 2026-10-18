# Primary use case: one nurse, a room of residents living with dementia

> ReMind supports engagement. It is not a diagnostic or treatment tool, has not been clinically tested, and does not claim to improve memory or slow dementia.

## The problem, in numbers

| Fact | Figure | Source |
| --- | --- | --- |
| People living with dementia worldwide | 55+ million (2021), rising to 78 million by 2030 and 139 million by 2050 | WHO, via [PAHO 2021](https://www.paho.org/en/news/2-9-2021-world-failing-address-dementia-challenge) |
| New cases each year, worldwide | nearly 10 million | WHO fact sheet, summarised by [NIHR Dementia Researcher](https://www.dementiaresearcher.nihr.ac.uk/who-dementia-statistics/) |
| Americans 65+ with Alzheimer's dementia | 7.2 million (2025) | [Alzheimer's Association 2025 Facts and Figures](https://www.alz.org/getmedia/c05f7ba4-9aea-4cb0-8898-5e8bff3f0930/executive-summary-2025-alzheimers-disease-facts-and-figures.pdf) |
| US nursing home residents living with Alzheimer's or another dementia | 41.1% (2022) | [CDC FastStats](https://www.cdc.gov/nchs/fastats/alzheimers.htm) |
| Nursing homes with open jobs | 99%; 72% still below pre-pandemic staffing | [AHCA 2024 State of the Sector](https://ahcancal.org/News-and-Communications/Press-Releases/Pages/State-Of-The-Sector-Nursing-Home-Staffing-Shortages-Persist-Despite-Unprecedented-Efforts-To-Attract-More-Staff-.aspx) |
| Waking day residents with dementia spend doing nothing | 47.5% (7 am to 7 pm, observed) | [BMC Geriatrics 2024](https://link.springer.com/article/10.1186/s12877-024-05641-7) |

Other observation studies put inactivity at roughly 45–70% of the day, depending on how it is measured.

**In one line:** almost half the people in a nursing home live with dementia, they spend about half their waking day doing nothing, and almost every home is short of the staff who could sit with them.

## Who it is for

- **Resident:** someone with mild-to-moderate dementia in a care home. Wants something pleasant to do and someone to talk to. No tests, no scores, no feeling of failure.
- **Nurse or care aide:** responsible for many residents at once. Needs to start an activity in seconds, step away, and know when to come back.
- **Family:** wants to know that their person had a good day, and to be told when something is wrong.

## The scenario

1. The nurse opens a resident's profile on the nurse screen and starts a session. ReMind already knows the resident's name, family, work and favourite things from earlier sessions (only with consent).
2. ReMind greets the resident by name on the patient screen and chats warmly. It offers activities from the catalog: famous faces, finishing a saying, everyday sounds (screen games), or **Remember the Order** with the robot arm.
3. **Remember the Order:** three keyrings in a row. They say the order together, the SO-101 arm mixes them up, and the resident puts them back. The camera follows the table, so ReMind can say "yes, the black one goes on the left" when it's right. When the resident hesitates, it offers a two-way choice, never "wrong". If they'd like, the robot shows the answer.
4. The nurse is elsewhere. If the resident says something concerning ("I've fallen", "where am I?", "I want to go home"), ReMind texts the caregiver straight away (Photon), with a short plain summary.
5. Afterwards the nurse sees engagement notes ("talked about seeing Elvis films with her sister"; "restored the row with one choice"). These are facts, not a score.

## Why a robot arm, and not just a tablet

- **Real objects.** Cognitive Stimulation Therapy, the best-evidenced non-drug activity for mild-to-moderate dementia, recommended by [NICE NG97](https://www.nice.org.uk/guidance/ng97), works with real, familiar objects. A screen can't be picked up.
- **Someone has to move them.** For the memory game, the objects must be mixed up while the resident watches. Today that is a staff member's time. The arm does it, so one nurse can run activities for several residents.
- **Consistent and safe.** The same five trained shuffles every time, checked by the camera. The arm clamps every motion to safe joint limits and pauses whenever a hand is on the table. A physical emergency stop is always within reach.

## Why this game suits people living with dementia

Built from established methods (details and references in [EXERCISE_FIND_AND_REMEMBER.md](EXERCISE_FIND_AND_REMEMBER.md)):

- **Errorless learning:** support before an error can stick; choices of two; show the answer together.
- **Spaced retrieval:** a later "which one was on the left at the very start?", spaced further apart after success.
- **Reminiscence:** an optional, skippable memory question about an object.
- **CST principles:** themed, enjoyable, social, opinions over facts.

These methods are evidence-based; ReMind's combination of them has not been evaluated. The next step would be a usability and acceptability pilot with a care home and an occupational therapist, before any claim of benefit.

## What we measure (and don't)

- **We record:** which activities were played, engagement (engaged / some / withdrawn), short notes, and how a row was restored (alone / with a choice / together).
- **We never record:** scores, response times, or anything presented as a measure of memory or decline.
