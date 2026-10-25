"""Reports the state of exactly the packages the module manages."""

import subprocess

from suil.sdk import Facter


def installed(name):
    result = subprocess.run(
        ['rpm', '-q', '--qf', '%{VERSION}-%{RELEASE}', name],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    return result.stdout.decode().strip() if result.returncode == 0 else None


class PackagesFacter(Facter):

    def collect(self) -> dict:
        report = {}

        for name, spec in (self.config.get('list') or {}).items():
            wanted = (spec or {}).get('ensure', 'present')
            version = installed(name)

            if version is None:
                ensure = 'absent'
            elif wanted not in ('present', 'absent'):
                # A pinned entry is reported as its version, so a drifted pin diffs.
                ensure = version
            else:
                ensure = 'present'

            report[name] = {'ensure': ensure}

        return {'list': report}
