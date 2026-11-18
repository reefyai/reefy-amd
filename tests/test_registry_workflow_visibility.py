"""Execute the real push step against a synthetic eventually consistent registry."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PublicationJourneyTests(unittest.TestCase):
    def test_single_push_waits_for_exact_subject_before_sbom_attachment(self):
        source = Path(os.environ.get('REGISTRY_WORKFLOW_SOURCE', ROOT/'.github/workflows/publish.yml'))
        workflow = source.read_text()
        step = workflow.split('      - name: Push OCI artifact\n', 1)[1]
        body = step.split('        run: |\n', 1)[1].split('\n      - name:', 1)[0]
        script = textwrap.dedent(body)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'bin').mkdir(); (root/'inputs').mkdir()
            (root/'inputs/metadata.env').write_text('REEFY_BUILD_ID=synthetic-build\n')
            shutil.copy(ROOT/'versions.json', root/'versions.json')
            if (ROOT/'tools').exists(): shutil.copytree(ROOT/'tools', root/'tools')
            stub = root/'bin/oras'
            stub.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['REGISTRY_CALLS']);rows=json.loads(p.read_text()) if p.exists() else []
rows.append(sys.argv[1:]);p.write_text(json.dumps(rows))
digest='sha256:'+'a'*64
if sys.argv[1]=='push':print('Digest: '+digest)
elif sys.argv[1]=='resolve':
 if sum(c[0]=='resolve' for c in rows)==1:print('subject not found',file=sys.stderr);sys.exit(1)
 print(digest)
elif sys.argv[1]=='attach':
 if sum(c[0]=='resolve' for c in rows)<2:print('subject not found',file=sys.stderr);sys.exit(1)
else:sys.exit(2)
''')
            stub.chmod(0o755)
            env=dict(os.environ, PATH=str(root/'bin')+os.pathsep+os.environ['PATH'],
                     REGISTRY_CALLS=str(root/'calls.json'), GITHUB_OUTPUT=str(root/'outputs'))
            result=subprocess.run(['bash','-e','-o','pipefail','-c',script],cwd=root,
                                  env=env,text=True,capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            calls=json.loads((root/'calls.json').read_text())
            self.assertEqual(sum(c[0]=='push' for c in calls),1)
            self.assertEqual(sum(c[0]=='attach' for c in calls),1)
            self.assertEqual(sum(c[0]=='resolve' for c in calls),2)
            subjects=[c for c in calls if c[0] in ('resolve','attach')]
            self.assertTrue(all(any(x.endswith('@sha256:'+'a'*64) for x in c) for c in subjects))


if __name__ == '__main__': unittest.main()
