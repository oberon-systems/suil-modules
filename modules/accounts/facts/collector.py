"""Reports the state of exactly the accounts the module manages.

The sudoers drop-ins are recorded by the runner from files()."""

import grp
import os
import pwd

from suil.sdk import Facter


def authorized_keys(entry):
    content = Facter.read(os.path.join(entry.pw_dir, '.ssh', 'authorized_keys'))

    if not content:
        return None

    # One key per account is what the module writes; report the first non-comment.
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            return Facter.digest(line)

    return None


class AccountsFacter(Facter):

    def collect(self) -> dict:
        report = {}

        for name in (self.config.get('users') or {}):
            try:
                entry = pwd.getpwnam(name)
            except KeyError:
                report[name] = {'ensure': 'absent'}
                continue

            report[name] = {
                'ensure':   'present',
                'shell':    entry.pw_shell,
                'auth_key': authorized_keys(entry),
                'groups':   sorted(group.gr_name for group in grp.getgrall() if name in group.gr_mem),
            }

        return {'users': report, 'groups': sorted(group.gr_name for group in grp.getgrall())}
