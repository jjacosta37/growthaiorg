"""X's weighted character count (twitter-text v3 rules), so limits match what X enforces:
URLs count as 23, most Latin/punctuation as 1, everything else (CJK, emoji…) as 2."""

import re

URL_WEIGHT = 23
URL_RE = re.compile(r"https?://\S+|\bwww\.\S+|\b[a-z0-9-]+\.(?:com|io|co|ai|app|org|net|dev)(?:/\S*)?", re.I)
# Code point ranges with weight 1 (from twitter-text's v3 config).
LIGHT_RANGES = [(0, 4351), (8192, 8205), (8208, 8223), (8242, 8247)]
EMOJI_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2})"  # flags
    "|(?:[\U0001F300-\U0001FAFF☀-➿](?:️)?(?:‍[\U0001F300-\U0001FAFF☀-➿](?:️)?)*)"
)


def _char_weight(ch: str) -> int:
    cp = ord(ch)
    return 1 if any(lo <= cp <= hi for lo, hi in LIGHT_RANGES) else 2


def x_length(text: str) -> int:
    total = 0
    pos = 0
    for m in URL_RE.finditer(text):
        total += _plain_length(text[pos:m.start()]) + URL_WEIGHT
        pos = m.end()
    return total + _plain_length(text[pos:])


def _plain_length(text: str) -> int:
    total = 0
    pos = 0
    for m in EMOJI_RE.finditer(text):  # an emoji sequence counts as 2, however many code points
        total += sum(_char_weight(c) for c in text[pos:m.start()]) + 2
        pos = m.end()
    return total + sum(_char_weight(c) for c in text[pos:])
