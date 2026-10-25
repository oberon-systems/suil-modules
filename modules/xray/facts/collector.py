"""Reports the digest of config.json without its clients, whether it passes
`xray run -test`, and the state of the service.

The digests of the version stamp and the unit are recorded by the runner from
files()."""

import hashlib
import json
import os
import subprocess

from suil.sdk import Facter


def systemctl(verb, service):
    result = subprocess.run(['systemctl', verb, service],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    return result.stdout.decode().strip() in ('active', 'enabled', 'enabled-runtime')


def checked(binary, path):
    if not (os.path.isfile(binary) and os.path.isfile(path)):
        return None

    return subprocess.run([binary, 'run', '-test', '-c', path],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def digest(path):
    try:
        document = json.load(open(path))
    except (OSError, ValueError):
        return None

    for inbound in document.get('inbounds') or []:
        (inbound.get('settings') or {}).pop('clients', None)

    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class XrayFacter(Facter):

    def collect(self) -> dict:
        config_dir = self.config.get('config_dir') or '/usr/local/etc/xray'
        config_file = os.path.join(config_dir, 'config.json')

        return {
            'config':  digest(config_file),
            'checked': checked(os.path.join(self.config.get('bin_dir') or '/usr/local/bin', 'xray'), config_file),
            'service': {
                'running': systemctl('is-active', 'xray.service'),
                'enabled': systemctl('is-enabled', 'xray.service'),
            },
        }
