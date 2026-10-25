"""Reports the installed agent and the state of the service.

The digests of agent.env and the drop-in are recorded by the runner from
files(); agent.env carries the token, so only its digest ever leaves the host."""

from suil.sdk import Facter


def systemctl(verb, service):
    return Facter.run(['systemctl', verb, service])[1] in ('active', 'enabled', 'enabled-runtime')


class AwgKeeperFacter(Facter):

    def collect(self) -> dict:
        package = self.config.get('package') or 'awg-keeper-agent'
        unit = self.config.get('unit') or 'awg-keeper-agent.service'

        status, version = Facter.run(['rpm', '-q', '--qf', '%{VERSION}-%{RELEASE}', package])

        return {
            'package': version if status == 0 else None,
            'service': {
                'running': systemctl('is-active', unit),
                'enabled': systemctl('is-enabled', unit),
            },
        }
