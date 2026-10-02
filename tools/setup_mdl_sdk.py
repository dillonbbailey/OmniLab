"""Install the optional, pinned MDL reflection SDK in the ignored local cache.

Run with Python 3.12. No SDK binaries or shader libraries are added to the repo.
"""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request


VERSION = '2026.0.2'
NAME = 'MDL-SDK-2026.0.2-391700.2276-linux-x86-64'
SHA256 = '5aa37997647c757d27a0c16d467d5f3f26244a2303e697d4eabf0e3719b8dc19'
URL = f'https://github.com/NVIDIA/MDL-SDK/releases/download/{VERSION}/{NAME}.tgz'


def main():
    uv = shutil.which('uv')
    if not uv:
        raise SystemExit('Install uv before running this optional setup.')
    cache = Path(__file__).resolve().parents[1] / '.cache/mdl-sdk'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / 'sdk.tgz'
    if not archive.exists():
        partial = cache / 'sdk.tgz.part'
        print('Downloading NVIDIA MDL SDK (315 MB)…', flush=True)
        urllib.request.urlretrieve(URL, partial)
        if hashlib.file_digest(partial.open('rb'), 'sha256').hexdigest() != SHA256:
            raise SystemExit('SDK archive checksum does not match the pinned NVIDIA release.')
        partial.replace(archive)
    if hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest() != SHA256:
        raise SystemExit('Cached SDK archive checksum does not match the pinned NVIDIA release.')
    with tarfile.open(archive) as bundle:
        members = [member for member in bundle if member.name.startswith((NAME + '/lib/', NAME + '/mdl/'))
                   or 'license' in member.name.lower()]
        bundle.extractall(cache, members=members, filter='data')
    subprocess.run([uv, 'python', 'install', '3.10.20'], check=True)
    print('MDL reflection ready:', cache / NAME)


if __name__ == '__main__':
    main()
