# Planning: Provenance Guard

## 1. Detection signals

**Signal 1 — LLM-based classification (Groq, `llama-3.3-70b-versatile`)**
Measures: holistic semantic/stylistic coherence — voice, idiosyncrasy, generic
transitions, hedging language, uniform rhythm. The kind of judgment a careful
human reader forms after reading the whole passage.
Output shape: float `ai_likelihood` in `[0.0, 1.0]`, plus a one-sentence
`reasoning` string, parsed from a JSON response.
Blind spot: can be fooled by AI text that's been lightly edited by a human
("borderline_edited_ai" case), or by human writing that happens to be very
formal and even in tone ("borderline_formal_human" case). It's also the only
signal that costs an API call, so it's the single point of failure if Groq is
down — the pipeline falls back to a neutral 0.5 rather than guessing.

**Signal 2 — Stylometric heuristics (pure Python)**
Measures two structural properties:
- Sentence-length coefficient of variation (CV) — AI text tends toward more
  uniform sentence lengths than human writing.
- Type-token ratio (TTR) — unique words / total words. AI text tends to reuse
  a narrower vocabulary relative to length.
Output shape: float `ai_likelihood` in `[0.0, 1.0]` (average of two sub-scores
built by linearly mapping CV and TTR into `[0,1]`), plus a `metrics` dict with
the raw numbers.
Blind spot: both metrics are noisy on short passages (under a couple dozen
words / fewer than 2 sentences) — in that case the signal reports 0.5
("uncertain") rather than guessing. TTR also naturally drops as *any* text
gets longer, independent of authorship.

These two signals are genuinely independent: one reads the text as a whole
via a language model, the other only ever measures counts and ratios. That's
why they're combined rather than either being used alone.

**Combination:** weighted average, `confidence = 0.85 * llm_score + 0.15 * style_score`.
The LLM is weighted far higher because it's more reliable in general and
especially on short passages where the stylometric signal is intentionally
conservative. The stylometric signal's remaining 15% weight is enough to pull
a confident-but-wrong LLM verdict toward "uncertain" without being able to
flip the verdict outright — it's a check, not a co-equal vote.

## 2. Uncertainty representation

The combined `confidence` score is interpreted as **AI-likelihood**, not
"correctness": `0.0` = confident human, `1.0` = confident AI, `0.5` = the
signals found nothing decisive either way. A `0.6` means "leans slightly
toward AI-generated, but not strongly" — it is not rounded to a binary verdict
anywhere in the pipeline; the raw float is stored and returned alongside the
category.

**Thresholds** (deliberately asymmetric):

| Attribution | Condition |
|---|---|
| `likely_ai` | `confidence >= 0.80` |
| `likely_human` | `confidence <= 0.25` |
| `uncertain` | everything in between |

