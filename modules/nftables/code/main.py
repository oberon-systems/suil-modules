from io import StringIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pyinfra import host
from pyinfra.operations import files, systemd

from suil.sdk import Module

from .config import Config
from .ruleset import build

ROOT = Path(__file__).resolve().parent.parent
UNIT_DIR = '/etc/systemd/system'


class Nftables(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        found = {path: _source(Path(path).name) for path in (self.config.apply_script, self.config.resolve_script)}
        found[_completion_file(self.config)] = _source('nft.bash-completion')
        found[self.config.rules_file] = build(self.config)

        if self.config.manage_service:
            found.update({f'{UNIT_DIR}/{unit}': unit_text(self.config, unit) for unit in unit_names(self.config)})

        return found

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if scope == {}:
            return

        self._scripts(facts, force)

        content = build(self.config)
        changed = self.file_needs_write(facts, self.config.rules_file, content)

        if self.file_needs_write(facts, self.config.rules_file, content, force):
            self._ruleset(content)

        if not self.config.manage_service:
            return

        # The masks have no facts: only force puts them in place.
        if force:
            _conflicting(self.config)

        self._units(facts, force)

        restart = changed or facts.get('drift', True)

        if restart or self.diff_touches(scope, 'service'):
            _service(self.config, restart, force)

    def check(self, facts: dict) -> list[str]:
        if not self.config.manage_service:
            return []

        problems = []

        if (facts.get('service') or {}).get('running') is not True:
            problems.append(f'{self.config.unit}.service is not running')

        if facts.get('drift') is not False:
            problems.append(f'the live ruleset differs from {self.config.rules_file}')

        return problems

    def expected(self) -> dict:
        wanted = {
            'files': {path: self.file_digest(content) for path, content in self.files().items()},
            'service': {
                'running': self.config.manage_service,
                'enabled': self.config.manage_service,
            },
        }

        if self.config.manage_service:
            wanted['drift'] = False

        return wanted

    def _scripts(self, facts: dict, force: bool) -> None:
        for path in (self.config.apply_script, self.config.resolve_script):
            if self.file_needs_write(facts, path, _source(Path(path).name), force):
                files.put(
                    name=f'Install {Path(path).name}',
                    src=str(ROOT / 'files' / Path(path).name),
                    dest=path,
                    user='root',
                    group='root',
                    mode='755',
                )

        if not self.file_needs_write(facts, _completion_file(self.config), _source('nft.bash-completion'), force):
            return

        files.directory(
            name='Ensure the bash completion directory exists',
            path=self.config.completion_dir,
            user='root',
            group='root',
            mode='755',
        )

        files.put(
            name='Install the nft bash completion',
            src=str(ROOT / 'files' / 'nft.bash-completion'),
            dest=_completion_file(self.config),
            user='root',
            group='root',
            mode='644',
        )

    def _ruleset(self, content: str) -> None:
        self.validate_file(host, content, f'{self.config.nft_binary} -c -f %s')

        for path in (str(Path(self.config.rules_file).parent), self.config.state_dir):
            files.directory(
                name=f'Ensure {path} exists',
                path=path,
                user='root',
                group='root',
                mode='700',
            )

        files.put(
            name='Write the ruleset',
            src=StringIO(content),
            dest=self.config.rules_file,
            user='root',
            group='root',
            mode='600',
        )

    def _units(self, facts: dict, force: bool) -> None:
        changed = False

        for unit in unit_names(self.config):
            path = f'{UNIT_DIR}/{unit}'
            content = unit_text(self.config, unit)

            if not self.file_needs_write(facts, path, content, force):
                continue

            changed |= self.file_needs_write(facts, path, content)

            files.put(
                name=f'Install {unit}',
                src=StringIO(content),
                dest=path,
                user='root',
                group='root',
                mode='644',
            )

        if changed:
            systemd.daemon_reload(name='Reload systemd')


def unit_names(config: Config) -> list[str]:
    units = [f'{config.unit}.service']

    if config.resolve_dns:
        units += [f'{config.unit}-resolve.service', f'{config.unit}-resolve.timer']

    return units


def unit_text(config: Config, unit: str) -> str:
    environment = Environment(loader=FileSystemLoader(ROOT / 'templates'),
                              trim_blocks=True, keep_trailing_newline=True)

    # The templates are named after the default unit name; a renamed unit
    # still renders from them.
    source = unit.replace(config.unit, 'nftables-suil', 1) + '.j2'

    return environment.get_template(source).render(config.model_dump(exclude={'suil'}))


def _source(name: str) -> str:
    return (ROOT / 'files' / name).read_text()


def _completion_file(config: Config) -> str:
    return f'{config.completion_dir}/nft'


def _conflicting(config: Config) -> None:
    if not config.disable_conflicting:
        return

    for service in config.conflicting_services:
        # Two firewalls programming the same inet family is one firewall too
        # many, and on Rocky firewalld arrives with @core regardless.
        systemd.service(
            name=f'Stop and disable {service}',
            service=f'{service}.service',
            running=False,
            enabled=False,
        )

        # A mask IS a symlink to /dev/null; systemd.service has no masked flag.
        files.link(
            name=f'Mask {service}',
            path=f'{UNIT_DIR}/{service}.service',
            target='/dev/null',
        )


def _service(config: Config, restart: bool, force: bool) -> None:
    # `running` is deliberately unmanaged here: the stock unit's ExecStop is
    # `nft flush ruleset`, and stopping it would wipe the live firewall.
    if force:
        systemd.service(
            name=f'Keep the stock {config.service} service out of the boot sequence',
            service=f'{config.service}.service',
            enabled=False,
        )

    systemd.service(
        name='Apply the ruleset',
        service=f'{config.unit}.service',
        running=True,
        enabled=True,
        restarted=restart,
    )

    if config.resolve_dns and force:
        systemd.service(
            name='Ensure the set refresh timer is running',
            service=f'{config.unit}-resolve.timer',
            running=True,
            enabled=True,
        )
