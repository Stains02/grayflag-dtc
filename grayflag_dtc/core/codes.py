"""CP codes: short (ideally 3-letter) labels derived deterministically from CP names.

Rules in order (docs/DESIGN.md, "CP codes"): override, generic name, dictionary, compose, per-objective
uniqueness (load time). Two CPs in different objectives may share a code. Same input always
gives the same codes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..paths import RES, data_dir
from .dataset import Dataset, Objective

VOWELS = set("AEIOU")


@dataclass
class CodeConfig:
    words: dict[str, str] = field(default_factory=dict)
    generic_names: set[str] = field(default_factory=lambda: {"capture point"})
    digit_fallback: bool = True       # False: use letters instead of digits for uniqueness suffixes
    max_len: int = 3

    @classmethod
    def load(cls, max_len: int = 3) -> "CodeConfig":
        raw = json.loads((RES / "config" / "code_dictionary.json").read_text(encoding="utf-8"))
        return cls(words={k.upper(): v.upper() for k, v in raw.get("words", {}).items()},
                   generic_names={n.strip().lower() for n in raw.get("generic_names", [])},
                   digit_fallback=raw.get("digit_fallback", True), max_len=max_len)


@dataclass
class CodeResult:
    cp_id: str
    code: str
    rule: str                  # override | generic | dictionary | one-word | two-word | multi-word
    note: str = ""             # collision handling, e.g. "was SE"
    base: str = ""             # code before uniqueness handling


def tokens(name: str) -> list[str]:
    """Uppercase, split on spaces and hyphens, drop punctuation."""
    parts = re.split(r"[\s\-]+", name.upper())
    return [t for t in (re.sub(r"[^A-Z0-9]", "", p) for p in parts) if t]


def _consonants(word: str) -> list[str]:
    return [c for c in word[1:] if c not in VOWELS]


def objective_prefix(name: str) -> str:
    """2 letters: initials of the first two words, or first letter + next consonant for one word."""
    t = tokens(name)
    if not t:
        return "XX"
    if len(t) >= 2:
        return (t[0][0] + t[1][0])
    w = t[0]
    cons = _consonants(w)
    return w[0] + (cons[0] if cons else (w[1] if len(w) > 1 else "X"))


def _letters_pad(word: str, picked: str, n: int) -> str:
    """Pad a short code to n chars with the word's vowels in order (after the first letter)."""
    out = picked
    for c in word[1:]:
        if len(out) >= n:
            break
        if c in VOWELS:
            out += c
    return out[:n]


def compose(name: str, cfg: CodeConfig) -> tuple[str, str, list[str]]:
    """(base code, rule, alternative third characters) for a non-generic, non-override name."""
    toks = tokens(name)
    n = cfg.max_len
    if not toks:
        return "", "generic", []
    if len(toks) == 1:
        w = toks[0]
        if w in cfg.words:
            return cfg.words[w][:n], "dictionary", []
        cons = _consonants(w)
        base = w[0] + "".join(cons[: n - 1])
        if len(base) < n:
            base = _letters_pad(w, base, n)
        alts = [c for c in cons[n - 1:]]
        return base[:n], "one-word", alts
    if len(toks) == 2:
        initials = [cfg.words.get(t, t[0]) for t in toks]
        last = toks[1]
        cons = _consonants(last)
        third = cons[0] if cons else (last[1] if len(last) > 1 else "")
        base = ("".join(initials) + (third if last not in cfg.words else ""))[:n]
        return base, "two-word", cons[1:] if third else []
    return "".join(t[0] for t in toks[:3])[:n], "multi-word", []


def _suffix_variants(base: str, cfg: CodeConfig):
    """Digit (or letter) suffixed variants: append while there is room, else replace trailing chars."""
    n = cfg.max_len
    i = 2
    while i < 100:
        s = str(i) if cfg.digit_fallback else chr(ord("A") + i - 2) if i < 28 else None
        if s is None:
            return
        cut = n - len(s)
        yield (base[:cut] if len(base) + len(s) > n else base) + s
        i += 1


