#!/usr/bin/env python3
"""Use HTTPS for official Ubuntu repositories in the ephemeral CI runner."""
from pathlib import Path


def configure(root=Path('/etc/apt')):
    paths = [root / 'sources.list', *sorted((root / 'sources.list.d').glob('*.list')),
             *sorted((root / 'sources.list.d').glob('*.sources'))]
    for path in paths:
        if not path.is_file():
            continue
        original = path.read_text()
        updated = original
        for host in ('archive.ubuntu.com', 'security.ubuntu.com'):
            updated = updated.replace('http://' + host + '/ubuntu',
                                      'https://' + host + '/ubuntu')
        if updated != original:
            path.write_text(updated)
            print('Enabled Ubuntu HTTPS in ' + path.name, flush=True)


if __name__ == '__main__':
    configure()
