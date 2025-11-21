from src.natural_intent import detect_natural_intent

cases = [
    "how are you?",
    "lagi ngapain?",
    "you are stupid",
    "are you human?",
    "good morning",
    "thank you",
    "thanks, bye",
    "good night, talk to you tomorrow",
    "bantu saya bikin checklist langkah-langkahnya",
    "what else can I ask you?",
    "bro",
]

for c in cases:
    r = detect_natural_intent(c)
    print(c, "->", r)
