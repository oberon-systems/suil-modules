"""Reports whether the live firewall has drifted from the saved ruleset, and the
state of the unit.

The digests of the ruleset, the scripts and the units are recorded by the
runner from files()."""

import subprocess

from suil.sdk import Facter


def drifted(script):
    # A first run has no script yet; that reads as drift, so the unit is started.
    try:
        return subprocess.run([script, 'diff'], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode != 0
    except OSError:
        return True


def systemctl(verb, unit):
    result = subprocess.run(['systemctl', verb, unit],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    return result.stdout.decode().strip() in ('active', 'enabled', 'enabled-runtime')


class NftablesFacter(Facter):

    def collect(self) -> dict:
        unit = self.config['unit'] + '.service'

        return {
            'drift':   drifted(self.config.get('apply_script') or '/usr/local/sbin/nftables-apply.sh'),
            'service': {
                'running': systemctl('is-active', unit),
                'enabled': systemctl('is-enabled', unit),
            },
        }