def _candidates(base: str, alts: list[str], cfg: CodeConfig):
    seen = set()
    for c in [base] + [base[:-1] + a for a in alts if base]:
        if c and c not in seen:
            seen.add(c)
            yield c
    for c in _suffix_variants(base, cfg):
        if c not in seen:
            seen.add(c)
            yield c


def _pick(base: str, alts: list[str], used: set[str], cfg: CodeConfig) -> str:
    for c in _candidates(base, alts, cfg):
        if c not in used:
            return c
    raise RuntimeError(f"no free code for {base!r}")


def generate_objective_codes(obj: Objective, cfg: CodeConfig, overrides: dict[str, str] | None = None
                             ) -> dict[str, CodeResult]:
    """Codes for every CP of one objective, unique within it. Keyed by CP zone id."""
    overrides = {k: v.upper() for k, v in (overrides or {}).items()}
    out: dict[str, CodeResult] = {}
    used: set[str] = {v for cp in obj.cps for k, v in overrides.items() if k == cp.id}
    prefix = objective_prefix(obj.name)
    generic_index = 0
    for cp in obj.cps:
        if cp.id in overrides:
            out[cp.id] = CodeResult(cp.id, overrides[cp.id][:cfg.max_len], "override", base=overrides[cp.id])
            continue
        name = (cp.name or "").strip()
        if name.lower() in cfg.generic_names or not tokens(name):
            generic_index += 1
            base, rule, alts = f"{prefix}{generic_index}"[:cfg.max_len], "generic", []
        else:
            base, rule, alts = compose(name, cfg)
        code = _pick(base, alts, used, cfg)
        used.add(code)
        note = f"was {base}" if code != base else ""
        out[cp.id] = CodeResult(cp.id, code, rule, note, base)
    return out


def generate_codes(ds: Dataset, cfg: CodeConfig, overrides: dict[str, str] | None = None
                   ) -> dict[str, dict[str, CodeResult]]:
    """{objective id: {cp id: CodeResult}} for the whole dataset."""
    return {o.id: generate_objective_codes(o, cfg, overrides) for o in ds.objectives}


AIRFIELD_NOISE = {"AB", "AFB", "AIRBASE", "AIR", "BASE", "AIRPORT", "AIRFIELD", "FIELD", "INTL", "INTERNATIONAL",
                  "INT", "ARPT", "APT", "STRIP", "FARP", "HELIPAD", "MILITARY", "CIVIL"}


def airfield_code(name: str, cfg: CodeConfig) -> str:
    """3-char label for an airfield name: noise words (Airbase, Intl, ...) dropped, then the CP composition rules."""
    toks = [t for t in tokens(name) if t not in AIRFIELD_NOISE] or tokens(name)
    base, _rule, _alts = compose(" ".join(toks), cfg)
    return base or "AFD"


def airfield_excluded(name: str) -> bool:
    """True for airfields that are really helipads/generated strips (config/airfield_filters.json)."""
    pats = _airfield_patterns(str(RES))
    return any(p.search(name) for p in pats)


def _airfield_patterns(root: str):
    from functools import lru_cache

    @lru_cache(maxsize=4)
    def load(r: str):
        f = Path(r) / "config" / "airfield_filters.json"
        raw = json.loads(f.read_text(encoding="utf-8")).get("exclude_name_regex", []) if f.exists() else []
        return tuple(re.compile(x, re.I) for x in raw)
    return load(root)


def load_airfield_overrides(server_id: str) -> dict[str, str]:
    p = data_dir() / "codes" / f"{server_id}.airfields.json"
    return {k: v.upper()[:3] for k, v in json.loads(p.read_text(encoding="utf-8")).items()} if p.exists() else {}


def load_overrides(server_id: str) -> dict[str, str]:
    p = data_dir() / "codes" / f"{server_id}.overrides.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
