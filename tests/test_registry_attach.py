"""Registry propagation must not repush or change immutable subjects."""
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location(
    'registry_attach', Path(__file__).resolve().parents[1] / 'tools/registry_attach.py')
module = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(module)
REFERENCE = 'ghcr.io/reefyai/synthetic-provider@sha256:' + 'a' * 64
DIGEST = 'sha256:' + 'a' * 64


class RegistryVisibilityTests(unittest.TestCase):
    def exercise(self, outcomes):
        clock = [0.0]; commands = []
        def run(command, **kwargs):
            commands.append(command)
            self.assertLessEqual(kwargs['timeout'], 10)
            result = outcomes[min(len(commands)-1, len(outcomes)-1)]
            if isinstance(result, Exception): raise result
            return SimpleNamespace(returncode=result[0], stdout=result[1], stderr=result[2])
        def sleep(duration): clock[0] += duration
        error = None
        try:
            module.attach(REFERENCE, 'output/sbom.spdx.json',
                          now=lambda: clock[0], sleep=sleep, run=run)
        except RuntimeError as caught: error = caught
        self.assertTrue(all(REFERENCE in cmd for cmd in commands))
        self.assertFalse(any('push' in cmd for cmd in commands))
        return commands, clock[0], error

    def test_read_404_then_exact_digest_then_attach(self):
        commands, elapsed, error = self.exercise([
            (1, '', 'failed to resolve: not found'),
            (0, DIGEST, ''), (0, '', '')])
        self.assertIsNone(error); self.assertEqual(elapsed, 2)
        self.assertEqual([c[1] for c in commands], ['resolve', 'resolve', 'attach'])

    def test_attachment_subject_404_is_retried_without_repush(self):
        commands, _, error = self.exercise([
            (0, DIGEST, ''), (1, '', 'subject not found'),
            (0, DIGEST, ''), (0, '', '')])
        self.assertIsNone(error)
        self.assertEqual([c[1] for c in commands], ['resolve', 'attach', 'resolve', 'attach'])

    def test_permanent_absence_is_bounded_at_sixty_seconds(self):
        commands, elapsed, error = self.exercise([(1, '', 'not found')])
        self.assertEqual(elapsed, 60); self.assertEqual(len(commands), 30)
        self.assertIn('deadline', str(error))

    def test_authentication_and_non_visibility_errors_fail_immediately(self):
        for stderr in ('unauthorized: not found', 'denied', 'invalid manifest', 'forbidden'):
            with self.subTest(stderr=stderr):
                commands, elapsed, error = self.exercise([(1, '', stderr)])
                self.assertEqual(len(commands), 1); self.assertEqual(elapsed, 0)
                self.assertIsNotNone(error)

    def test_wrong_digest_never_reaches_attach(self):
        commands, _, error = self.exercise([(0, 'sha256:'+'b'*64, '')])
        self.assertEqual(len(commands), 1); self.assertIn('different subject', str(error))

    def test_ambiguous_attach_timeout_is_never_replayed(self):
        commands, _, error = self.exercise([
            (0, DIGEST, ''), subprocess.TimeoutExpired(['oras', 'attach'], 10)])
        self.assertEqual(len(commands), 2); self.assertIn('timed out', str(error))

    def test_tag_or_malformed_digest_rejected_before_registry_access(self):
        for reference in ('ghcr.io/reefyai/synthetic-provider:latest', REFERENCE+';echo'):
            with self.assertRaises(ValueError): module.attach(reference, 'sbom')


if __name__ == '__main__': unittest.main()
