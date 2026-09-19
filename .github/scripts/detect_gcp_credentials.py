#!/usr/bin/env python3
"""Report whether GCP_CREDENTIALS is present without printing the value.

The nightly Parakeet GPU workflow must skip before google-github-actions/auth
when this fork has no development-environment credential. A configured repo
still fails closed through the existing GKE job. This script is the probe's
production seam: it writes only `available=true|false` to GITHUB_OUTPUT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

UNCONFIGURED_SUMMARY = "Parakeet GPU tests skipped because GCP_CREDENTIALS is unavailable.\n"


def credentials_available(value: str | None) -> bool:
    """True only when a nonempty credential is actually present."""
    return bool((value or "").strip())


def emit_availability(
    available: bool,
    *,
    output_path: str | None,
    summary_path: str | None,
) -> str:
    line = f"available={'true' if available else 'false'}"
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    if not available and summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(UNCONFIGURED_SUMMARY)
    return line


def main() -> int:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print("GITHUB_OUTPUT is required so the GPU job can read a nonsecret availability flag.", file=sys.stderr)
        return 1
    available = credentials_available(os.environ.get("GCP_CREDENTIALS"))
    emit_availability(
        available,
        output_path=output_path,
        summary_path=os.environ.get("GITHUB_STEP_SUMMARY"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
