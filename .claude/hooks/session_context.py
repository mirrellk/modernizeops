"""SessionStart: print each run's CR key with the last line of its runs/<KEY>/STATUS.log.

Stdout from a SessionStart hook is added to the session context.
"""

from __future__ import annotations

import re

from _common import project_dir


def _sort_key(name: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name))


def main() -> None:
    try:
        logs = sorted((project_dir() / "runs").glob("*/STATUS.log"), key=lambda p: _sort_key(p.parent.name))
        lines = []
        for log in logs:
            entries = [ln.strip() for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()]
            entries = [ln for ln in entries if ln]
            last = entries[-1] if entries else "(empty)"
            parts = [p.strip() for p in last.split("|")]
            if len(parts) >= 3:
                last = f"{parts[1]} -> {' | '.join(parts[2:])} ({parts[0]})"
            lines.append(f"- {log.parent.name}: {last}")
        if lines:
            print("ModernizeOps runs (last STATUS.log entry):")
            print("\n".join(lines))
        else:
            print("ModernizeOps runs: none yet (no runs/*/STATUS.log).")
    except Exception as exc:  # noqa: BLE001 - session start must never fail
        print(f"session_context: could not read run status ({type(exc).__name__}: {exc})")


if __name__ == "__main__":
    main()
