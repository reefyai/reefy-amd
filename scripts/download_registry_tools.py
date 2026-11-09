#!/usr/bin/env python3
"""Fetch pinned registry tools through GitHub's API, verifying before replacement."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import time

TOOLS = (
    ('oras-project/oras', 'v1.3.0', 'oras_1.3.0_linux_amd64.tar.gz',
     '6cdc692f929100feb08aa8de584d02f7bcc30ec7d88bc2adc2054d782db57c64'),
    ('sigstore/cosign', 'v2.5.3', 'cosign-linux-amd64',
     '783b5d6c74105401c63946c68d9b2a4e1aab3c8abce043e06b8510b02b623ec9'),
)


def download_tool(repository, version, asset, expected, destination, *, retry_delay=1):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    reason = 'download did not run'
    for attempt in range(3):
        # A new directory prevents CLI retries from reusing partial bytes and
        # keeps a previously verified destination intact until replacement.
        with tempfile.TemporaryDirectory(prefix='.registry-download-', dir=destination.parent) as tmp:
            try:
                result = subprocess.run(
                    ['gh', 'release', 'download', version, '--repo', repository,
                     '--pattern', asset, '--dir', tmp], capture_output=True, timeout=120)
                if result.returncode:
                    reason = f'CLI exit {result.returncode}'
                else:
                    path = Path(tmp)/asset
                    with path.open('rb') as stream:
                        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
                    if actual == expected:
                        os.replace(path, destination)
                        return destination
                    reason = 'SHA-256 mismatch'
            except (OSError, subprocess.TimeoutExpired) as error:
                reason = type(error).__name__
        if attempt < 2:
            time.sleep(retry_delay*(attempt+1))
    raise RuntimeError(f'{repository} {version} {asset}: {reason} after 3 attempts')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    for repository, version, asset, expected in TOOLS:
        download_tool(repository, version, asset, expected, args.directory/asset)


if __name__ == '__main__':
    main()
