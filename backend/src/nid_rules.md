0. Shared normalization & helpers

Normalization (run once at start):

text_raw = original user text

text = normalized:

.strip()

collapse multiple spaces → single space

convert to lowercase

optional: remove zero-width / control chars

tokens = text.split()

char_len = len(text)

token_len = len(tokens)

has_question_mark = "?" in text_raw

Useful helpers:

is_short_utterance: token_len <= 4 and char_len <= 40

contains_any(text, phrases: list[str]) -> bool

starts_with_any(text, prefixes: list[str]) -> bool

Regex patterns (pseudo):

EMAIL_REGEX = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"

PHONE_REGEX = r"\b(\+?\d[\d\s\-]{6,})\b"
(simple: +62 xxx, 08xx, etc.)

NAME_PATTERNS (phrases):

"my name is ", "nama saya ", "saya bernama ", "gue " + name? (optional for v1)"

Attachment metadata (from API):

Input to detector can include has_attachment: bool, attachment_types: list[str].

1. Global precedence (important)

If multiple rules match, apply this priority:

no_content

upload_attachment

contact_sharing

task_meta

explicit_proactive_intent

clarification

feedback

small_talk / greeting

personal_context

non_retrieval_inquiry

fallback → unknown (→ RAG)

So Copilot should check intents roughly in this order.

2. Intent: Contact Sharing

Goal: detect when user shares email / phone / name / contact channel.

Detection rules:

A. Email present

EMAIL_REGEX matches AND

text contains any of:

"my email", "this is my email", "you can email me", "contact me at",

"ini email saya", "email saya", "boleh kirim ke", "kirim ke email".

If email in context of a question like
"apakah email ini sudah terdaftar?" → lower confidence or fall back to unknown:

heuristic: if has_question_mark and phrases like "sudah terdaftar", "valid?", "bener?" then do not classify as contact_sharing (set unknown).

B. Phone/WhatsApp present

PHONE_REGEX matches AND text contains any of:

"my phone", "my number", "call me at", "whatsapp me",

"no hp saya", "nomor saya", "wa saya", "hubungi saya di", "kontak saya di".

C. Name introduction (weaker rule)

text contains NAME_PATTERNS:

"my name is ", "nama saya ", "saya bernama ".

Slots to extract:

slots["email"] = first EMAIL_REGEX match or None

slots["phone"] = first PHONE_REGEX match or None

slots["name"] = extracted substring after "my name is "/"nama saya " up to punctuation/end

Confidence:

email or phone + clear pattern → 0.9+

name only → 0.6–0.8

requires_retrieval = False (always in v1)

3. Intent: Small Talk / Social

Goal: “thanks / ok / chit-chat” where no real task.

Detection rules:

is_short_utterance == True

text in or contains any of these exact or near-exact matches (after normalization):

EN:

"ok", "okay", "okey", "k", "thx", "thanks", "thank you",

"great", "nice", "awesome", "cool", "perfect",

"that's it", "all good".

ID:

"makasih", "terima kasih", "trimakasih",

"sip", "siap", "mantap", "keren", "oke",

"sudah cukup", "udah cukup", "gitu aja".

If text also contains clear task verbs ("lanjut", "next", "what next") then do NOT classify as small talk (maybe explicit_proactive_intent instead).

Slots: none.

Confidence: high (0.9+) if short and exact match.

