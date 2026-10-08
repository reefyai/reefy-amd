#!/usr/bin/env python3
"""Build Reefy's AMD common and exact-kernel SquashFS payload layers."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VERSIONS = json.loads((ROOT / 'versions.json').read_text())
DRIVER = VERSIONS['amd_gpu_driver']
AMD_SMI = VERSIONS['amd_smi']
EXPECTED_MODULES = {
    'amdgpu', 'amdkcl', 'amdxcp', 'amdttm', 'amd-sched',
    'amddrm_ttm_helper', 'amddrm_buddy', 'amddrm_exec',
    'amddrm_suballoc_helper',
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path, size, digest, label):
    if path.stat().st_size != size:
        raise SystemExit(f'{label} size mismatch')
    if sha256(path) != digest:
        raise SystemExit(f'{label} SHA-256 mismatch')


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source, destination):
    if not source.is_dir():
        raise SystemExit(f'missing payload directory: {source}')
    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)


def extract(package, destination):
    subprocess.run([
        'dpkg-deb', '--extract', str(package), str(destination),
    ], check=True)


def stage_common(firmware_package, amd_smi_package, amd_ctk, common,
                 temporary):
    verify(
        firmware_package, DRIVER['firmware_bytes'],
        DRIVER['firmware_sha256'], 'AMD firmware package')
    verify(
        amd_smi_package, AMD_SMI['package_bytes'],
        AMD_SMI['package_sha256'], 'AMD SMI package')
    firmware = temporary / 'firmware'
    smi = temporary / 'amd-smi'
    extract(firmware_package, firmware)
    extract(amd_smi_package, smi)
    copy_tree(
        firmware / 'lib/firmware/updates/amdgpu',
        common / 'lib/firmware/amdgpu')

    rocm = smi / f'opt/rocm-{AMD_SMI["rocm_version"]}'
    copy_tree(
        rocm / 'share/amd_smi/amdsmi',
        common / 'usr/lib/reefy/amd-smi/python/amdsmi')
    copy_tree(
        rocm / 'libexec/amdsmi_cli',
        common / 'usr/lib/reefy/amd-smi/cli')
    copy(
        rocm / 'share/doc/amd-smi-lib/LICENSE.txt',
        common / 'usr/share/licenses/amd-smi/LICENSE.txt')
    copy(
        firmware / 'usr/share/doc/amdgpu-dkms-firmware/copyright',
        common / 'usr/share/licenses/amdgpu-firmware/copyright')
    copy(amd_ctk, common / 'usr/bin/amd-ctk')
    copy(ROOT / 'scripts/amd-smi', common / 'usr/bin/amd-smi')
    copy(ROOT / 'scripts/activate', common / 'usr/lib/reefy/activate')
    for path in (
            common / 'usr/bin/amd-ctk', common / 'usr/bin/amd-smi',
            common / 'usr/lib/reefy/activate'):
        path.chmod(0o755)


def stage_kernel(modules_dir, kernel_release, kernel):
    source = modules_dir / 'lib/modules' / kernel_release / 'extra/amd'
    modules = sorted(source.glob('*.ko'))
    present = {path.stem for path in modules}
    if present != EXPECTED_MODULES:
        raise SystemExit(f'unexpected AMD module closure: {sorted(present)}')
    destination = kernel / 'lib/modules' / kernel_release / 'extra/amd'
    for module in modules:
        copy(module, destination / module.name)


def squash(source, destination):
    subprocess.run([
        'mksquashfs', str(source), str(destination),
        '-noappend', '-comp', 'xz', '-b', '1M', '-Xdict-size', '1M',
        '-all-root', '-all-time', '0', '-mkfs-time', '0', '-no-xattrs',
        '-no-progress',
    ], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--firmware-package', type=Path, required=True)
    parser.add_argument('--amd-smi-package', type=Path, required=True)
    parser.add_argument('--amd-ctk', type=Path, required=True)
    parser.add_argument('--modules-dir', type=Path, required=True)
    parser.add_argument('--kernel-release', required=True)
    parser.add_argument('--reefy-build-id', required=True)
    parser.add_argument('--kernel-abi-digest', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='reefy-amd-payload-') as temp:
        temporary = Path(temp)
        common = args.output / 'common-root'
        kernel = args.output / 'kernel-root'
        shutil.rmtree(common, ignore_errors=True)
        shutil.rmtree(kernel, ignore_errors=True)
        stage_common(
            args.firmware_package.resolve(), args.amd_smi_package.resolve(),
            args.amd_ctk.resolve(), common, temporary)
        stage_kernel(
            args.modules_dir.resolve(), args.kernel_release, kernel)
        squash(common, args.output / 'common.squashfs')
        squash(kernel, args.output / 'kernel.squashfs')

    config = {
        'artifact_schema': 1,
        'kind': 'host-extension',
        'name': 'amd-driver',
        'version': DRIVER['release'],
        'driver_version': DRIVER['version'],
        'amd_container_toolkit_version':
            VERSIONS['amd_container_toolkit']['version'],
        'amd_smi_version': AMD_SMI['version'],
        'architecture': 'x86_64',
        'publisher': 'reefyai',
        'activation_hook': 'usr/lib/reefy/activate',
        'reefy_build_id': args.reefy_build_id,
        'kernel_abi_digest': args.kernel_abi_digest,
    }
    (args.output / 'config.json').write_text(
        json.dumps(config, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
