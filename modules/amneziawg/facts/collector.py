"""Reports the packages, ip forwarding, and per interface whether its file is
there, the key and the peers the live device holds, and the state of its unit.

The digests of the interface files and the drop-ins are recorded by the runner
from files().

Never `awg show <iface> dump` or `showconf`: both print the private key. Every
field is asked for by name, one at a time."""

import os

from suil.sdk import Facter


def systemctl(verb, service):
    return Facter.run(['systemctl', verb, service])[1] in ('active', 'enabled', 'enabled-runtime')


def installed(package, wanted):
    status, version = Facter.run(['rpm', '-q', '--qf', '%{VERSION}-%{RELEASE}', package])

    if status != 0:
        return 'absent'

    # A pinned entry reports its version, so a drifted pin diffs; an unpinned
    # one only has to be there.
    return version if wanted not in ('present', 'absent') else 'present'


def ip_forward():
    try:
        with open('/proc/sys/net/ipv4/ip_forward') as stream:
            return stream.read().strip() == '1'
    except OSError:
        return None


def awg(binary, name, field):
    status, output = Facter.run([binary, 'show', name, field])

    return output if status == 0 else None


def interface(config, name):
    config_dir = config.get('config_dir') or '/etc/amnezia/amneziawg'
    unit = '{}@{}.service'.format(config.get('unit_prefix') or 'awg-quick', name)
    binary = config.get('awg_binary') or '/usr/bin/awg'
    found = os.path.isfile(os.path.join(config_dir, '{}.conf'.format(name)))
    spec = (config.get('interfaces') or {}).get(name) or {}
    external = bool(spec.get('peers_external')) and spec.get('ensure', 'present') == 'present'
    public_key = peers = None

    # Only what the module manages is read, or an unmanaged device would stay a
    # diff forever.
    if found and config.get('manage_service', True):
        public_key = awg(binary, name, 'public-key')

        if not external:
            listed = awg(binary, name, 'peers')
            peers = None if listed is None else sorted(line.strip() for line in listed.splitlines() if line.strip())

    return {
        'ensure':     'present' if found else 'absent',
        'public_key': public_key,
        'peers':      peers,
        'service': {
            'running': systemctl('is-active', unit),
            'enabled': systemctl('is-enabled', unit),
        },
    }


class AmneziawgFacter(Facter):

    def collect(self) -> dict:
        packages = {}

        if self.config.get('install_packages', True):
            for name, spec in (self.config.get('packages') or {}).items():
                wanted = (spec or {}).get('ensure', 'present')
                packages[name] = {'ensure': installed(name, wanted)}

        return {
            'packages':   packages,
            'ip_forward': ip_forward() if self.config.get('manage_ip_forward', True) else None,
            'interfaces': {name: interface(self.config, name) for name in self.config.get('interfaces') or {}},
        }
