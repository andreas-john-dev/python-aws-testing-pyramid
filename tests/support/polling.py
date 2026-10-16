import time
from collections.abc import Callable


def eventually[T](
    probe: Callable[[], T],
    until: Callable[[T], bool],
    timeout: float = 10.0,
    interval: float = 0.25,
) -> T:
    """Polls `probe` until `until(result)` holds. For reads from an eventually consistent GSI.

    Returns on the first try against moto or the fake, so the same test works for all backends.
    """
    deadline = time.monotonic() + timeout
    while True:
        result = probe()
        if until(result) or time.monotonic() >= deadline:
            return result
        time.sleep(interval)
