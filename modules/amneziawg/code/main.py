from io import StringIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pyinfra.operations import dnf, files, server, systemd

from suil.sdk import Module

from .config import Config, Interface

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'

# What the device can disagree with its own file about.
DRIFT = ('peers', 'public_key')


def render(config: Config, name: str) -> str:
    environment = Environment(loader=FileSystemLoader(TEMPLATES),
                              trim_blocks=True, keep_trailing_newline=True)

    return environment.get_template('awg.conf.j2').render(
        name=name, node=config.suil.node, interface=config.interfaces[name].model_dump(),
        obfuscation=config.effective_obfuscation(name))


def dropin_text(config: Config, name: str) -> str:
    interface = config.interfaces[name]
    lines = [
        f'# Managed by suil, module `amneziawg`, interface {name} on {config.suil.node}.',
        '# The agent rewrites the file from showconf, which carries no Address or MTU.',
        '[Service]',
        f'ExecStartPost=-{config.ip_binary} address replace {interface.address} dev {name}',
    ]

    if interface.mtu is not None:
        lines.append(f'ExecStartPost=-{config.ip_binary} link set mtu {interface.mtu} dev {name}')

    return '\n'.join(lines) + '\n'


class Amneziawg(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        """An interface whose peers the agent owns keeps its file out: the agent rewrites it."""
        found = {}

        for name, interface in self.config.interfaces.items():
            present = interface.ensure == 'present'
            external = present and interface.peers_external

            if not external:
                found[self.config.config_file(name)] = render(self.config, name) if present else None

            found[self.config.dropin_file(name)] = dropin_text(self.config, name) if external else None

        return found

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if scope == {}:
            return

        reported = facts.get('interfaces') or {}
        only = self.diff_names(scope, 'interfaces')
        fresh = False

        if only is not None:
            only |= {name for name in self.config.interfaces
                     if self.diff_touches(scope, 'files', self.config.config_file(name))
                     or self.diff_touches(scope, 'files', self.config.dropin_file(name))}

        if self.config.install_packages:
            # A daemon started before dnf ran holds a binary this run replaces, so
            # every interface is restarted onto the one the pin names.
            fresh = _stale(self.config, facts.get('packages') or {})

            if self.diff_touches(scope, 'packages') and (present := _wanted(self.config, absent=False)):
                dnf.packages(
                    name=f'Install {len(present)} amneziawg packages',
                    packages=present,
                    present=True,
                )

            if self.diff_touches(scope, 'packages') and (absent := _wanted(self.config, absent=True)):
                dnf.packages(
                    name=f'Remove {len(absent)} amneziawg packages',
                    packages=absent,
                    present=False,
                )

        if fresh:
            only = None

        # A gateway forwards for its peers; nothing else on the host turns this on.
        if self.config.manage_ip_forward and self.diff_touches(scope, 'ip_forward'):
            server.sysctl(
                name='Turn ip forwarding on',
                key='net.ipv4.ip_forward',
                value=1,
                persist=True,
                persist_file=self.config.sysctl_file,
            )

        if force:
            files.directory(
                name=f'Ensure {self.config.config_dir} exists',
                path=self.config.config_dir,
                user='root',
                group='root',
                mode='700',
            )

        for name, interface in sorted(self.config.interfaces.items()):
            if only is not None and name not in only:
                continue

            current = reported.get(name) or {}

            if interface.ensure == 'absent':
                self._remove(name, current, facts, force)
                continue

            service = force or self.diff_touches(scope, 'interfaces', name, 'service')
            self._interface(name, interface, fresh or _drifted(scope, name), current, facts, service, force)

    def check(self, facts: dict) -> list[str]:
        if not self.config.manage_service:
            return []

        reported = facts.get('interfaces') or {}

        return [f'{self.config.unit(name)} is not running'
                for name, interface in sorted(self.config.interfaces.items())
                if interface.ensure == 'present'
                and ((reported.get(name) or {}).get('service') or {}).get('running') is not True]

    def expected(self) -> dict:
        interfaces = {}

        for name, interface in self.config.interfaces.items():
            present = interface.ensure == 'present'
            running = present and self.config.manage_service
            external = present and interface.peers_external

            interfaces[name] = {
                'ensure':     interface.ensure,
                'public_key': interface.derived_public_key if running else None,
                'peers':      (sorted(peer.public_key for peer in interface.peers.values())
                               if running and not external else None),
                'service': {
                    'running': running,
                    'enabled': running and interface.enabled,
                },
            }

        return {
            'packages':   ({name: {'ensure': package.ensure} for name, package in self.config.packages.items()}
                           if self.config.install_packages else {}),
            'ip_forward': True if self.config.manage_ip_forward else None,
            'interfaces': interfaces,
            'files':      {path: self.file_digest(content) for path, content in self.files().items()},
        }

    def _interface(self, name: str, interface: Interface, restart: bool, current: dict,
                   facts: dict, service: bool, force: bool) -> None:
        content = render(self.config, name)
        path = self.config.config_file(name)

        if interface.peers_external:
            changed = write = current.get('ensure') != 'present'
        else:
            changed = self.file_needs_write(facts, path, content)
            write = self.file_needs_write(facts, path, content, force)

        if write:
            files.put(
                name=f'Write the configuration of {name}',
                src=StringIO(content),
                dest=path,
                user='root',
                group='root',
                mode='600',
            )

        changed |= self._dropin(name, interface, facts, force)

        if self.config.manage_service and (changed or restart or service):
            systemd.service(
                name=f'Ensure {name} is up',
                service=self.config.unit(name),
                running=True,
                enabled=interface.enabled,
                restarted=changed or restart,
            )

    def _remove(self, name: str, current: dict, facts: dict, force: bool) -> None:
        present = current.get('ensure') == 'present'

        # The unit is a shared template, so the file is what says this one exists.
        if self.config.manage_service and present:
            systemd.service(
                name=f'Stop {name}',
                service=self.config.unit(name),
                running=False,
                enabled=False,
            )

        if present or force:
            files.file(name=f'Remove the configuration of {name}', path=self.config.config_file(name), present=False)

        if self.file_needs_write(facts, self.config.dropin_file(name), None):
            files.directory(name=f'Remove the drop-in of {name}', path=self.config.dropin_dir(name), present=False)
            systemd.daemon_reload(name='Reload systemd')

    def _dropin(self, name: str, interface: Interface, facts: dict, force: bool) -> bool:
        """The address drop-in exists exactly while the agent owns the file."""
        path = self.config.dropin_file(name)
        content = dropin_text(self.config, name) if interface.peers_external else None
        changed = self.file_needs_write(facts, path, content)

        if not self.file_needs_write(facts, path, content, force):
            return False

        if content is None:
            files.directory(name=f'Remove the drop-in of {name}', path=self.config.dropin_dir(name), present=False)
        else:
            files.directory(name=f'Ensure the drop-in directory of {name}', path=self.config.dropin_dir(name),
                            user='root', group='root', mode='755')
            files.put(name=f'Write the drop-in of {name}', src=StringIO(content), dest=path,
                      user='root', group='root', mode='644')

        if changed:
            systemd.daemon_reload(name='Reload systemd')

        return changed


def _wanted(config: Config, absent: bool) -> list[str]:
    """The package arguments dnf is given, a pinned entry as name-version."""
    names = []

    for name, package in sorted(config.packages.items()):
        if (package.ensure == 'absent') != absent:
            continue

        names.append(name if package.ensure in ('present', 'absent') else f'{name}-{package.ensure}')

    return names


def _stale(config: Config, reported: dict) -> bool:
    return any((reported.get(name) or {}).get('ensure') != package.ensure
               for name, package in config.packages.items())


def _drifted(diff, name: str) -> bool:
    """The live device disagrees with the peers or the key its file declares."""
    if diff is None:
        return False

    return any(path[:3] in [('interfaces', name, key) for key in DRIFT]
               and entry.get('actual') is not None
               for path, entry in diff.items())
