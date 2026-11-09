"""Exercise partial HTTP transfers, bounded retries and verified replacement."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('registry_download', ROOT/'scripts/download_registry_tools.py')
download = importlib.util.module_from_spec(spec)
spec.loader.exec_module(download)


class RegistryToolDownloadTests(unittest.TestCase):
    def transfer(self, mode, previous=None):
        body = b'synthetic complete tool content'
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(1)
                response = b'synthetic corrupt tool content' if mode == 'digest' else body
                self.send_response(200)
                self.send_header('Content-Length', str(len(response)))
                self.end_headers()
                partial = mode == 'exhaust' or (mode == 'partial' and len(requests) == 1)
                self.wfile.write(response[:5] if partial else response)
                self.close_connection = True

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root/'output/tool'
                output.parent.mkdir()
                if previous is not None:
                    output.write_bytes(previous)
                # Model gh's partial-file/nonzero-exit contract with real HTTP
                # truncation. Production and test use the same retry helper.
                gh = root/'gh'
                gh.write_text('#!'+sys.executable+'\n'+'''import http.client,os,sys,urllib.request
from pathlib import Path
args=sys.argv
target=Path(args[args.index('--dir')+1])/args[args.index('--pattern')+1]
with urllib.request.urlopen(os.environ['DOWNLOAD_TEST_URL']) as response:
 try: data=response.read()
 except http.client.IncompleteRead as error:
  target.write_bytes(error.partial)
  sys.exit(1)
 target.write_bytes(data)
''')
                gh.chmod(0o755)
                error = None
                with patch.dict(os.environ, PATH=str(root)+os.pathsep+os.environ['PATH'],
                                DOWNLOAD_TEST_URL=f'http://127.0.0.1:{server.server_port}/synthetic-tool'):
                    try:
                        download.download_tool('synthetic/registry', 'v1', 'tool',
                            hashlib.sha256(body).hexdigest(), output, retry_delay=0)
                    except RuntimeError as failure:
                        error = failure
                leftovers = [p.name for p in output.parent.iterdir() if p != output]
                return error, requests, output.read_bytes() if output.exists() else None, body, leftovers
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_partial_transfer_retries_without_duplicate_bytes(self):
        error, requests, actual, body, leftovers = self.transfer('partial')
        self.assertIsNone(error)
        self.assertEqual(len(requests), 2)
        self.assertEqual(actual, body)
        self.assertEqual(leftovers, [])

    def test_exhaustion_is_bounded_and_removes_partial_tool(self):
        error, requests, actual, _, leftovers = self.transfer('exhaust')
        self.assertIsNotNone(error)
        self.assertEqual(len(requests), 3)
        self.assertIsNone(actual)
        self.assertEqual(leftovers, [])

    def test_bad_digest_preserves_previously_verified_tool(self):
        previous = b'synthetic previously verified tool'
        error, requests, actual, _, leftovers = self.transfer('digest', previous)
        self.assertIsNotNone(error)
        self.assertEqual(len(requests), 3)
        self.assertEqual(actual, previous)
        self.assertEqual(leftovers, [])
