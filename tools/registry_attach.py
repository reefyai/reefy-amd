"""Attach an SBOM to an immutable subject after bounded registry visibility."""
import re
import subprocess
import sys
import time


def attach(reference, sbom, *, now=time.monotonic, sleep=time.sleep,
           run=subprocess.run):
    if not re.fullmatch(r'ghcr\.io/reefyai/[a-z0-9-]+@sha256:[0-9a-f]{64}', reference):
        raise ValueError('An immutable provider subject is required')
    expected = reference.rsplit('@', 1)[1]
    deadline = now() + 60
    while now() < deadline:
        # Read and attach only the original push digest. Never repush, resolve
        # a moving tag, or accept another subject while waiting for GHCR.
        commands = [
            ['oras', 'resolve', reference],
            ['oras', 'attach', '--artifact-type', 'application/spdx+json',
             reference, sbom + ':application/spdx+json']]
        for index, command in enumerate(commands):
            remaining = deadline - now()
            if remaining <= 0:
                raise RuntimeError('Registry subject visibility deadline exceeded')
            try:
                result = run(command, capture_output=True, text=True,
                             timeout=min(10, remaining))
            except subprocess.TimeoutExpired as error:
                # An attach may have happened. Do not replay ambiguous writes.
                raise RuntimeError('Registry command timed out') from error
            if result.returncode != 0:
                error = result.stderr.lower()
                if ('not found' not in error or any(word in error for word in
                        ('unauthorized', 'denied', 'forbidden', 'authentication'))):
                    raise RuntimeError('Registry command failed without a visibility retry')
                break
            if index == 0 and result.stdout.strip() != expected:
                raise RuntimeError('Registry returned a different subject digest')
        else:
            print('SBOM attached to the exact published subject', flush=True)
            return
        sleep(min(2, max(0, deadline - now())))
    raise RuntimeError('Registry subject visibility deadline exceeded')


if __name__ == '__main__':
    attach(*sys.argv[1:])
