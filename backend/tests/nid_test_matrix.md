# Add extended NID intent test matrix (small_talk, greeting, proactive, cross-intents)

## Summary

This PR expands the natural intent detection (NID) test coverage by adding a structured test matrix for several key intents:
- `small_talk`
- `greeting_closing`
- `explicit_proactive_intent`
- various cross-intent edge cases (e.g., greeting + real question, clarification vs proactive, etc.)
The goal is to make the NID layer more “bulletproof” and to protect future refactors from regressions in common conversational patterns.

## Motivation
After introducing the `features` layer and fixing the affirmative/contact false positive, the NID core is much more robust. The next logical step is to:

- Validate that other high-level intents (small talk, greeting/closing, explicit proactive requests) are classified as expected.
- Ensure that ambiguous utterances (e.g., “hi, can you help me with my Joget process?”, “ok lanjut”, “can you explain it in simpler words?”) are routed to the correct intent and not misclassified as small talk/greeting/proactive by accident.
- Provide a clear, documented test matrix so future changes to `natural_intent.py` can rely on strong regression tests.

This PR does not change production behavior; it only adds tests to lock in the current contract.

# **What’s Included**

## 1. New parametrized tests for small_talk intent

Covers typical small talk scenarios such as:

- “how are you?”
- “lagi ngapain?”
- “that’s cool”
- “this is interesting”
- “are you human?”

These tests assert that detect_natural_intent(text)["intent"] == "small_talk" where appropriate, and that more “goal-oriented” questions are not treated as small talk.

### Small Talk – Test Matrix
| ID    | User Input              | Expected Intent                                    | Notes / Edge Case                                                               |
| ----- | ----------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------- |
| ST-01 | `how are you?`          | `small_talk`                                       | Short, pure chit-chat, question. Pastikan tidak dianggap clarification.         |
| ST-02 | `lagi ngapain?`         | `small_talk`                                       | Bahasa Indonesia, informal.                                                     |
| ST-03 | `that's cool`           | `small_talk`                                       | Komentar positif pendek, bukan pertanyaan.                                      |
| ST-04 | `this is interesting`   | `small_talk`                                       | Sentiment ringan, bukan pertanyaan.                                             |
| ST-05 | `you are very helpful`  | `small_talk` atau `feedback` (tergantung definisi) | Pilih satu yang konsisten. Kalau ada intent `feedback`, bisa diarahkan ke sana. |
| ST-06 | `you are stupid`        | `small_talk` atau `feedback`                       | Negative sentiment; kalau ada intent `feedback`, diarahkan ke sana.             |
| ST-07 | `can you explain more?` | **bukan** `small_talk` (mungkin `clarification`)   | Penting: kalimat seperti ini jangan jatuh ke small_talk meski pendek.           |
| ST-08 | `are you human?`        | `small_talk`                                       | Classic bot small talk.                                                         |

## 2. New tests for greeting_closing intent
Covers greetings and closings such as:
- “hi”, “hello”, “halo”
- “good morning”
- “see you later”, “thanks, bye”
Also includes at least one guard case like:
- “hello, I need help with Joget”
which must not be classified as greeting_closing only, but fall through to the normal/task-oriented intent.

### Greeting / Closing – Test Matrix
| ID    | User Input                         | Expected Intent                                                                | Notes / Edge Case                                                                            |
| ----- | ---------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| GR-01 | `hi`                               | `greeting_closing`                                                             | Short greeting; harus jelas.                                                                 |
| GR-02 | `hello`                            | `greeting_closing`                                                             | Basic.                                                                                       |
| GR-03 | `halo`                             | `greeting_closing`                                                             | Versi Indonesia.                                                                             |
| GR-04 | `good morning`                     | `greeting_closing`                                                             | Salam waktu.                                                                                 |
| GR-05 | `see you later`                    | `greeting_closing`                                                             | Closing.                                                                                     |
| GR-06 | `thank you`                        | `greeting_closing` atau `feedback`                                             | Pilih kebijakan: boleh treat sebagai greeting/closing atau feedback. Yang penting konsisten. |
| GR-07 | `thanks, bye`                      | `greeting_closing`                                                             | Kombinasi ucapan terima kasih + penutupan.                                                   |
| GR-08 | `good night, talk to you tomorrow` | `greeting_closing`                                                             | Closing panjang tapi jelas.                                                                  |
| GR-09 | `hello, I need help with Joget`    | **bukan hanya** `greeting_closing` (mungkin `non_retrieval_inquiry` / default) | Penting: greeting di depan tapi ada pertanyaan serius; jangan classify only greeting.        |

## 3. New tests for explicit_proactive_intent
Validates utterances that should explicitly trigger “what’s next / help me proceed” semantics, for example:

- “what should I do next?”
- “lanjut dong”
- “next step please”
- “can you give me more ideas?”
- “help me navigate this feature”

And also guard cases such as:
- “can you explain it in simpler words?”
which should be treated as clarification, not a generic proactive intent.

