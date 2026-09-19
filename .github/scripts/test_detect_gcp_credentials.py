#!/usr/bin/env python3
"""Credential-gate tests for the nightly Parakeet GPU workflow.

The Google Auth step fails closed when secrets.GCP_CREDENTIALS is empty:
google-github-actions/auth requires exactly one of credentials_json or
workload_identity_provider. An unconfigured fork must skip before auth; a
configured repo must still run the GKE suite.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent
MODULE_PATH = SCRIPT_DIR / "detect_gcp_credentials.py"
WORKFLOW_PATH = SCRIPT_DIR.parent / "workflows" / "parakeet_gpu_tests.yml"
SPEC = importlib.util.spec_from_file_location("detect_gcp_credentials", MODULE_PATH)
assert SPEC and SPEC.loader
detect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(detect)

SECRET = '{"type":"service_account","client_email":"probe@example.iam.gserviceaccount.com"}'


class DetectGcpCredentialsTests(unittest.TestCase):
    def test_empty_and_whitespace_are_unavailable(self) -> None:
        self.assertFalse(detect.credentials_available(None))
        self.assertFalse(detect.credentials_available(""))
        self.assertFalse(detect.credentials_available("   \n\t"))

    def test_nonempty_credential_is_available(self) -> None:
        self.assertTrue(detect.credentials_available(SECRET))
        self.assertTrue(detect.credentials_available("{" + "a" * 40 + "}"))

    def test_emit_writes_boolean_without_the_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = str(Path(tmp) / "github_output")
            summary_path = str(Path(tmp) / "summary")
            line = detect.emit_availability(False, output_path=output_path, summary_path=summary_path)
            self.assertEqual(line, "available=false")
            output_text = Path(output_path).read_text(encoding="utf-8")
            summary_text = Path(summary_path).read_text(encoding="utf-8")
            self.assertEqual(output_text, "available=false\n")
            self.assertIn("GCP_CREDENTIALS is unavailable", summary_text)
            self.assertNotIn(SECRET, output_text)
            self.assertNotIn(SECRET, summary_text)

            line = detect.emit_availability(True, output_path=output_path, summary_path=summary_path)
            self.assertEqual(line, "available=true")
            output_text = Path(output_path).read_text(encoding="utf-8")
            self.assertIn("available=true\n", output_text)
            self.assertNotIn(SECRET, output_text)

    def test_main_reads_env_and_does_not_print_the_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = str(Path(tmp) / "github_output")
            summary_path = str(Path(tmp) / "summary")
            env = {
                "GCP_CREDENTIALS": SECRET,
                "GITHUB_OUTPUT": output_path,
                "GITHUB_STEP_SUMMARY": summary_path,
            }
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(detect.main(), 0)
            output_text = Path(output_path).read_text(encoding="utf-8")
            self.assertEqual(output_text, "available=true\n")
            self.assertNotIn(SECRET, output_text)
            self.assertFalse(Path(summary_path).exists())

            env["GCP_CREDENTIALS"] = ""
            Path(output_path).unlink()
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(detect.main(), 0)
            self.assertEqual(Path(output_path).read_text(encoding="utf-8"), "available=false\n")
            self.assertIn("unavailable", Path(summary_path).read_text(encoding="utf-8"))

    def test_main_requires_github_output(self) -> None:
        env = {key: value for key, value in os.environ.items() if key != "GITHUB_OUTPUT"}
        env["GCP_CREDENTIALS"] = SECRET
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(detect.main(), 1)

    def test_gpu_tests_run_only_when_probe_reports_true(self) -> None:
        self.assertTrue(detect.credentials_available(SECRET))
        self.assertFalse(detect.credentials_available(""))
        # The workflow if: compares the nonsecret output exactly.
        self.assertEqual("true" if detect.credentials_available(SECRET) else "false", "true")
        self.assertEqual("true" if detect.credentials_available("") else "false", "false")


class WorkflowGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_probe_job_maps_secret_without_if_on_secrets(self) -> None:
        # omi-test-quality: source-inspection -- GitHub rejects secrets in job if:.
        self.assertIn("  gcp-credentials:\n", self.workflow)
        probe = self.workflow.split("  gcp-credentials:\n", 1)[1].split("  gpu-tests:\n", 1)[0]
        self.assertIn("environment: development", probe)
        self.assertIn("id: credentials", probe)
        self.assertIn("GCP_CREDENTIALS: ${{ secrets.GCP_CREDENTIALS }}", probe)
        self.assertIn("detect_gcp_credentials.py", probe)
        self.assertNotIn("if: ${{ secrets.", probe)
        self.assertNotIn("if: secrets.", probe)

    def test_gpu_tests_are_gated_on_the_nonsecret_probe_output(self) -> None:
        # omi-test-quality: source-inspection -- empty credentials must skip Google Auth.
        gpu = self.workflow.split("  gpu-tests:\n", 1)[1]
        self.assertIn("needs: gcp-credentials", gpu)
        self.assertIn("if: needs.gcp-credentials.outputs.available == 'true'", gpu)
        self.assertIn("google-github-actions/auth@v3", gpu)
        self.assertIn("credentials_json: ${{ secrets.GCP_CREDENTIALS }}", gpu)

    def test_configured_path_still_runs_the_gpu_suite(self) -> None:
        # omi-test-quality: source-inspection -- skip is unconfigured-only, not a deleted gate.
        gpu = self.workflow.split("  gpu-tests:\n", 1)[1]
        self.assertIn("python -m pytest tests/container/test_parakeet_smoke.py", gpu)
        self.assertIn("test_parakeet_der_gate.py", gpu)
        self.assertIn("test_parakeet_der_benchmark.py", gpu)
        self.assertIn("test_parakeet_concurrency.py", gpu)
        self.assertIn("test_parakeet_wer_gate.py", gpu)
        self.assertIn("JOB_NAME: parakeet-gpu-test-${{ github.run_id }}", self.workflow)


if __name__ == "__main__":
    unittest.main()
