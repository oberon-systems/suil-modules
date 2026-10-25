"""Reports whether the host has keys and the state of the service.

The digest of sshd_config is recorded by the runner from files()."""

import os
import subprocess

from suil.sdk import Facter


def systemctl(verb, service):
    result = subprocess.run(['systemctl', verb, service],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    return result.stdout.decode().strip() in ('active', 'enabled', 'enabled-runtime')


class SshFacter(Facter):

    def collect(self) -> dict:
        service = self.config.get('service') or 'sshd'

        return {
            'host_key': os.path.isfile('/etc/ssh/ssh_host_ed25519_key'),
            'service': {
                'running': systemctl('is-active', service),
                'enabled': systemctl('is-enabled', service),
            },
        }
