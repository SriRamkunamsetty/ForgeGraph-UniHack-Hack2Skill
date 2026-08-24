from __future__ import annotations

from collections import Counter
from threading import Lock


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: Counter[str] = Counter()

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def render(self) -> str:
        with self._lock:
            lines = [
                "# HELP forgegraph_events_total Number of ForgeGraph application events.",
                "# TYPE forgegraph_events_total counter",
            ]
            for name, value in sorted(self._counters.items()):
                safe_name = name.replace("-", "_")
                lines.append(f'forgegraph_events_total{{event="{safe_name}"}} {value}')
            return "\n".join(lines) + "\n"


metrics = Metrics()