### Explicit Proactive Intent – Test Matrix
Ini intent yang memicu “bantu saya lanjut”, “apa langkah selanjutnya?”, dsb.
| ID    | User Input                                      | Expected Intent                                                 | Notes / Edge Case                                                           |
| ----- | ----------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------------------------------- |
| PR-01 | `what should I do next?`                        | `explicit_proactive_intent`                                     | Trigger klasik: minta langkah berikutnya.                                   |
| PR-02 | `lanjut dong`                                   | `explicit_proactive_intent`                                     | Pendek & jelas minta dilanjut.                                              |
| PR-03 | `next step please`                              | `explicit_proactive_intent`                                     | Bahasa campuran.                                                            |
| PR-04 | `bantu saya bikin checklist langkah-langkahnya` | `explicit_proactive_intent`                                     | Minta struktur/step.                                                        |
| PR-05 | `can you give me more ideas?`                   | `explicit_proactive_intent`                                     | Proaktif minta ide tambahan.                                                |
| PR-06 | `help me navigate this feature`                 | `explicit_proactive_intent`                                     | Sesuai frasa di rules-mu.                                                   |
| PR-07 | `can you repeat the last answer?`               | **bukan** `explicit_proactive_intent` (mungkin `clarification`) | Penting: jangan semua kalimat dengan “help” diperlakukan sebagai proactive. |
| PR-08 | `what else can I ask you?`                      | `explicit_proactive_intent`                                     | Good candidate untuk proactive tips.                                        |

## 4. Cross-intent and ambiguous case tests
Tests that ensure NID disambiguates correctly between similar-looking patterns:
- Greeting + real question:
 - “hi, can you help me with my Joget process?” → not only greeting_closing.
- Short confirmations:
 - “ok lanjut” / “ok, that makes sense” → treated as confirmation/affirmative (depending on context), not proactive or small talk.
- Clarification vs proactive:
 - “can you explain more?” / “can you explain it in simpler words?” → clarification, not small_talk or explicit_proactive_intent.
- Feedback:
 - “this answer is not helpful” → feedback.
 - “thanks, that was very clear” → feedback or greeting_closing, depending on current taxonomy, but consistent.


### Cross-Intent & Ambiguous Cases – Test Matrix
Ini penting untuk memastikan NID tidak bingung antara greeting/small_talk/proactive/clarification/feedback.
| ID   | User Input                                   | Expected Intent                                                                  | Kenapa penting                                                        |
| ---- | -------------------------------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| X-01 | `hi, can you help me with my Joget process?` | **bukan** `greeting_closing` (lebih ke `non_retrieval_inquiry` / default intent) | NID harus lihat bahwa setelah “hi” ada pertanyaan serius.             |
| X-02 | `ok lanjut`                                  | `affirmative` **atau** `explicit_proactive_intent` (pilih satu dan konsisten)    | Pendek dan kontekstual: sering muncul setelah bot menawarkan sesuatu. |
| X-03 | `ok, that makes sense`                       | `affirmative`                                                                    | Konfirmasi, bukan proactive.                                          |
| X-04 | `can you explain it in simpler words?`       | `clarification`                                                                  | Jangan jatuh ke `explicit_proactive_intent` atau `small_talk`.        |
| X-05 | `this answer is not helpful`                 | `feedback`                                                                       | Untuk memicu log kritik user.                                         |
| X-06 | `thanks, that was very clear`                | `feedback` atau `greeting_closing`                                               | Pilih kebijakan.                                                      |
| X-07 | `yo`                                         | `greeting_closing`                                                               | Slang, tapi sering dianggap salam.                                    |
| X-08 | `bro`                                        | `small_talk` atau `greeting_closing` (tergantung policy)                         | Perlu definisi yang konsisten.                                        |


## How to Use This Matrix in Testing (concept, not code)

use the table Test Matrix above as:
- Parametrized tests for detect_natural_intent(text):
 - Input: text
 - Expected: res["intent"] == expected_intent
 - Optional: check features (e.g., is_short, is_question).

- Test grouping structure (conceptual):
 - test_small_talk_intents → loop ST-01 .. ST-08
 - test_greeting_closing_intents → GR-01 .. GR-09
 - test_explicit_proactive_intent → PR-01 .. PR-08
 - test_cross_intent_disambiguation → X-01 .. X-08

With this matrix, every time you change the NID logic, you simply check:
- Are all the main intents still as expected?
- Are edge cases (like X-02, X-04, X-09) not leaking to the wrong intent?


# Scope and Non-Goals

- Scope
 - Add / extend tests under tests/ for NID.
 - Use the existing detect_natural_intent API.
 - Optionally assert selected features values for a few representative cases (e.g., is_short, is_question) when it helps clarify expected behavior.

- Non-Goals
 - No changes to natural_intent.py logic in this PR.
 - No changes to proactive controller, DPE, orchestrator, RuleInstance, or outbox.
 - No changes to the intent taxonomy (no new intent names).

Clear documentation (via tests) of how small talk, greeting/closing, proactive intent, and edge cases should be interpreted.

Makes future refactors to `natural_intent.py` safer and easier to reason about.