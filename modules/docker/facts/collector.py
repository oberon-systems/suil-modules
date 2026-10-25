"""Reports what the docker module runs and what it cannot write down as a file,
read off the disk and systemd.

The digests of daemon.json, the units and every entry's files are recorded by
the runner from files(). The docker client is never called: a wedged
daemon would hang the collector."""

import os
import re

from suil.sdk import Facter

ARCH = re.compile(r'\.(x86_64|aarch64|ppc64le|s390x)$')
WANTS = '/etc/systemd/system/multi-user.target.wants'

# Where entries lived before each got an account and a home of its own.
LEGACY = ('/etc/docker/containers', '/etc/docker/compose')


def systemctl(verb, unit):
    return Facter.run(['systemctl', verb, unit])[1] in ('active', 'enabled', 'enabled-runtime')


def state(unit):
    return {'running': systemctl('is-active', unit), 'enabled': systemctl('is-enabled', unit)}


def read(path):
    try:
        with open(path) as stream:
            return stream.read().strip()
    except OSError:
        return None


def installed(package, ensure):
    status, version = Facter.run(['rpm', '-q', '--qf', '%{VERSION}-%{RELEASE}', package])

    if status != 0:
        return 'absent'

    if ensure in ('present', 'absent'):
        return 'present'

    return version if '-' in ensure else version.split('-', 1)[0]


def modules_extra(name):
    if not name:
        return None

    return Facter.run(['rpm', '-q', '{}-{}'.format(name, ARCH.sub('', os.uname().release))])[0] == 0


def enabled(template):
    """Instances of a template unit that systemd starts at boot."""
    prefix = template + '@'

    if not os.path.isdir(WANTS):
        return set()

    return {name[len(prefix):-len('.service')] for name in os.listdir(WANTS)
            if name.startswith(prefix) and name.endswith('.service')}


def legacy():
    return sorted(os.path.join(base, name) for base in LEGACY if os.path.isdir(base)
                  for name in os.listdir(base) if os.path.isdir(os.path.join(base, name)))


class DockerFacter(Facter):

    def collect(self) -> dict:
        package = self.config.get('package') or 'docker-ce'
        ensure = self.config.get('ensure') or 'present'

        if ensure == 'absent':
            return {'packages': {package: installed(package, ensure)}}

        compose = self.config.get('compose') or {}
        compose_package = self.config.get('compose_package') or 'docker-compose-plugin'
        base = self.config.get('dir') or '/opt'
        containers = self.config.get('containers') or {}
        stacks = compose.get('stacks') or {}

        def entry(name, unit):
            return {'present': os.path.isdir(os.path.join(base, name)), 'service': state(unit.format(name))}

        unmanaged = None

        if self.config.get('purge', True):
            unmanaged = {'containers': sorted(enabled('docker-container') - set(containers)),
                         'stacks':     sorted(enabled('docker-compose') - set(stacks))}

        return {
            'packages': {
                package:         installed(package, ensure),
                compose_package: installed(compose_package, compose.get('ensure') or 'present'),
            },
            'kernel':        os.uname().release,
            'modules_extra': modules_extra(self.config.get('modules_extra')),
            'dockerd':       os.path.isfile(self.config.get('dockerd_binary') or '/usr/bin/dockerd'),
            'br_netfilter':  os.path.isdir('/sys/module/br_netfilter'),
            'ip_forward':    read('/proc/sys/net/ipv4/ip_forward') == '1',
            'service':       state(self.config.get('service') or 'docker'),
            'containers':    {name: entry(name, 'docker-container@{}.service') for name in containers},
            'stacks':        {name: entry(name, 'docker-compose@{}.service') for name in stacks},
            'unmanaged':     unmanaged,
            'legacy':        legacy(),
        }
