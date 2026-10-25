"""
Small Kannada-script helpers, no network and no model:

  has_kannada(text)      does the text contain Kannada letters?
  clean(text)            Kannada name tidied for storing and comparing (no zero-width joiners, single spaces)
  romanize(text)         rough Latin spelling of a Kannada word: ಬೆಳ್ತಂಗಡಿ -> "beltangadi"
  sounds_like(kn, en)    0..1, how well a Kannada name and an English (census) spelling agree

`romanize` is deliberately simple: it is only used to *compare* names (with the spelling-tolerant skeleton
from areas.py, which ignores vowels and aspiration), and to let people type a village name in Kannada even
when we have no Kannada name stored for it. It is not a transliteration for display.
"""
import re
import unicodedata
from difflib import SequenceMatcher

KANNADA = re.compile(r"[ಀ-೿]")
VIRAMA, ANUSVARA, VISARGA, NUKTA = "್", "ಂ", "ಃ", "಼"

VOWELS = {"ಅ": "a", "ಆ": "aa", "ಇ": "i", "ಈ": "ee", "ಉ": "u", "ಊ": "oo", "ಋ": "ru", "ಎ": "e", "ಏ": "e",
          "ಐ": "ai", "ಒ": "o", "ಓ": "o", "ಔ": "au"}
SIGNS = {"ಾ": "aa", "ಿ": "i", "ೀ": "ee", "ು": "u", "ೂ": "oo", "ೃ": "ru", "ೆ": "e", "ೇ": "e", "ೈ": "ai",
         "ೊ": "o", "ೋ": "o", "ೌ": "au"}
CONSONANTS = {"ಕ": "k", "ಖ": "kh", "ಗ": "g", "ಘ": "gh", "ಙ": "n",
              "ಚ": "ch", "ಛ": "chh", "ಜ": "j", "ಝ": "jh", "ಞ": "n",
              "ಟ": "t", "ಠ": "th", "ಡ": "d", "ಢ": "dh", "ಣ": "n",
              "ತ": "t", "ಥ": "th", "ದ": "d", "ಧ": "dh", "ನ": "n",
              "ಪ": "p", "ಫ": "ph", "ಬ": "b", "ಭ": "bh", "ಮ": "m",
              "ಯ": "y", "ರ": "r", "ಱ": "r", "ಲ": "l", "ವ": "v", "ಶ": "sh", "ಷ": "sh", "ಸ": "s", "ಹ": "h",
              "ಳ": "l", "ೞ": "l"}
DIGITS = {chr(0x0CE6 + i): str(i) for i in range(10)}


def has_kannada(text: str | None) -> bool:
    return bool(text and KANNADA.search(text))


def clean(text: str | None) -> str:
    """NFC, no zero-width (non-)joiners, single spaces, trimmed."""
    s = unicodedata.normalize("NFC", text or "").replace("‌", "").replace("‍", "")
    return re.sub(r"\s+", " ", s).strip()


def romanize(text: str) -> str:
    s = clean(text)
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in CONSONANTS:
            out.append(CONSONANTS[ch])
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt == NUKTA:                               # ಫ಼ = f, ಜ಼ = z: rare in village names
                out[-1] = {"ph": "f", "j": "z"}.get(out[-1], out[-1])
                i += 1
                nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt in SIGNS:
                out.append(SIGNS[nxt])
                i += 1
            elif nxt == VIRAMA:
                i += 1                                     # dead consonant: no vowel
            else:
                out.append("a")                            # inherent vowel
        elif ch in VOWELS:
            out.append(VOWELS[ch])
        elif ch == ANUSVARA:
            nxt = s[i + 1] if i + 1 < len(s) else ""
            out.append("m" if (not nxt or nxt in "ಪಫಬಭಮ " or not KANNADA.search(nxt)) else "n")
        elif ch == VISARGA:
            out.append("h")
        elif ch in DIGITS:
            out.append(DIGITS[ch])
        elif ch in (VIRAMA, NUKTA) or ch in SIGNS:
            pass                                           # stray mark
        else:
            out.append(ch)                                 # space, bracket, Latin letters
        i += 1
    return "".join(out)


def sounds_like(kn: str, en: str) -> float:
    """Agreement of a Kannada name with an English spelling on the spelling-tolerant skeleton (0..1).
    Census spellings vary a lot ("Beltangadi", "Belthangady"), the skeleton absorbs most of that."""
    from .areas import _skeleton                           # one skeleton for search and for this check
    a, b = _skeleton(romanize(kn)), _skeleton(en)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
