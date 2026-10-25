import hashlib
import json
import posixpath
import shlex

from io import BytesIO, StringIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pyinfra import host, logger
from pyinfra.operations import files, server, systemd

from suil.sdk import Module

from .config import Config
from .release import BINARY, GEO, check_config, fetch_release

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'

# Runs on the host: the staged document takes over the clients the live file
# holds per inbound tag, then replaces it.
MERGE = '''
import json, os, sys
staged, live = sys.argv[1:3]
document = json.load(open(staged))
try:
    kept = {inbound.get('tag'): inbound['settings']['clients']
            for inbound in json.load(open(live)).get('inbounds', [])
            if 'clients' in (inbound.get('settings') or {})}
except (OSError, ValueError):
    kept = {}
for inbound in document['inbounds']:
    settings = inbound.get('settings') or {}
    if 'clients' in settings and inbound.get('tag') in kept:
        settings['clients'] = kept[inbound['tag']]
with open(staged, 'w') as stream:
    stream.write(json.dumps(document, indent=2) + chr(10))
os.replace(staged, live)
'''


def render(config: Config, template: str) -> str:
    environment = Environment(loader=FileSystemLoader(TEMPLATES),
                              trim_blocks=True, keep_trailing_newline=True)

    return environment.get_template(template).render(config=config)


def config_text(config: Config) -> str:
    return json.dumps(config.document(), indent=2) + '\n'


def config_digest(document: dict) -> str:
    """The digest of config.json without its clients, which belong to the agent.

    facts/collector.py computes the same over the live file."""
    document = json.loads(json.dumps(document))

    for inbound in document.get('inbounds') or []:
        (inbound.get('settings') or {}).pop('clients', None)

    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def stamp_text(config: Config) -> str:
    return config.version + '\n'


class Xray(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        return {
            self.config.stamp_file: stamp_text(self.config),
            self.config.unit_file:  render(self.config, 'xray.service.j2'),
        }

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if scope == {}:
            return

        content = config_text(self.config)
        unit = render(self.config, 'xray.service.j2')

        fresh = self.file_needs_write(facts, self.config.stamp_file, stamp_text(self.config))
        written = facts.get('config') != config_digest(self.config.document())
        unit_changed = self.file_needs_write(facts, self.config.unit_file, unit)

        install = self.file_needs_write(facts, self.config.stamp_file, stamp_text(self.config), force)
        write_config = force or written
        members = None

        if install or write_config:
            server.group(name=f'Ensure group {self.config.group}', group=self.config.group, system=True)

            server.user(
                name=f'Ensure user {self.config.user}',
                user=self.config.user,
                group=self.config.group,
                home=self.config.config_dir,
                shell='/sbin/nologin',
                system=True,
                ensure_home=False,
            )

        if install:
            members = _install(self.config)

        if write_config:
            self._config(content, members)

        if self.file_needs_write(facts, self.config.unit_file, unit, force):
            files.put(
                name='Write xray.service',
                src=StringIO(unit),
                dest=self.config.unit_file,
                user='root',
                group='root',
                mode='644',
            )

            if unit_changed:
                systemd.daemon_reload(name='Reload systemd')

        restart = fresh or written or unit_changed

        if self.config.manage_service and (restart or self.diff_touches(scope, 'service')):
            systemd.service(
                name='Ensure xray is up',
                service=self.config.unit,
                running=True,
                enabled=True,
                restarted=restart,
            )

    def check(self, facts: dict) -> list[str]:
        problems = []

        if self.config.manage_service and (facts.get('service') or {}).get('running') is not True:
            problems.append(f'{self.config.unit} is not running')

        if facts.get('checked') is False:
            problems.append(f'{self.config.binary} run -test rejects {self.config.config_file}')

        return problems

    def expected(self) -> dict:
        return {
            'files':   {path: self.file_digest(content) for path, content in self.files().items()},
            'config':  config_digest(self.config.document()),
            'checked': True,
            'service': {
                'running': self.config.manage_service,
                'enabled': self.config.manage_service,
            },
        }

    def _config(self, content: str, members: dict[str, bytes] | None) -> None:
        # setgid: the agent replaces config.json with a file of its own, and only
        # the directory's group lets xray read that one.
        files.directory(
            name=f'Ensure {self.config.config_dir} exists',
            path=self.config.config_dir,
            user='root',
            group=self.config.group,
            mode='2770',
        )

        if members is not None:
            check_config(members[BINARY], content)
        else:
            self.validate_file(host, content, f'{self.config.binary} run -test -format json -c %s')

        staged = f'{self.config.config_file}.suil'

        files.put(
            name='Stage config.json',
            src=StringIO(content),
            dest=staged,
            user='root',
            group=self.config.group,
            mode='660',
        )

        server.shell(
            name='Write config.json, keeping the clients',
            commands=[f'python3 -c {shlex.quote(MERGE)} {shlex.quote(staged)} {shlex.quote(self.config.config_file)}'],
        )


def _install(config: Config) -> dict[str, bytes]:
    if not config.sha256:
        logger.warning(f'{config.suil.node}: xray sha256 is empty, {config.url} is not pinned')

    members = fetch_release(config.url, config.sha256)

    for path in (config.bin_dir, config.share_dir, posixpath.dirname(config.stamp_file)):
        files.directory(name=f'Ensure {path} exists', path=path, user='root', group='root', mode='755')

    files.put(
        name=f'Install xray {config.version}',
        src=BytesIO(members[BINARY]),
        dest=config.binary,
        user='root',
        group='root',
        mode='755',
    )

    for name in GEO:
        files.put(
            name=f'Install {name}',
            src=BytesIO(members[name]),
            dest=f'{config.share_dir}/{name}',
            user='root',
            group='root',
            mode='644',
        )

    files.put(
        name='Record the installed version',
        src=StringIO(stamp_text(config)),
        dest=config.stamp_file,
        user='root',
        group='root',
        mode='644',
    )

    return members