A false positive (calling a human's work AI-generated) is more damaging to a
creator than a false negative, so the system requires *more* evidence
(distance from the 0.5 midpoint: 0.30) before declaring `likely_ai` than it
does before declaring `likely_human` (distance from midpoint: 0.25). This
widens the "uncertain" band and skews it in the direction that protects human
creators from being wrongly flagged.

## 3. Transparency label design

Three fixed label strings, one per attribution category. Exact text (also
duplicated verbatim in README.md):

**High-confidence AI:**
> Likely AI-generated. Our system found strong, consistent signals across independent checks suggesting this content was created by an AI tool. This is an automated estimate, not a certainty — if this is your original work, you can request a review.

**High-confidence human:**
> Likely human-written. Our system did not find strong signals of AI generation in this content. As with all automated detection, this is an estimate based on available signals, not a guarantee.

**Uncertain:**
> Uncertain. Our system could not confidently determine whether this content is AI-generated or human-written. Please treat this classification as inconclusive rather than a verdict.

Design notes: every variant explicitly names itself as an *estimate*, never a
verdict — including the confident ones — because AI detection is not a solved
problem and the label shouldn't imply more certainty than the underlying
signals support. The AI-generated variant is the only one that mentions the
appeal path directly, since that's the case where a wrong call costs a
creator the most.

## 4. Appeals workflow

- **Who:** the creator associated with the submission (identified by
  `creator_id` on the original `/submit` call — no separate auth layer in
  this project).
- **What they provide:** `content_id` of the disputed submission and
  `creator_reasoning` (free text — why they believe the classification is
  wrong).
- **What the system does:** looks up the submission by `content_id`, flips its
  `status` to `under_review`, and writes a new `audit_log` entry with
  `event_type = "appeal"` that carries the original attribution/confidence/
  signal scores *and* the appeal reasoning, so the full history is visible in
  one place. No automated re-classification happens.
- **What a human reviewer would see:** querying `GET /log` (or the
  `submissions` table directly) surfaces, for a given `content_id`, the
  original classification entry immediately followed by the appeal entry —
  giving the reviewer the original signals, the label that was shown to the
  reader, and the creator's stated reasoning, side by side.

## 5. Anticipated edge cases

1. **Formal, even-toned human writing** (e.g. academic or technical prose).
   Low sentence-length variance and moderate-to-low TTR can push the
   stylometric signal toward "AI-like" even though the author is human — this
   is exactly the `borderline_formal_human` test case, and it's why the LLM
   signal is weighted far higher than the stylometric one.
2. **Lightly-edited AI output.** A human rewrites a few AI-generated sentences
   in their own voice; the LLM signal may still catch generic structure, but
   confidently, while the stylometric signal reads mixed results. The system
   is designed to land these in "uncertain" rather than force a binary call —
   see the `borderline_edited_ai` test case.
3. **Very short submissions** (a haiku, a two-line caption). Neither signal
   has enough material to say anything meaningful; the stylometric signal
   explicitly detects this (fewer than 2 sentences or 5 words) and reports a
   neutral 0.5 rather than extrapolating from noise.
4. **Non-native-English or heavily accented prose style.** Unusual but
   internally consistent grammar or word choice can read as "unnatural" to an
   LLM judging fluency, risking a false "AI-generated" call on a human
   creator — this is the scenario used in the sample appeal (see README).

## Architecture

```
                          SUBMISSION FLOW
                          ---------------

  Client                                                Provenance Guard
    |                                                            |
    |  POST /submit {text, creator_id}                          |
    |----------------------------------------------------------->|
    |                                                            |
    |                                          +-----------------v----------------+
    |                                          |  Signal 1: LLM (Groq)             |
    |                                          |  -> ai_likelihood (0-1) + reason  |
    |                                          +-----------------+----------------+
    |                                                            |
    |                                          +-----------------v----------------+
    |                                          |  Signal 2: Stylometric heuristics |
    |                                          |  -> ai_likelihood (0-1) + metrics |
    |                                          +-----------------+----------------+
    |                                                            |
    |                                          +-----------------v----------------+
    |                                          |  combine_signals()                |
    |                                          |  0.85*llm + 0.15*style ->confidence|
    |                                          +-----------------+----------------+
    |                                                            |
    |                                          +-----------------v----------------+
    |                                          |  labels.classify(confidence)      |
    |                                          |  -> attribution + label text      |
    |                                          +-----------------+----------------+
    |                                                            |
    |                                          +-----------------v----------------+
    |                                          |  storage.save_submission()        |
    |                                          |  -> writes `submissions` row      |
    |                                          |  -> writes `audit_log` entry      |
    |                                          |     (event_type=classification)   |
    |                                          +-----------------+----------------+
    |                                                            |
    |  200 {content_id, confidence, attribution, label, signals} |
    |<-----------------------------------------------------------|


                            APPEAL FLOW
                            -----------

  Client                                                Provenance Guard
    |                                                            |
    |  POST /appeal {content_id, creator_reasoning}              |
    |----------------------------------------------------------->|
    |                                          +-----------------v----------------+
    |                                          |  storage.get_submission()         |
    |                                          |  (404 if content_id unknown)      |
    |                                          +-----------------+----------------+
    |                                                            |
    |                                          +-----------------v----------------+
    |                                          |  storage.file_appeal()            |
    |                                          |  -> submissions.status =          |
    |                                          |     "under_review"                |
    |                                          |  -> writes `audit_log` entry      |
    |                                          |     (event_type=appeal,           |
    |                                          |      carries original scores +    |
    |                                          |      creator_reasoning)           |
    |                                          +-----------------+----------------+
    |                                                            |
    |  200 {content_id, status: under_review, message}          |
    |<-----------------------------------------------------------|
```

A submission passes through both detection signals independently, gets
combined into a single confidence score, mapped to one of three labels, and
persisted with a matching audit-log entry — all before the response is sent.
An appeal never re-runs detection; it only updates status and appends a
linked audit-log entry so a reviewer can see the original decision and the
creator's objection together.

## AI Tool Plan

**M3 — submission endpoint + first signal:**
Provide the "Detection signals" section above (Signal 1 description) plus the
submission-flow half of the architecture diagram. Ask for: a Flask app
skeleton with a `POST /submit` route stub, and a standalone `llm_signal(text)`
function matching the described output shape (`{"score": float, "reasoning":
str}`). Verify by calling `llm_signal()` directly on 2-3 sample strings before
wiring it into the route, and checking the route returns valid JSON with a
hardcoded placeholder confidence before the signal is connected.

**M4 — second signal + confidence scoring:**
Provide the "Detection signals" + "Uncertainty representation" sections plus
the full diagram. Ask for: a standalone `stylometric_signal(text)` function
computing sentence-length CV and TTR, and a `combine_signals()` function
implementing the weighted average with the exact thresholds from the
"Uncertainty representation" table. Verify by running the four provided test
inputs (clearly AI, clearly human, two borderline) and confirming the
combined scores land in the buckets described in that section — if not,
print both signal scores separately to find which one is off, then adjust
weights (this is exactly what happened during implementation — see README's
spec reflection).

**M5 — production layer:**
Provide the "Transparency label design" + "Appeals workflow" sections plus
the diagram. Ask for: a `label_for(attribution)` function returning the three
exact strings from the label design section, and the `POST /appeal` route
implementing the described status-update + audit-log-append behavior. Verify
by calling `label_for()` for all three attribution values and diffing against
the spec text character-for-character, and by submitting a test appeal then
confirming `GET /log` shows a `status: under_review` entry with
`appeal_reasoning` populated.
