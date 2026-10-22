"""Exercise the real activation script with isolated paths and synthetic tools."""
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

VENDOR = 'amd'
ROOT = Path(__file__).resolve().parents[1]


class ActivationLockTests(unittest.TestCase):
    def exercise(self, fail_module=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host = root/'host'
            common, kernel, tools = (root/name for name in ('common', 'kernel', 'tools'))
            for path in (
                common/'lib/firmware/nvidia', common/'lib/firmware/amdgpu',
                common/'lib/firmware/i915', common/'lib/firmware/xe',
                common/'lib/firmware/intel/vpu', common/'usr/lib',
                common/'usr/share/vulkan/icd.d', common/'usr/share/glvnd/egl_vendor.d',
                common/'usr/share/vulkan/implicit_layer.d', common/'usr/share/egl/egl_external_platform.d',
                common/'usr/share/nvidia', tools/'lib', tools/'share/xpum/resources/config',
                kernel/f'lib/modules/synthetic-release/extra/{VENDOR}',
                host/'proc/driver/nvidia/gpus/synthetic', host/'dev',
                host/'sys/class/drm/card0/device', host/'run/reefy-artifacts/locks',
            ):
                path.mkdir(parents=True, exist_ok=True)
            lock = host/'run/reefy-artifacts/locks/host-module-activation'
            # Use the real flock utility for assertions, with no host module work.
            flock = shutil.which('flock')
            if not flock:
                self.skipTest('Linux util-linux flock is required')
            def executable(path, content):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#!/bin/sh\nset -eu\n'+content)
                path.chmod(0o755)
            bins = root/'bin'
            bins.mkdir()
            executable(bins/'uname', 'echo synthetic-release\n')
            executable(bins/'mountpoint', 'exit 0\n')
            executable(bins/'mount', 'echo unexpected mount >&2; exit 91\n')
            check_held = f'if "{flock}" -n "{lock}" -c true; then echo missing-module-lock >&2; exit 92; fi\n'
            executable(bins/'depmod', check_held+'exit 0\n')
            executable(bins/'modprobe', check_held+('exit 17\n' if fail_module else 'exit 0\n'))
            check_free = f'"{flock}" -n "{lock}" -c true\ntouch "{root}/tail-entered"\n'
            executable(bins/'python3', check_free+'cat >/dev/null\n')
            for name in ('nvidia-smi', 'amd-smi'):
                executable(common/'usr/bin'/name, check_free+'exit 0\n')
                executable(bins/name, check_free+'exit 0\n')
            ctk = check_free+'output=\nprevious=\nfor argument in "$@"; do\n    if [ "$previous" = --output ]; then output=$argument; fi\n    case "$argument" in --output=*) output=${argument#--output=};; esac\n    previous=$argument\ndone\nif [ -n "$output" ]; then printf \'amd.com/gpu\\n\' > "$output"; fi\nexit 0\n'
            for name in ('nvidia-ctk', 'amd-ctk'):
                executable(common/'usr/bin'/name, ctk)
                executable(bins/name, ctk)
            for name in ('xpu-smi', 'xpu-smi.real'):
                executable(tools/'bin'/name, 'exit 0\n')
            (host/'proc/devices').write_text('195 nvidiactl\n511 nvidia-uvm\n')
            for name in ('kfd', 'nvidiactl', 'nvidia-modeset', 'nvidia0', 'nvidia-uvm', 'nvidia-uvm-tools'):
                (host/'dev'/name).touch()
            (host/'sys/class/drm/card0/device/driver').symlink_to(root/'amdgpu')
            (root/'amdgpu').mkdir()
            script = (ROOT/'scripts/activate').read_text()
            # Rewrite every host absolute path, including the embedded Intel
            # discovery program. The staged payload paths are already private.
            for prefix in ('/lib/', '/usr/', '/run/', '/etc/', '/sys/', '/proc/', '/dev/'):
                script = re.sub(r'(?<![A-Za-z0-9_$}])'+re.escape(prefix),
                                lambda match: (prefix if script[:match.start()].endswith('$COMMON\"')
                                               else str(host)+prefix), script)
            hook = root/'activate'
            hook.write_text(script)
            hook.chmod(0o755)
            env = {**os.environ, 'PATH': str(bins)+':'+os.environ['PATH'],
                   'REEFY_ARTIFACT_MOUNTS': ':'.join(map(str, (common, kernel, tools)))}
            result = subprocess.run([str(hook)], env=env, capture_output=True, text=True, timeout=20)
            if fail_module:
                self.assertEqual(result.returncode, 17, result.stderr)
                self.assertFalse((root/'tail-entered').exists())
            else:
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertTrue((root/'tail-entered').exists())
            # Both success and an early set -e failure release the kernel lock.
            self.assertEqual(subprocess.run([flock, '-n', str(lock), '-c', 'true']).returncode, 0)

    def test_module_commands_hold_lock_but_vendor_tail_does_not(self):
        self.exercise()

    def test_module_failure_releases_lock_and_never_publishes_tail(self):
        self.exercise(fail_module=True)
