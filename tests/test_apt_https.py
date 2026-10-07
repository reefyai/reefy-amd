import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('apt_https', Path(__file__).resolve().parents[1] / 'scripts/configure_apt_https.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AptHttpsTests(unittest.TestCase):
    def test_deb822_and_legacy_keep_keys_suites_and_other_repositories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sources.list.d').mkdir()
            source = root / 'sources.list.d/ubuntu.sources'
            original = 'Types: deb\nURIs: http://archive.ubuntu.com/ubuntu\nSuites: noble noble-updates\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n'
            source.write_text(original)
            legacy = root / 'sources.list'
            legacy.write_text('deb http://security.ubuntu.com/ubuntu noble-security main\ndeb https://example.invalid/packages stable main\n')
            module.configure(root)
            self.assertEqual(source.read_text(), original.replace('http://archive.', 'https://archive.'))
            self.assertEqual(legacy.read_text(), 'deb https://security.ubuntu.com/ubuntu noble-security main\ndeb https://example.invalid/packages stable main\n')
            first = source.read_text()
            module.configure(root)
            self.assertEqual(source.read_text(), first)

    def test_absent_sources_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            module.configure(Path(tmp))
