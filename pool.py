"""Candidate gathering for Mixer.build.

Artists are fetched in rank order until enough candidates SURVIVE the
build's filters (owned, heard, already offered, junk, popularity gates). Counting raw search
hits instead stopped after the same first few dozen artists every build; once
their songs were all heard, owned or in the previous mix, the filtered pool
came out empty and maybe_refresh refused to rebuild.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable


def gather_until_usable(
    artists: Iterable[str],
    fetch: Callable[[str], list[Any]],
    keep: Callable[[list[Any]], list[Any]],
    target: int,
) -> list[tuple[str, list[Any]]]:
    """(artist, kept candidates) groups, stopping once `target` are kept.

    `keep(cands)` returns the candidates of one artist that the pool would
    take; an artist with none is dropped.
    """
    groups: list[tuple[str, list[Any]]] = []
    found = 0
    for artist in artists:
        kept = keep(fetch(artist))
        if kept:
            groups.append((artist, kept))
        found += len(kept)
        if found >= target:
            break
    return groups
