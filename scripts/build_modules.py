#!/usr/bin/env python3
"""Build and sign AMD 31.40 modules for one exact Reefy kernel tree."""

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MODULE_ROOT = Path('/lib/modules')
DRIVER = json.loads((ROOT / 'versions.json').read_text())['amd_gpu_driver']
MODULES = {
    'amdgpu': 'amd/amdgpu/amdgpu.ko',
    'amdkcl': 'amd/amdkcl/amdkcl.ko',
    'amdxcp': 'amd/amdxcp/amdxcp.ko',
    'amdttm': 'ttm/amdttm.ko',
    'amd-sched': 'scheduler/amd-sched.ko',
    'amddrm_ttm_helper': 'amddrm_ttm_helper.ko',
    'amddrm_buddy': 'amddrm_buddy.ko',
    'amddrm_exec': 'amddrm_exec.ko',
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_package(path):
    if path.stat().st_size != DRIVER['package_bytes']:
        raise SystemExit('AMD driver package size mismatch')
    if sha256(path) != DRIVER['package_sha256']:
        raise SystemExit('AMD driver package SHA-256 mismatch')


def source_root(extracted):
    candidates = list((extracted / 'usr/src').glob('amdgpu-*'))
    if len(candidates) != 1:
        raise SystemExit('AMD DKMS source layout changed')
    changelog = extracted / 'usr/share/doc/amdgpu-dkms/changelog.Debian.gz'
    result = subprocess.run(
        ['gzip', '-cd', str(changelog)], capture_output=True, text=True,
        check=True)
    if DRIVER['source_commit'] not in result.stdout:
        raise SystemExit('AMD DKMS source commit mismatch')
    return candidates[0]


@contextlib.contextmanager
def dkms_kernel_link(kernel, kernel_release):
    """Expose the exact tree at the path hard-coded by AMD DKMS scripts."""
    release_dir = MODULE_ROOT / kernel_release
    link = release_dir / 'build'
    created = False
    if link.exists() or link.is_symlink():
        if link.resolve() != kernel.resolve():
            raise SystemExit(f'conflicting DKMS kernel build link: {link}')
    else:
        release_dir.mkdir(parents=True, exist_ok=True)
        link.symlink_to(kernel.resolve(), target_is_directory=True)
        created = True
    try:
        yield
    finally:
        if created:
            link.unlink(missing_ok=True)
            try:
                release_dir.rmdir()
            except OSError:
                pass


def build(source, kernel, kernel_release, toolchain_prefix):
    environment = os.environ.copy()
    environment.update({
        'ARCH': 'x86',
        'CROSS_COMPILE': toolchain_prefix,
        'CC': toolchain_prefix + 'gcc',
        'LD': toolchain_prefix + 'ld',
        'AR': toolchain_prefix + 'ar',
        'NM': toolchain_prefix + 'nm',
        'OBJCOPY': toolchain_prefix + 'objcopy',
        'OBJDUMP': toolchain_prefix + 'objdump',
        'STRIP': toolchain_prefix + 'strip',
    })
    with dkms_kernel_link(kernel, kernel_release):
        subprocess.run([
            'make', '-C', str(source),
            f'KERNELVER={kernel_release}',
            f'kernel_build_dir={kernel}',
            'CONFIG_DRM_SUBALLOC_HELPER=', 'modules',
        ], env=environment, check=True)


def stage_and_sign(source, kernel, kernel_release, output):
    destination = (
        output / 'lib/modules' / kernel_release / 'extra/amd')
    shutil.rmtree(output, ignore_errors=True)
    destination.mkdir(parents=True)
    sign_file = kernel / 'scripts/sign-file'
    signing_key = kernel / 'certs/signing_key.pem'
    signing_certificate = kernel / 'certs/signing_key.x509'
    for name, relative in MODULES.items():
        module = source / relative
        if not module.is_file():
            raise SystemExit(f'missing AMD module {name}: {module}')
        target = destination / module.name
        shutil.copy2(module, target)
        subprocess.run([
            str(sign_file), 'sha512', str(signing_key),
            str(signing_certificate), str(target),
        ], check=True)

    unexpected = list(source.rglob('amddrm_suballoc_helper.ko'))
    if unexpected:
        raise SystemExit(
            'AMD build produced conflicting amddrm_suballoc_helper.ko')
    staged = {path.stem for path in destination.glob('*.ko')}
    if staged != set(MODULES):
        raise SystemExit(f'unexpected AMD module closure: {sorted(staged)}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--driver-package', type=Path, required=True)
    parser.add_argument('--kernel-dir', type=Path, required=True)
    parser.add_argument('--kernel-release', required=True)
    parser.add_argument('--toolchain-prefix', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify_package(args.driver_package)
    with tempfile.TemporaryDirectory(prefix='reefy-amd-modules-') as temporary:
        extracted = Path(temporary) / 'extracted'
        subprocess.run([
            'dpkg-deb', '--extract', str(args.driver_package), str(extracted),
        ], check=True)
        source = source_root(extracted)
        build(
            source, args.kernel_dir.resolve(), args.kernel_release,
            args.toolchain_prefix)
        stage_and_sign(
            source, args.kernel_dir.resolve(), args.kernel_release,
            args.output.resolve())


if __name__ == '__main__':
    main()
