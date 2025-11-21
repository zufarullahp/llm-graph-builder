import src.natural_intent as ni

text = 'you are stupid'
tl = text.lower()
print('tl:', tl)
print('_contains_word greetings:', ni._contains_word(tl, ["hi","hello","yo","bro"]))
print('_contains_any greetings:', ni._contains_any(tl, ["hi","hello","yo","bro"]))
print('_contains_word closings:', ni._contains_word(tl, ["bye","see you","thanks"]))
print('_contains_any closings:', ni._contains_any(tl, ["bye","see you","thanks"]))
print('match any of good night/talk to you/see you later:', ni._contains_any(tl, ["good night","talk to you","see you later"]))
