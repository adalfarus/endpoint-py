from collections import defaultdict
from dataclasses import dataclass
import re

# Standard typing imports for aps
import typing_extensions as _te
import collections.abc as _a
import typing as _ty

if _ty.TYPE_CHECKING:
    import _typeshed as _tsh
import types as _ts

__all__ = ["guess_prefix_shortforms", "guess_letters", "guess_shortforms"]


def guess_prefix_shortforms(arguments: list[str], min_len: int = 2) -> dict[str, str]:
    shortforms: dict[str, str] = dict()
    for argument in arguments:
        argu_i: int = 0
        while argument[:argu_i] in shortforms.values() or argu_i < min_len:
            if argu_i == len(argument):  # Shortform not possible
                argu_i = 0
                break
            argu_i += 1
        shortforms[argument] = argument[:argu_i]
    return shortforms


def guess_letters(arguments: list[str]) -> dict[str, str]:
    letters: dict[str, str] = dict()
    for argument in arguments:
        argu_i: int = 0
        while True:
            if argument[argu_i] not in letters.values():
                letters[argument] = argument[argu_i]
                break
            elif argu_i == len(argument):  # Shortform not possible
                letters[argument] = ""
                break
            argu_i += 1
    return letters


# Soft Min Max guess
_SPLIT = re.compile(r"[^A-Za-z0-9]+")

@dataclass
class _State:
    original: str
    tokens: list[str]   # e.g. ["output", "file"]
    idx: list[int]      # chars taken from each token

def _abbr(st: _State) -> str:
    return "".join(t[:n] for t, n in zip(st.tokens, st.idx) if n > 0)

def _init_state(name: str, *, soft_min: int) -> _State:
    s = name.lstrip("-")
    tokens = [t for t in _SPLIT.split(s) if t] or [s]

    # Start token-aware:
    # - take a small chunk from token1
    # - take 1 from each later token (so multiword args get "outf" style immediately)
    if len(tokens) == 1:
        first = tokens[0]
        take1 = min(max(2, min(soft_min, 3)), len(first))  # typically 2–3
        idx = [take1]
    else:
        t1 = tokens[0]
        take1 = min(max(2, min(soft_min, 3)), len(t1))     # typically 2–3
        idx = [take1] + [min(1, len(t)) for t in tokens[1:]]

    st = _State(original=name, tokens=tokens, idx=idx)

    # Ensure at least soft_min chars total (grow token1 first for readability)
    while len(_abbr(st)) < soft_min and st.idx[0] < len(st.tokens[0]):
        st.idx[0] += 1

    return st

def _can_grow(st: _State, pos: int) -> bool:
    return pos < len(st.tokens) and st.idx[pos] < len(st.tokens[pos])

def guess_shortforms(arguments: list[str], *, soft_min: int = 3, soft_max: int = 4) -> dict[str, str]:
    """
    Find sensible unique shortforms for a set of argument names

    - soft_min / soft_max are preferences not hard limits
    - Shortforms will grow beyond soft_max when needed for uniqueness
    - Only colliding items are lengthened, and we lengthen later tokens (split at e.g. '-') first
    """
    states = [_init_state(a, soft_min=soft_min) for a in arguments]

    while True:
        groups: dict[str, list[_State]] = defaultdict(list)
        for st in states:
            groups[_abbr(st)].append(st)

        collisions = [g for g in groups.values() if len(g) > 1]
        if not collisions:
            break

        progressed_any = False

        for grp in collisions:
            # Strategy:
            # 1) If they're still within preferred length, try to disambiguate by adding info:
            #    grow later tokens first (file vs format => fi vs fo)
            # 2) If later tokens can’t grow, grow the first token.
            # 3) If still stuck (true duplicates), fall back to full name.

            # If any in this collision group are <= soft_max, we try to keep them near that
            # by extending informative parts first.
            for pos in range(1, max(len(s.tokens) for s in grp)):  # token2..tokenN
                did = False
                for st in grp:
                    if len(_abbr(st)) <= soft_max and _can_grow(st, pos):
                        st.idx[pos] += 1
                        did = True
                        progressed_any = True
                if did:
                    break  # regroup after one dimension of growth

            if progressed_any:
                continue

            # Otherwise, extend token1 (or beyond soft_max if needed)
            did = False
            for st in grp:
                if _can_grow(st, 0):
                    st.idx[0] += 1
                    did = True
                    progressed_any = True
            if did:
                continue

            # Last resort: can't disambiguate => use full normalized tokens
            for st in grp:
                st.idx = [len(t) for t in st.tokens]
                progressed_any = True

        if not progressed_any:
            break

    return {st.original: _abbr(st) for st in states}
