"""Company-name normalisation.

The register is typed in by hand, so the same company can appear as
"CAKE GLORY LTD LTD", "Cake Glory Limited" or "cake glory ltd.". Many rows also
carry a trading name ("X LTD T/A Y", "X trading as Y", "X t/as Y"). We reduce every
name to a canonical key and keep each trading name as a separate alias, so a job
ad that only says "Y" still resolves to the licensed legal entity "X".
"""

from __future__ import annotations

import re
import unicodedata

# Split points between a legal name and a trading name.
_TRADING_SPLIT = re.compile(
    r"\s+(?:trading\s+as|t\s*/\s*as|t\s*/\s*a|t\.a\.|ta)\s+|\s+(?:t\s*/\s*a)\s*$",
    re.IGNORECASE,
)

# Legal-form words that carry no identifying information.
_LEGAL_SUFFIXES = {
    "ltd", "limited", "plc", "llp", "lp", "llc", "inc", "incorporated",
    "co", "company", "corp", "corporation", "pvt", "private", "cic", "cio",
}

# Words that only add noise when something more specific is present.
_NOISE = {"uk", "the", "trade", "name"}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _ascii_lower(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.lower().replace("&", " and ")


def canonical(name: str) -> str:
    """Reduce a company name to a comparable key.

    >>> canonical("F-Secure (UK) Limited")
    'f secure'
    >>> canonical("CAKE GLORY LTD LTD")
    'cake glory'
    """
    tokens = _NON_ALNUM.sub(" ", _ascii_lower(name)).split()
    kept = [t for t in tokens if t not in _LEGAL_SUFFIXES]
    meaningful = [t for t in kept if t not in _NOISE]
    return " ".join(meaningful or kept)


def split_trading_names(raw: str) -> list[str]:
    """Return the legal name followed by any trading names, as raw strings.

    >>> split_trading_names("Everest Kitchen Ltd T/A Gurkha Swindon")
    ['Everest Kitchen Ltd', 'Gurkha Swindon']
    """
    parts = [p.strip(" ,()-") for p in _TRADING_SPLIT.split(raw)]
    return [p for p in parts if p]


def aliases(raw: str) -> list[str]:
    """All canonical keys a register entry should be findable under (deduplicated, ordered)."""
    keys: list[str] = []
    for part in [raw, *split_trading_names(raw)]:
        key = canonical(part)
        if key and key not in keys:
            keys.append(key)
    return keys
