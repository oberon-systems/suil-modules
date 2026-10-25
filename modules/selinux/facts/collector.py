"""Reports the mode the running kernel is in, which is not what the file says
until the machine reboots.

The digest of /etc/selinux/config is recorded by the runner from files()."""

from suil.sdk import Facter

ENFORCE = '/sys/fs/selinux/enforce'


def mode(path):
    # No selinuxfs at all is a kernel running without the policy: disabled.
    try:
        with open(path) as stream:
            return 'enforcing' if stream.read().strip() == '1' else 'permissive'
    except OSError:
        return 'disabled'


class SelinuxFacter(Facter):

    def collect(self) -> dict:
        return {'mode': mode(self.config.get('enforce_file') or ENFORCE)}
