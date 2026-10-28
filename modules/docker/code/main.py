import json
import re
import shlex

from io import StringIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pyinfra import host
from pyinfra.operations import dnf, files, server, systemd

from suil.sdk import Module, ModuleError

from .config import Config

ROOT = Path(__file__).resolve().parent.parent
UNITS = ('docker-container@.service', 'docker-compose@.service')
ARCH = re.compile(r'\.(x86_64|aarch64|ppc64le|s390x)$')
DOCKER = '/usr/bin/docker'


def env_value(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'

    return str(value)


def systemd_exec(words: list[str]) -> str:
    """One command line for an Exec*= setting: shell-quoted, with what systemd
    would expand itself - backslashes, $ and % - escaped."""
    return shlex.join(words).replace('\\', '\\\\').replace('$', '$$').replace('%', '%%')


def environment() -> Environment:
    templates = Environment(loader=FileSystemLoader(ROOT / 'templates'), trim_blocks=True,
                            lstrip_blocks=True, keep_trailing_newline=True)
    templates.filters['env_value'] = env_value

    return templates


def render(config: Config, template: str, **context) -> str:
    return environment().get_template(template).render(node=config.suil.node, **context)


def unit_text(unit: str) -> str:
    return (ROOT / 'files' / unit).read_text()


def daemon_json(config: Config) -> str:
    return json.dumps(config.config, indent=2, sort_keys=True) + '\n'


def docker_args(config: Config, name: str, entry) -> list[str]:
    args = ['--rm'] if entry.recreate else []

    if entry.user:
        args += ['--user', entry.user]

    if entry.env:
        args += ['--env-file', config.env_file(name)]

    for port in entry.ports:
        args += ['-p', port]

    for mount in entry.mounts:
        args += ['-v', mount]

    for key, value in sorted(entry.opts.items()):
        flag = f'-{key}' if len(key) == 1 else f'--{key}'

        for item in (value if isinstance(value, list) else [value]):
            if item is None or item is False:
                continue

            if item is True:
                args.append(flag)
            elif len(key) == 1:
                args += [flag, env_value(item)]
            else:
                args.append(f'{flag}={env_value(item)}')

    return args


def run_text(config: Config, name: str, entry) -> str:
    return render(
        config, 'container-run.conf.j2',
        pull=systemd_exec([DOCKER, 'pull', entry.image]) if entry.pull else None,
        start=systemd_exec([DOCKER, 'run', '--name', name, *docker_args(config, name, entry),
                            entry.image, *entry.run_opts]),
        stop=systemd_exec([DOCKER, 'stop', '--time', str(entry.stop_timeout), name]))


def env_file(config: Config, env: dict, quoted: bool = False) -> str:
    """Compose interpolates $ in .env unless the value is single-quoted; docker run
    --env-file keeps quotes as part of the value, so a container's file gets none."""
    return render(config, 'env.j2', env=env, quoted=quoted)


def compose_text(entry) -> str:
    return entry.content.rstrip('\n') + '\n'


def dropin_text(config: Config, name: str, entry) -> str | None:
    if not entry.unit_dropin:
        return None

    text = environment().from_string(entry.unit_dropin).render(node=config.suil.node, name=name, entry=entry)

    return text.rstrip('\n') + '\n'


def modules_extra(config: Config, kernel: str) -> str:
    return f'{config.modules_extra}-{ARCH.sub("", kernel.strip())}'


def stack_action(entry, changed: bool) -> tuple[bool, bool]:
    """(restarted, reloaded) for a stack whose files changed."""
    return changed and entry.recreate, changed and not entry.recreate


def engine_action(config: Config, fresh: bool, changed: bool) -> tuple[bool, bool]:
    """(restarted, reloaded) for docker itself."""
    restarted = fresh or (changed and config.restart)

    return restarted, changed and not restarted


def container_files(config: Config, name: str, entry) -> dict:
    unit = config.container_unit(name)

    return {
        config.env_file(name):    env_file(config, entry.env) if entry.env else None,
        config.run_file(unit):    run_text(config, name, entry),
        config.dropin_file(unit): dropin_text(config, name, entry),
    }


def stack_directories(config: Config, name: str, entry) -> dict:
    """Each declared directory by its host path, owned by the stack's account unless it names another."""
    return {config.stack_directory(name, path): {'owner': name if item.owner is None else item.owner,
                                                 'group': name if item.group is None else item.group,
                                                 'mode':  item.mode}
            for path, item in entry.directories.items()}


def stack_files(config: Config, name: str, entry) -> dict:
    return {
        config.compose_file(name):                   compose_text(entry),
        config.env_file(name):                       env_file(config, entry.env, quoted=True) if entry.env else None,
        config.dropin_file(config.stack_unit(name)): dropin_text(config, name, entry),
    }


class Docker(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        if self.config.ensure == 'absent':
            return {}

        found = {self.config.modules_load_file: 'br_netfilter\n', self.config.config_file: daemon_json(self.config)}
        found.update({f'{self.config.unit_dir}/{unit}': unit_text(unit) for unit in UNITS})

        for name, entry in self.config.containers.items():
            if entry.ensure != 'absent':
                found.update(container_files(self.config, name, entry))

        for name, entry in self.config.compose.stacks.items():
            if entry.ensure != 'absent':
                found.update(stack_files(self.config, name, entry))

        return found

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if scope == {}:
            return

        if self.config.ensure == 'absent':
            dnf.packages(
                name='Remove docker',
                packages=[self.config.package, self.config.cli_package, self.config.compose_package],
                present=False,
            )
            return

        fresh = _stale(self.config, facts.get('packages') or {})

        if self.diff_touches(scope, 'modules_extra'):
            if not facts.get('kernel'):
                raise ModuleError(f'{self.config.suil.node}: the docker facts carry no running kernel')

            # The bare name resolves to the newest kernel build and drags that kernel in,
            # and docker-ce pulls the bare name itself unless this pin lands first.
            dnf.packages(
                name=f'Install {self.config.modules_extra} for the running kernel',
                packages=[modules_extra(self.config, facts['kernel'])],
                present=True,
            )

        if self.diff_touches(scope, 'packages'):
            dnf.packages(
                name='Install docker',
                packages=self.config.packages,
                present=True,
                clean=fresh,
            )

            if self.config.compose.ensure == 'absent':
                dnf.packages(name=f'Remove {self.config.compose_package}', packages=[self.config.compose_package],
                             present=False)

        if self.diff_touches(scope, 'br_netfilter'):
            server.modprobe(name='Load br_netfilter', module='br_netfilter')

        self._put(self.config.modules_load_file, 'br_netfilter\n', 'Load br_netfilter on boot', '644', facts, force)

        if self.diff_touches(scope, 'ip_forward'):
            server.sysctl(
                name='Turn ip forwarding on',
                key='net.ipv4.ip_forward',
                value=1,
                persist=True,
                persist_file=self.config.sysctl_file,
            )

        content = daemon_json(self.config)
        changed = self.file_needs_write(facts, self.config.config_file, content)

        if self.file_needs_write(facts, self.config.config_file, content, force):
            files.directory(
                name=f'Ensure {Path(self.config.config_file).parent} exists',
                path=str(Path(self.config.config_file).parent),
                user='root',
                group='root',
                mode='755',
            )

            self._validate(content, facts)
            self._put(self.config.config_file, content, 'Write daemon.json', '644', facts, force)

        units = False

        for unit in UNITS:
            units |= self._put(f'{self.config.unit_dir}/{unit}', unit_text(unit), f'Install {unit}', '644',
                               facts, force)

        if self.config.manage_service and (fresh or changed or units or self.diff_touches(scope, 'service')):
            restarted, reloaded = engine_action(self.config, fresh, changed)

            systemd.service(
                name=f'Ensure {self.config.service} is up',
                service=self.config.service,
                running=True,
                enabled=True,
                restarted=restarted,
                reloaded=reloaded,
                daemon_reload=units,
            )

        # A changed shared unit is every instance's change.
        self._containers(scope, units, facts, force)
        self._stacks(scope, units, facts, force)

        if self.config.purge:
            _purge(self.config, facts.get('unmanaged') or {})

        # What the layout before /opt left behind: its unit.env went with it.
        for path in facts.get('legacy') or []:
            files.directory(name=f'Remove the old layout {path}', path=path, present=False)

    def check(self, facts: dict) -> list[str]:
        if self.config.ensure == 'absent' or not self.config.manage_service:
            return []

        problems = [f'{self.config.service} is not running'] if not _running(facts) else []

        for kind, unit, declared in (('containers', self.config.container_unit, self.config.containers),
                                     ('stacks', self.config.stack_unit, self.config.compose.stacks)):
            reported = facts.get(kind) or {}

            problems += [f'{unit(name)} is not running' for name, entry in sorted(declared.items())
                         if entry.ensure != 'absent' and not _running(reported.get(name))]

        return problems

    def expected(self) -> dict:
        if self.config.ensure == 'absent':
            return {'packages': {self.config.package: 'absent'}}

        return {
            'packages': {
                self.config.package:         self.config.ensure,
                self.config.compose_package: self.config.compose.ensure,
            },
            'files':         {path: self.file_digest(content) for path, content in self.files().items()},
            'br_netfilter':  True,
            'ip_forward':    True,
            'modules_extra': True,
            'service':       _state(self.config.manage_service),
            'containers':    {name: _expected_entry(self.config, entry)
                              for name, entry in self.config.containers.items()},
            'stacks':        {name: _expected_stack(self.config, name, entry)
                              for name, entry in self.config.compose.stacks.items()},
            'unmanaged':     {'containers': [], 'stacks': []} if self.config.purge else None,
            'legacy':        [],
        }

    def _validate(self, content: str, facts: dict) -> None:
        if facts.get('dockerd'):
            self.validate_file(host, content, f'{self.config.dockerd_binary} --validate --config-file %s')

    def _selected(self, scope, kind: str, name: str, paths, restart: bool) -> bool:
        return (restart or self.diff_touches(scope, kind, name)
                or any(self.diff_touches(scope, 'files', path) for path in paths))

    def _containers(self, scope, restart: bool, facts: dict, force: bool) -> None:
        reported = facts.get('containers') or {}

        for name, entry in sorted(self.config.containers.items()):
            unit = self.config.container_unit(name)
            current = reported.get(name) or {}

            if entry.ensure == 'absent':
                if self.diff_touches(scope, 'containers', name):
                    _remove(self.config, name, unit, current.get('present'))
                continue

            wanted = container_files(self.config, name, entry)

            if not self._selected(scope, 'containers', name, wanted, restart):
                continue

            _home(self.config, name, force or not current.get('present'))

            if entry.env:
                changed = self._put(self.config.env_file(name), wanted[self.config.env_file(name)],
                                    f'Write the environment of container {name}', '600', facts, force, owner=name)
            else:
                changed = self._absent(self.config.env_file(name), f'Remove the environment of container {name}', facts)

            reload = self._dropin(self.config.run_file(unit), wanted[self.config.run_file(unit)],
                                  f'Write the docker run of {unit}', facts, force)
            reload |= self._dropin(self.config.dropin_file(unit), wanted[self.config.dropin_file(unit)],
                                   f'Write the drop-in of {unit}', facts, force)
            restarted = changed or reload or restart

            if force or restarted or not _running(current):
                _service(self.config, unit, restarted=restarted, reloaded=False, daemon_reload=reload)

    def _stacks(self, scope, restart: bool, facts: dict, force: bool) -> None:
        reported = facts.get('stacks') or {}

        for name, entry in sorted(self.config.compose.stacks.items()):
            unit = self.config.stack_unit(name)
            current = reported.get(name) or {}

            if entry.ensure == 'absent':
                if self.diff_touches(scope, 'stacks', name):
                    _remove(self.config, name, unit, current.get('present'))
                continue

            wanted = stack_files(self.config, name, entry)

            if not self._selected(scope, 'stacks', name, wanted, restart):
                continue

            _home(self.config, name, force or not current.get('present'))

            # Before compose up: docker creates a missing bind mount source as root.
            for path, item in stack_directories(self.config, name, entry).items():
                if force or self.diff_touches(scope, 'stacks', name, 'directories', path):
                    files.directory(name=f'Ensure {path} exists', path=path, user=str(item['owner']),
                                    group=str(item['group']), mode=item['mode'])

            changed = self._put(self.config.compose_file(name), wanted[self.config.compose_file(name)],
                                f'Write the compose file of stack {name}', '600', facts, force, owner=name)

            if entry.env:
                changed |= self._put(self.config.env_file(name), wanted[self.config.env_file(name)],
                                     f'Write the .env of stack {name}', '600', facts, force, owner=name)
            else:
                changed |= self._absent(self.config.env_file(name), f'Remove the .env of stack {name}', facts)

            reload = self._dropin(self.config.dropin_file(unit), wanted[self.config.dropin_file(unit)],
                                  f'Write the drop-in of {unit}', facts, force)
            restarted, reloaded = stack_action(entry, changed)

            if force or restarted or reloaded or reload or restart or not _running(current):
                _service(self.config, unit, restarted=restarted or reload or restart, reloaded=reloaded,
                         daemon_reload=reload)

    def _dropin(self, path: str, text: str | None, name: str, facts: dict, force: bool) -> bool:
        if text is None:
            if not self.file_needs_write(facts, path, None):
                return False

            files.file(name=f'Remove {path}', path=path, present=False)
            return True

        if self.file_needs_write(facts, path, text, force):
            files.directory(name=f'Ensure {Path(path).parent} exists', path=str(Path(path).parent),
                            user='root', group='root', mode='755')

        return self._put(path, text, name, '644', facts, force)

    def _absent(self, path: str, name: str, facts: dict) -> bool:
        if not self.file_needs_write(facts, path, None):
            return False

        files.file(name=name, path=path, present=False)
        return True

    def _put(self, path: str, content: str, name: str, mode: str, facts: dict, force: bool,
             owner: str = 'root') -> bool:
        changed = self.file_needs_write(facts, path, content)

        if self.file_needs_write(facts, path, content, force):
            files.put(
                name=name,
                src=StringIO(content),
                dest=path,
                user=owner,
                group=owner,
                mode=mode,
            )

        return changed


def _expected_entry(config: Config, entry) -> dict:
    if entry.ensure == 'absent':
        return {'present': False, 'service': _state(False)}

    return {'present': True, 'service': _state(config.manage_service)}


def _expected_stack(config: Config, name: str, entry) -> dict:
    expected = _expected_entry(config, entry)

    if entry.ensure != 'absent':
        expected['directories'] = stack_directories(config, name, entry)

    return expected


def _state(on: bool) -> dict:
    return {'running': on, 'enabled': on}


def _running(reported) -> bool:
    return ((reported or {}).get('service') or {}).get('running') is True


def _stale(config: Config, reported: dict) -> bool:
    return reported.get(config.package) != config.ensure


def _home(config: Config, name: str, needed: bool) -> None:
    """The entry's own account, a plain one, and its home, where its files live."""
    if not needed:
        return

    directory = config.entry_dir(name)

    server.group(name=f'Ensure group {name}', group=name, system=True)
    server.user(name=f'Ensure user {name}', user=name, group=name, home=directory,
                shell='/sbin/nologin', system=True, create_home=False)
    files.directory(name=f'Ensure {directory} exists', path=directory, user=name, group=name, mode='750')


def _service(config: Config, unit: str, restarted: bool, reloaded: bool, daemon_reload: bool) -> None:
    if not config.manage_service:
        return

    systemd.service(
        name=f'Ensure {unit} is up',
        service=unit,
        running=True,
        enabled=True,
        restarted=restarted,
        reloaded=reloaded and not restarted,
        daemon_reload=daemon_reload,
    )


def _remove(config: Config, name: str, unit: str, present: bool) -> None:
    # Stopped before the files go: `compose down` still needs the stack's document.
    if config.manage_service and present:
        systemd.service(name=f'Stop {unit}', service=unit, running=False, enabled=False)

    files.directory(name=f'Remove {config.entry_dir(name)}', path=config.entry_dir(name), present=False)
    files.directory(name=f'Remove the drop-ins of {unit}', path=f'{config.unit_dir}/{unit}.d', present=False)
    server.user(name=f'Remove user {name}', user=name, present=False)
    server.group(name=f'Remove group {name}', group=name, present=False)


def _purge(config: Config, unmanaged: dict) -> None:
    for kind, unit in (('containers', config.container_unit), ('stacks', config.stack_unit)):
        for name in unmanaged.get(kind) or []:
            _remove(config, name, unit(name), True)