**requires_retrieval = False`.

4. Intent: Clarification

Goal: user asks to clarify previous explanation, without giving new domain content.

Detection rules:

Text contains any of:

EN:

"what do you mean", "what does that mean",

"explain more", "explain again",

"explain more simply", "simpler explanation",

"what is an example", "give me an example",

"can you elaborate", "please elaborate".

ID:

"maksudnya apa", "maksudnya gimana",

"jelaskan lagi", "boleh dijelasin lagi", "jelasin dong",

"lebih simpel", "jelaskan dengan sederhana",

"contohnya apa", "contoh dong", "kasih contoh".

Heuristics:

Usually short or medium-length; may contain "?".

Should not contain domain-specific new nouns like "Pelni", "Joget DX 8", "Neo4j" etc. For v1 you can skip this check; or treat long, content-heavy questions as not-clarification.

Slots:

Maybe slots["clarification_type"] = "example" | "simplify" | "repeat" based on phrase.

Confidence:

If any of the strong phrases exist → 0.8+.

requires_retrieval = False (use last answer + LLM).

5. Intent: Task Meta

Goal: system-level commands, not domain questions.

Detection rules:

Look for imperative commands, especially at start of string:

EN commands:

"save this", "save conversation", "save session",

"clear history", "delete session", "reset chat", "start over",

"change mode", "set mode", "toggle proactive on", "toggle proactive off",

"turn off proactive", "turn on proactive",

"disable suggestions", "enable suggestions".

ID commands:

"hapus sesi", "hapus riwayat", "reset chat", "mulai dari awal",

"ganti mode", "ubah mode",

"matikan mode proaktif", "nyalakan mode proaktif",

"nonaktifkan proaktif", "aktifkan proaktif".

Heuristics:

often start with a verb: "save", "delete", "clear", "reset", "hapus", "ganti", etc.

not phrased as a question (no "?") in most cases; but allow "can you delete my session?" as Task Meta if contains both "delete" + "session".

Slots:

slots["command"] = normalized command string, e.g. "clear_history", "toggle_proactive_off".

Confidence: high when verb + known object (session, history, mode).

requires_retrieval = False.

6. Intent: Feedback

Goal: user reacts to answer quality: wrong / unclear / ask to repeat.

Detection rules:

EN phrases:

"that's wrong", "not correct", "incorrect",

"that’s not right", "i disagree",

"the answer isn't clear", "not clear", "unclear",

"repeat", "say it again", "can you repeat".

ID phrases:

"itu salah", "jawabannya salah", "nggak bener", "ga bener",

"tidak tepat", "kurang tepat",

"tidak jelas", "kurang jelas", "nggak jelas", "ga jelas",

"ulang lagi", "ulang jawabannya", "ulang dong".

Heuristics:

Often short / medium; may or may not contain "?".

If combined with a new question (e.g. "jawaban tadi kurang jelas, jelaskan cara deploy di AWS") → still feedback intent but you might set requires_retrieval = True later; for v1 you can keep requires_retrieval = False and rely on previous context.

Slots:

slots["feedback_type"] = "wrong" | "unclear" | "repeat" based on phrase.

Confidence: high if any phrase matches.

7. Intent: Personal Context

Goal: user tells you about themselves / their situation, not asking a direct question.

Detection rules (heuristic):

Contains first-person pronouns:

EN: "i ", "i'm ", "im ", "my ", "me ".

ID: "saya ", "aku ", "gue ", "gw ", "klien saya", "client saya".

AND length is medium/long: token_len >= 8.

AND either:

no question mark, or

question mark only at the end but most of sentence is descriptive (for v1 you can just allow has_question_mark == False).

Example patterns:

"i'm working on an office assignment about X",

"my client is Pelni and we use Joget DX 7",

"saya lagi ngerjain tugas kantor",

"klien saya perusahaan BUMN dan pakai versi joget lama".

Slots:

For v1, you can just store slots["raw_context"] = text_raw.

Future: extract client, tech_stack, etc.

Confidence: medium (0.6–0.8), requires_retrieval = False.

8. Intent: Greeting / Closing

Goal: “Hi”, “Bye”, “Good morning”, etc.

Detection rules:

Greeting keywords:

EN:

"hi", "hello", "hey",

"good morning", "good afternoon", "good evening".

ID:

"halo", "hallo", "selamat pagi", "selamat siang", "selamat sore", "selamat malam",

"assalamualaikum".

Closing keywords:

EN:

"bye", "goodbye", "see you", "see ya", "talk to you later".

ID:

"sampai jumpa", "makasih ya", "terima kasih banyak", "sekian", "cukup sekian".

Heuristics:

Very short, token_len <= 6.

If the message is only greeting/closing words (maybe with small talk like "hi, good morning"), classify as greeting intent.

If combined with a real question ("hi, how do I deploy Joget?") → treat as normal RAG (or detect both greeting + RAG; but for classifier, set intent="unknown" and let RAG run).

Slots: maybe slots["greeting_type"] = "open" | "close".

**requires_retrieval = False` for pure greeting/closing.

9. Intent: Non-Retrieval Information Inquiry

Goal: questions about bot / service / pricing / capabilities, not about graph docs.

Detection rules:

Look for:

Question mark present OR typical question phrases "how do i", "can you", "could you", "apa itu", "bagaimana cara".

AND content refers to bot/system, not specific corpus:

English patterns:

"how do i use this bot", "how does this bot work",

"can you help me", "what can you do",

"how much do you charge", "what is the price", "how much is your fee".

Indonesian patterns:

"bagaimana cara pakai bot ini", "cara menggunakan bot ini",

"bisa bantu apa saja", "fungsi bot ini apa",

"berapa biaya", "harga berapa", "berapa tarif".

Heuristics:

Contains terms: "bot", "kamu", "you", "service", "harga", "biaya", "produk".

Does not mention specific domain entities/IDs from your graph (like "Neo4j node", "Pelni SOP" etc.) – but v1 can skip this.

Slots:

slots["topic"] = "pricing" | "capabilities" | "usage" based on keyword.

requires_retrieval = False (hard-coded/system docs or LLM-only).

10. Intent: Upload / Attachment

Goal: user sends or refers to a file/image.

Detection rules:

A. Metadata-based (strong):

If has_attachment == True → upload_attachment (unless text is obviously about something else, but v1: always treat as upload intent).

B. Text-based:

Text contains any of:

EN:

"here is the file", "here's the file",

"here is the pdf", "here's the pdf",

"i upload a file", "i uploaded a file",

"please analyze this file", "please analyze this image".

ID:

"ini file nya", "ini filenya",

"ini pdf nya", "ini pdfnya",

"saya upload file", "sudah saya upload file",

"tolong analisa file ini", "tolong analisa gambar ini".

Slots:

slots["has_attachment"] = has_attachment

slots["attachment_types"] = attachment_types

requires_retrieval = False (route to file processor).

11. Intent: Explicit Proactive Intent

Goal: user explicitly asks the bot to be more “driving”.

Detection rules:

Text contains any of:

EN:

"help me navigate", "guide me", "guide me step by step",

"what's next", "what is the next step", "what should i do next",

"give me more ideas", "give me further ideas".

ID:

"bantu saya langkah demi langkah", "pandunya step by step",

"lanjut", "lanjut dong", "lanjut gimana", "step selanjutnya apa",

"kasih ide lagi", "kasih rekomendasi lagi".

Heuristics:

Can appear after an answer, often referencing “next step”.

Might coexist with real questions and still require retrieval.

Slots:

slots["proactive_strength"] = "strong" (for DPE).

requires_retrieval:

For v1, set:

If only “lanjut” / “what’s next” → requires_retrieval = False (use last context + DPE).

If combined with new domain question → requires_retrieval = True.

12. Intent: No-Content / Empty

Goal: blank, only whitespace, or trivial content (e.g. only emoji).

Detection rules:

text_raw.strip() == "" → true.

OR text is extremely short and all chars are in set of emojis / punctuation like "...", "??", "!!", etc.:

e.g., token_len == 0 or char_len <= 3 and no alphabetic characters.

Slots: none.

**requires_retrieval = False`.