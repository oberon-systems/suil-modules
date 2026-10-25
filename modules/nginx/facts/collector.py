"""Reports the installed nginx, what else sits in conf.d, the default certificate's
key size, whether the live configuration checks out, and the state of the service.

The digests of the files the module writes are recorded by the runner from
files(). The key itself is never read into the output: only its bit length."""

import glob
import os
import re

from suil.sdk import Facter

KEY_BITS = re.compile(r'Private-Key: \((\d+) bit')


def systemctl(verb, service):
    return Facter.run(['systemctl', verb, service])[1] in ('active', 'enabled', 'enabled-runtime')


def installed(package, ensure):
    status, version = Facter.run(['rpm', '-q', '--qf', '%{VERSION}-%{RELEASE}', package])

    if status != 0:
        return 'absent'

    if ensure in ('present', 'absent'):
        return 'present'

    # A pin without a release matches any release, so only the version is reported.
    return version if '-' in ensure else version.split('-', 1)[0]


def key_bits(path):
    if not os.path.isfile(path):
        return None

    status, output = Facter.run(['openssl', 'rsa', '-in', path, '-noout', '-text'])
    match = KEY_BITS.search(output) if status == 0 else None

    return int(match.group(1)) if match else None


def checked(binary):
    if not os.path.isfile(binary):
        return None

    return Facter.run([binary, '-t', '-q'])[0] == 0


class NginxFacter(Facter):

    def collect(self) -> dict:
        package = self.config.get('package') or 'nginx'
        ensure = self.config.get('ensure') or 'present'

        if ensure == 'absent':
            return {'package': installed(package, ensure)}

        confd_dir = self.config.get('confd_dir') or '/etc/nginx/conf.d'
        cert_dir = self.config.get('cert_dir') or '/etc/nginx/cert'
        servers = self.config.get('servers') or {}
        set_default = self.config.get('set_default', True)

        keep = {'{}.conf'.format(name) for name, content in servers.items() if content}

        if set_default:
            keep.add('default.conf')
        unmanaged = None

        if self.config.get('purge', True):
            unmanaged = sorted(path for path in glob.glob(os.path.join(confd_dir, '*.conf'))
                               if os.path.basename(path) not in keep)

        return {
            'package':   installed(package, ensure),
            'unmanaged': unmanaged,
            'certificate': {
                'key_bits': key_bits(os.path.join(cert_dir, 'default.key')),
                'cert':     os.path.isfile(os.path.join(cert_dir, 'default.crt')),
            } if set_default else None,
            'checked': checked(self.config.get('binary') or '/usr/sbin/nginx'),
            'binary':  os.path.isfile(self.config.get('binary') or '/usr/sbin/nginx'),
            'service': {
                'running': systemctl('is-active', self.config.get('service') or 'nginx'),
                'enabled': systemctl('is-enabled', self.config.get('service') or 'nginx'),
            },
        }
