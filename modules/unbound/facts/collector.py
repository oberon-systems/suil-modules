"""Reports whether the live unbound.conf checks out, what the module needs to know
about NetworkManager and resolv.conf, and the state of the service.

The digests of the files the module writes are recorded by the runner from
files()."""

import os
import subprocess

from suil.sdk import Facter


def systemctl(verb, service):
    result = subprocess.run(['systemctl', verb, service],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    return result.stdout.decode().strip() in ('active', 'enabled', 'enabled-runtime')


def checked(binary, path):
    # null, not false, when there is nothing to check with: the module cannot
    # validate before the package it installs exists, and this is what says so.
    if not os.path.isfile(binary):
        return None

    return subprocess.run([binary, path],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


class UnboundFacter(Facter):

    def collect(self) -> dict:
        config_file = self.config.get('config_file') or '/etc/unbound/unbound.conf'
        binary = self.config.get('checkconf_binary') or '/usr/sbin/unbound-checkconf'
        service = self.config.get('service') or 'unbound'
        nm_dropin = self.config.get('nm_dropin') or '/etc/NetworkManager/conf.d/90-dns-none.conf'
        resolv_conf = self.config.get('resolv_conf') or '/etc/resolv.conf'

        return {
            'checked':     checked(binary, config_file),
            'checkconf':   os.path.isfile(binary),
            'nm_dir':      os.path.isdir(os.path.dirname(nm_dropin)),
            'resolv_link': os.path.islink(resolv_conf),
            'service': {
                'running': systemctl('is-active', service),
                'enabled': systemctl('is-enabled', service),
            },
        }
