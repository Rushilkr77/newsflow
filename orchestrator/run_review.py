"""
Run /newsflow-review headlessly via `claude -p` after each pipeline run.
Writes the markdown report to workspace/{date}/review_report.md.
"""
import shutil
import subprocess
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_REPO_ROOT = Path(__file__).parent.parent


def generate(date_str: str) -> Path | None:
    """Run /newsflow-review for the given date. Returns report path or None on failure."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        log.warning("run_review_skipped", reason="claude binary not found in PATH")
        return None

    workspace = _REPO_ROOT / "workspace" / date_str
    report_path = workspace / "review_report.md"

    log.info("run_review_start", date=date_str)
    try:
        result = subprocess.run(
            [claude_bin, "-p", "/newsflow-review", "--output-format", "text"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        log.warning("run_review_timeout", date=date_str)
        return None
    except Exception as exc:
        log.warning("run_review_error", error=str(exc))
        return None

    if result.returncode != 0:
        log.warning("run_review_failed", returncode=result.returncode, stderr=result.stderr[:500])
        return None

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(result.stdout, encoding="utf-8")
    log.info("run_review_complete", path=str(report_path), chars=len(result.stdout))
    return report_path


if __name__ == "__main__":
    import sys
    from datetime import date

    date_arg = sys.argv[1] if len(sys.argv) > 1 else str(date.today())
    path = generate(date_arg)
    print(f"Review report: {path}" if path else "Review failed — check logs")
