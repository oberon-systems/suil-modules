import hashlib
import io
import subprocess
import tempfile
import urllib.request
import zipfile

from functools import cache
from pathlib import Path

from suil.sdk import ModuleError, ModuleValidateError

BINARY = 'xray'
GEO = ('geoip.dat', 'geosite.dat')


@cache
def fetch_release(url: str, sha256: str = '') -> dict[str, bytes]:
    """The members of the release archive, read on the control machine.

    pyinfra's unarchive and copy check their paths while the run is planned, so
    an archive downloaded by the same run can never be unpacked on the host."""
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()

    if sha256 and hashlib.sha256(data).hexdigest() != sha256:
        raise ModuleError(f'{url} does not match sha256 {sha256}')

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return {name: archive.read(name) for name in (BINARY, *GEO)}
    except (zipfile.BadZipFile, KeyError) as error:
        raise ModuleError(f'{url} is not an Xray release archive: {error}') from error


def check_config(binary: bytes, content: str) -> None:
    """`xray run -test` on the control machine, with the binary the release carries."""
    with tempfile.TemporaryDirectory() as workdir:
        executable = Path(workdir) / BINARY
        executable.write_bytes(binary)
        executable.chmod(0o700)

        path = Path(workdir) / 'config.json'
        path.write_text(content)

        result = subprocess.run([str(executable), 'run', '-test', '-c', str(path)],
                                capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        raise ModuleValidateError('xray rejected config.json\n' + (result.stdout + result.stderr).strip())
