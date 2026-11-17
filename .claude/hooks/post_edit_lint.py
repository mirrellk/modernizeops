"""PostToolUse (Edit|Write): run `ruff check --fix` on an edited .py file.

Remaining errors are returned to Claude (exit 2, stderr) so it fixes them in the next step.
Never blocks on its own failure: if ruff cannot run, it says so and exits 0.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys

from _common import base_dir, project_dir, read_input, resolve, tool_input


def ruff_command() -> list[str] | None:
    if importlib.util.find_spec("ruff") is not None:
        return [sys.executable, "-m", "ruff"]
    exe = shutil.which("ruff")
    return [exe] if exe else None


def main() -> None:
    try:
        data = read_input()
    except Exception:  # noqa: BLE001 - a lint hook never blocks on bad input
        return
    file_path = tool_input(data).get("file_path")
    if not isinstance(file_path, str) or not file_path.lower().endswith(".py"):
        return
    path = resolve(file_path, base_dir(data))
    if not path.is_file():
        return
    ruff = ruff_command()
    if ruff is None:
        print("post_edit_lint: ruff not found; skipped.", file=sys.stderr)
        return
    try:
        result = subprocess.run(
            [*ruff, "check", "--fix", "--quiet", "--output-format", "concise", str(path)],
            check=False,
            cwd=project_dir(),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"post_edit_lint: ruff did not run ({exc}); skipped.", file=sys.stderr)
        return
    if result.returncode == 0:
        return
    output = (result.stdout + result.stderr).strip()
    print(f"ruff check --fix left errors in {file_path}:\n{output}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
