"""Cross-process locks on files in state/.

The live watcher and the hourly routine both read, change and write
played.json, and both can roll the playlist. Each such step holds one of
these exclusive flock locks so the slower writer cannot overwrite the other's
change. Locks are not re-entrant: never nest two steps that take the same name.
"""

from __future__ import annotations

import contextlib
import fcntl
import functools
from pathlib import Path
from typing import Any, Callable, Iterator


@contextlib.contextmanager
def state_lock(state: Path, name: str) -> Iterator[None]:
    state.mkdir(parents=True, exist_ok=True)
    with open(state / f"{name}.lock", "w", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def locked(name: str) -> Callable:
    """Decorator for `fn(paths, ...)`: run it holding state_lock(paths.state, name)."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(paths: Any, *args: Any, **kwargs: Any) -> Any:
            with state_lock(paths.state, name):
                return fn(paths, *args, **kwargs)

        return wrapper

    return deco
