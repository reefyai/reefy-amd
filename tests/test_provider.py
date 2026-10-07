import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BUILD_PAYLOAD = ROOT / 'scripts/build_payload.py'
PAYLOAD_SPEC = importlib.util.spec_from_file_location(
    'amd_build_payload', BUILD_PAYLOAD)
PAYLOAD = importlib.util.module_from_spec(PAYLOAD_SPEC)
PAYLOAD_SPEC.loader.exec_module(PAYLOAD)

BUILD_MODULES = ROOT / 'scripts/build_modules.py'
MODULE_SPEC = importlib.util.spec_from_file_location(
    'amd_build_modules', BUILD_MODULES)
MODULES = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(MODULES)


class ProviderTests(unittest.TestCase):
    def test_exact_nonconflicting_module_closure(self):
        self.assertEqual(set(MODULES.MODULES), PAYLOAD.EXPECTED_MODULES)
        self.assertIn('amddrm_suballoc_helper', MODULES.MODULES)

    def test_build_preserves_stock_amd_suballocator_configuration(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(
                    MODULES, 'MODULE_ROOT', Path(temporary) / 'modules'), \
                mock.patch.object(MODULES.subprocess, 'run') as run:
            kernel = Path(temporary) / 'kernel'
            kernel.mkdir()
            MODULES.build(
                Path('/source'), kernel, '6.18.40', '/tool/bin/x-')
        command = run.call_args.args[0]
        self.assertFalse(any(
            value.startswith('CONFIG_DRM_SUBALLOC_HELPER=')
            for value in command))
        # AMD's outer make generates compatibility headers serially. Its
        # nested kernel build already uses every CPU itself.
        self.assertFalse(any(value.startswith('-j') for value in command))

    def test_private_helper_is_signed_with_exact_kernel_key(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(MODULES.subprocess, 'run') as run:
            root = Path(temporary)
            source, kernel, output = root / 'source', root / 'kernel', root / 'output'
            for name, relative in MODULES.MODULES.items():
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
            MODULES.stage_and_sign(source, kernel, '6.18.54', output)
            helper = output / 'lib/modules/6.18.54/extra/amd/amddrm_suballoc_helper.ko'
            self.assertEqual(helper.read_bytes(), b'amddrm_suballoc_helper')
            run.assert_any_call([
                str(kernel / 'scripts/sign-file'), 'sha512',
                str(kernel / 'certs/signing_key.pem'),
                str(kernel / 'certs/signing_key.x509'), str(helper),
            ], check=True)
            self.assertEqual(run.call_count, len(MODULES.MODULES))

    def test_kernel_payload_requires_and_preserves_private_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'modules/lib/modules/6.18.54/extra/amd'
            source.mkdir(parents=True)
            for name in PAYLOAD.EXPECTED_MODULES:
                (source / (name + '.ko')).write_bytes(name.encode())
            helper = source / 'amddrm_suballoc_helper.ko'
            helper.unlink()
            with self.assertRaisesRegex(SystemExit, 'module closure'):
                PAYLOAD.stage_kernel(root / 'modules', '6.18.54', root / 'missing')
            helper.write_bytes(b'synthetic signed helper')
            PAYLOAD.stage_kernel(root / 'modules', '6.18.54', root / 'payload')
            staged = root / 'payload/lib/modules/6.18.54/extra/amd'
            self.assertEqual((staged / helper.name).read_bytes(), helper.read_bytes())
            self.assertEqual({p.stem for p in staged.glob('*.ko')},
                             PAYLOAD.EXPECTED_MODULES)

    def test_build_normalizes_temporary_source_paths(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(
                    MODULES, 'MODULE_ROOT', Path(temporary) / 'modules'), \
                mock.patch.dict(MODULES.os.environ, {'KCFLAGS': '-Werror'}), \
                mock.patch.object(MODULES.subprocess, 'run') as run:
            kernel = Path(temporary) / 'kernel'
            kernel.mkdir()
            source = Path(temporary) / 'random-dkms-tree'
            MODULES.build(source, kernel, '6.18.40', '/tool/bin/x-')
            flags = run.call_args.kwargs['env']['KCFLAGS']
            self.assertIn('-Werror', flags)
            for option in ('-fdebug-prefix-map', '-ffile-prefix-map'):
                self.assertIn(
                    f'{option}={source.resolve()}=/usr/src/reefy-amd', flags)

    def test_dkms_kernel_link_is_exact_and_temporary(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(
                    MODULES, 'MODULE_ROOT', Path(temporary) / 'modules'):
            root = Path(temporary)
            kernel = root / 'kernel'
            kernel.mkdir()
            link = MODULES.MODULE_ROOT / '6.18.40/build'
            with MODULES.dkms_kernel_link(kernel, '6.18.40'):
                self.assertEqual(link.resolve(), kernel.resolve())
            self.assertFalse(link.exists())

    def test_squashfs_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(PAYLOAD.subprocess, 'run') as run:
            root = Path(temporary)
            PAYLOAD.squash(root / 'source', root / 'payload.squashfs')
        command = run.call_args.args[0]
        self.assertIn('-mkfs-time', command)
        self.assertIn('-all-time', command)
        self.assertIn('-all-root', command)

    def test_activation_is_provider_owned_and_atomic(self):
        script = (ROOT / 'scripts/activate').read_text()
        self.assertNotIn('/sys/bus/pci', script)
        self.assertIn('modprobe amdgpu', script)
        self.assertIn('/sys/class/drm/card[0-9]*/device/driver', script)
        self.assertIn('amd-ctk cdi validate --path "$temporary"', script)
        self.assertIn('mv -f "$temporary" /run/cdi/amd.json', script)
        self.assertIn('AMD driver found no usable GPUs', script)

    def test_only_amd_smi_is_exposed_as_host_monitor(self):
        wrapper = (ROOT / 'scripts/amd-smi').read_text()
        self.assertIn('amdsmi_cli.py', wrapper)
        self.assertNotIn('LD_LIBRARY_PATH', wrapper)
        self.assertFalse((ROOT / 'scripts/rocm-smi').exists())

    def test_libdrm_is_owned_by_reefy_os(self):
        versions = (ROOT / 'versions.json').read_text()
        workflow = (ROOT / '.github/workflows/publish.yml').read_text()
        activation = (ROOT / 'scripts/activate').read_text()
        self.assertNotIn('"libdrm"', versions)
        self.assertNotIn('libdrm', workflow)
        self.assertNotIn('amdgpu.ids', activation)

    def test_reusable_workflow_checks_out_its_exact_source(self):
        workflow = (ROOT / '.github/workflows/publish.yml').read_text()
        self.assertIn(
            'repository: ${{ job.workflow_repository }}', workflow)
        self.assertIn('ref: ${{ job.workflow_sha }}', workflow)


if __name__ == '__main__':
    unittest.main()
