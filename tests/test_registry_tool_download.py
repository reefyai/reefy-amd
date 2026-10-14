"""Real curl retries must discard partial bytes and fail closed on exhaustion."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/publish.yml').read_text()


@unittest.skipUnless(shutil.which('curl'), 'curl required')
class RegistryToolDownloadTests(unittest.TestCase):
    def transfer(self, fail_all):
        body = b'synthetic complete tool content'
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(1)
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body[:5] if fail_all or len(requests) == 1 else body)
                self.close_connection = True

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'tool'
                function = re.search(r'          download_tool\(\) \{.*?\n          \}', WORKFLOW, re.S)
                self.assertIsNotNone(function, 'workflow must use the tested retry function')
                script = textwrap.dedent(function.group()) + '\ndownload_tool "$1" "$2"\n'
                result = subprocess.run(
                    ['bash', '-e', '-c', script, 'download-test',
                     f'http://127.0.0.1:{server.server_port}/synthetic-tool', str(output)],
                    capture_output=True, text=True, timeout=20)
                return result, requests, output.read_bytes() if output.exists() else None, body
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_partial_transfer_retries_without_duplicate_bytes(self):
        result, requests, actual, body = self.transfer(False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(requests), 2)
        self.assertEqual(actual, body)

    def test_exhaustion_is_bounded_and_removes_partial_tool(self):
        result, requests, actual, body = self.transfer(True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(requests), 3)
        self.assertIsNone(actual)
