#!/usr/bin/env python3
"""Unit tests for guardrail baseline health pulse (#9454)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import guardrail_pulse


class ScriptedGh:
    def __init__(self, responses: list[tuple[str, ...]]) -> None:
        self.calls: list[list[str]] = []
        self._responses = list(responses)

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if not self._responses:
            raise AssertionError(f"unexpected gh call: {args}")
        kind, *rest = self._responses.pop(0)
        if kind == "ok":
            return rest[0] if rest else ""
        raise guardrail_pulse.GhError(int(rest[0]), rest[1] if len(rest) > 1 else "", rest[2] if len(rest) > 2 else "")


class GuardrailPulseTests(unittest.TestCase):
    def test_format_text_parses_counts(self) -> None:
        text = guardrail_pulse.format_text(
            [
                guardrail_pulse.Metric("union_return_isinstance", 0, 0),
                guardrail_pulse.Metric("lifecycle_unlabeled_scripts", 14, 19),
            ]
        )
        self.assertIn("union_return_isinstance", text)
        self.assertIn("0", text)
        self.assertIn("(baseline 0)", text)
        self.assertIn("lifecycle_unlabeled_scripts", text)
        self.assertIn("(baseline 19)", text)

    def test_staleness_triggers_on_31_day_unchanged_nonzero(self) -> None:
        as_of = date(2026, 7, 23)
        old = (as_of - timedelta(days=31)).isoformat()
        mid = (as_of - timedelta(days=15)).isoformat()
        history = [
            {
                "date": old,
                "metrics": {"lifecycle_unlabeled_scripts": {"count": 14, "baseline": 19}},
            },
            {
                "date": mid,
                "metrics": {"lifecycle_unlabeled_scripts": {"count": 14, "baseline": 19}},
            },
            {
                "date": as_of.isoformat(),
                "metrics": {"lifecycle_unlabeled_scripts": {"count": 14, "baseline": 19}},
            },
        ]
        self.assertEqual(
            guardrail_pulse.find_stale_metrics(history, as_of=as_of, window_days=30),
            ["lifecycle_unlabeled_scripts"],
        )

    def test_staleness_skips_decreasing_metric(self) -> None:
        as_of = date(2026, 7, 23)
        old = (as_of - timedelta(days=31)).isoformat()
        recent = (as_of - timedelta(days=7)).isoformat()
        history = [
            {
                "date": old,
                "metrics": {"mapless_packages": {"count": 7, "baseline": 7}},
            },
            {
                "date": recent,
                "metrics": {"mapless_packages": {"count": 6, "baseline": 7}},
            },
            {
                "date": as_of.isoformat(),
                "metrics": {"mapless_packages": {"count": 6, "baseline": 7}},
            },
        ]
        self.assertEqual(guardrail_pulse.find_stale_metrics(history, as_of=as_of, window_days=30), [])

    def test_staleness_skips_zero_counts(self) -> None:
        as_of = date(2026, 7, 23)
        old = (as_of - timedelta(days=40)).isoformat()
        history = [
            {"date": old, "metrics": {"union_return_isinstance": {"count": 0, "baseline": 0}}},
            {
                "date": as_of.isoformat(),
                "metrics": {"union_return_isinstance": {"count": 0, "baseline": 0}},
            },
        ]
        self.assertEqual(guardrail_pulse.find_stale_metrics(history, as_of=as_of), [])

    def test_record_appends_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.jsonl"
            payload = guardrail_pulse.metrics_payload(
                [guardrail_pulse.Metric("union_return_isinstance", 0, 0)],
                recorded_at="2026-07-23",
            )
            guardrail_pulse.append_history(history, payload)
            guardrail_pulse.append_history(history, payload)
            rows = guardrail_pulse.load_history(history)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["date"], "2026-07-23")
            self.assertEqual(rows[0]["metrics"]["union_return_isinstance"]["count"], 0)

    def test_json_round_trip_shape(self) -> None:
        payload = guardrail_pulse.metrics_payload(
            [guardrail_pulse.Metric("brand_ui_purple", 3, 3)],
            recorded_at="2026-01-01",
        )
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["metrics"]["brand_ui_purple"]["baseline"], 3)


class GuardrailPulseTrackerTests(unittest.TestCase):
    def test_issues_disabled_matches_exact_omi_log_line(self) -> None:
        error = guardrail_pulse.GhError(
            1,
            "",
            "the 'woahwhattheheck/omi' repository has disabled issues",
        )
        self.assertTrue(error.issues_disabled())
        other = guardrail_pulse.GhError(1, "", "HTTP 401: Bad credentials")
        self.assertFalse(other.issues_disabled())

    def test_issues_disabled_writes_in_repo_tracker_and_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = Path(tmp) / "guardrail-staleness.md"
            runner = ScriptedGh(
                [
                    (
                        "err",
                        "1",
                        "",
                        "the 'woahwhattheheck/omi' repository has disabled issues",
                    )
                ]
            )
            body = guardrail_pulse.build_tracker_body(
                pulse_text="version_prefixed_files  38    (baseline 38)",
                staleness_text="STALE: version_prefixed_files",
                run_url="https://github.com/woahwhattheheck/omi/actions/runs/35647729331",
            )
            result = guardrail_pulse.persist_staleness_tracker(
                repo="woahwhattheheck/omi",
                title=guardrail_pulse.DEFAULT_TRACKER_TITLE,
                body=body,
                comment="refresh",
                tracker_path=tracker,
                runner=runner,
            )
            self.assertEqual(result["channel"], "file")
            self.assertTrue(tracker.is_file())
            text = tracker.read_text(encoding="utf-8")
            self.assertIn(guardrail_pulse.ISSUES_DISABLED_TRACKER_NOTE, text)
            self.assertIn("version_prefixed_files", text)
            self.assertIn("35647729331", text)
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(runner.calls[0][0], "issue")

    def test_other_gh_errors_still_fail_closed_without_writing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = Path(tmp) / "guardrail-staleness.md"
            runner = ScriptedGh([("err", "1", "", "HTTP 403: Resource not accessible by integration")])
            with self.assertRaises(guardrail_pulse.GhError) as caught:
                guardrail_pulse.persist_staleness_tracker(
                    repo="woahwhattheheck/omi",
                    title=guardrail_pulse.DEFAULT_TRACKER_TITLE,
                    body="body",
                    comment="refresh",
                    tracker_path=tracker,
                    runner=runner,
                )
            self.assertFalse(caught.exception.issues_disabled())
            self.assertFalse(tracker.exists())

    def test_creates_issue_when_none_exists(self) -> None:
        runner = ScriptedGh([("ok", ""), ("ok", "https://github.com/woahwhattheheck/omi/issues/12\n")])
        with tempfile.TemporaryDirectory() as tmp:
            tracker = Path(tmp) / "guardrail-staleness.md"
            result = guardrail_pulse.persist_staleness_tracker(
                repo="woahwhattheheck/omi",
                title=guardrail_pulse.DEFAULT_TRACKER_TITLE,
                body="body",
                comment="refresh",
                tracker_path=tracker,
                runner=runner,
            )
        self.assertEqual(result["channel"], "issue")
        self.assertIn("issues/12", result["url"])
        self.assertFalse(tracker.exists())
        self.assertEqual(runner.calls[1][0:2], ["issue", "create"])

    def test_updates_existing_issue_in_place(self) -> None:
        runner = ScriptedGh([("ok", "7\n"), ("ok", ""), ("ok", "")])
        with tempfile.TemporaryDirectory() as tmp:
            tracker = Path(tmp) / "guardrail-staleness.md"
            result = guardrail_pulse.persist_staleness_tracker(
                repo="woahwhattheheck/omi",
                title=guardrail_pulse.DEFAULT_TRACKER_TITLE,
                body="body",
                comment="Weekly pulse refreshed this tracker.",
                tracker_path=tracker,
                runner=runner,
            )
        self.assertEqual(result, {"channel": "issue", "number": "7"})
        self.assertEqual(runner.calls[1][0:3], ["issue", "edit", "7"])
        self.assertEqual(runner.calls[2][0:3], ["issue", "comment", "7"])
        self.assertFalse(tracker.exists())

    def test_workflow_routes_tracker_through_python_helper(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1] / "workflows" / "guardrail-baseline-pulse.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("--upsert-tracker", workflow)
        self.assertIn("guardrail-staleness.md", workflow)
        self.assertNotIn("gh issue create", workflow)
        self.assertNotIn("gh issue list", workflow)


if __name__ == "__main__":
    unittest.main()
