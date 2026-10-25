from io import StringIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pyinfra import host
from pyinfra.operations import dnf, files, systemd

from suil.sdk import Module

from .certificate import junk_certificate
from .config import Config

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'
DEFAULT_CONF = Path(__file__).resolve().parent.parent / 'files' / 'default.conf'


def render(config: Config, template: str, inline: str | None = None) -> str:
    environment = Environment(loader=FileSystemLoader(TEMPLATES), trim_blocks=True,
                              lstrip_blocks=True, keep_trailing_newline=True)

    return environment.get_template(template).render(config=config, inline=inline)


def default_conf() -> str:
    return DEFAULT_CONF.read_text()


def server_text(content: str) -> str:
    return content.rstrip('\n') + '\n'


def candidate(config: Config) -> str:
    """nginx.conf with conf.d inlined, so one `nginx -t` judges the whole set."""
    parts = [default_conf()] if config.set_default else []
    parts += [server_text(content) for _, content in sorted(config.servers.items()) if content]

    return render(config, 'nginx.conf.j2', inline=''.join(parts))


class Nginx(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        if self.config.ensure == 'absent':
            return {}

        found = {
            self.config.main_file:    render(self.config, 'nginx.conf.j2'),
            self.config.default_file: default_conf() if self.config.set_default else None,
        }

        found.update({self.config.server_file(name): (server_text(content) if content else None)
                      for name, content in self.config.servers.items()})

        return found

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if scope == {}:
            return

        if self.config.ensure == 'absent':
            dnf.packages(name=f'Remove {self.config.package}', packages=[self.config.package], present=False)
            return

        fresh = _stale(self.config, facts.get('package'))

        if self.diff_touches(scope, 'package'):
            dnf.packages(
                name=f'Install {self.config.package_spec}',
                packages=[self.config.package_spec],
                present=True,
                # Cached metadata does not know a freshly published pin until it expires.
                clean=fresh,
            )

        if any(self.diff_touches(scope, key) for key in ('files', 'certificate', 'unmanaged')):
            self._validate(facts)

        changed = self._put(self.config.main_file, render(self.config, 'nginx.conf.j2'), 'Write nginx.conf',
                            facts, force)
        changed |= self._default(scope, facts, force or fresh)
        changed |= self._servers(facts, force)

        if self.config.purge:
            changed |= _purge(facts.get('unmanaged') or [])

        if self.config.manage_service and (fresh or changed or self.diff_touches(scope, 'service')):
            systemd.service(
                name=f'Ensure {self.config.service} is up',
                service=self.config.service,
                running=True,
                enabled=True,
                restarted=fresh,
                reloaded=changed and not fresh,
            )

    def check(self, facts: dict) -> list[str]:
        if self.config.ensure == 'absent':
            return []

        problems = []

        if self.config.manage_service and (facts.get('service') or {}).get('running') is not True:
            problems.append(f'{self.config.service} is not running')

        if facts.get('checked') is False:
            problems.append(f'{self.config.binary} -t rejects the live configuration')

        return problems

    def expected(self) -> dict:
        if self.config.ensure == 'absent':
            return {'package': 'absent'}

        return {
            'package':     self.config.ensure,
            'files':       {path: self.file_digest(content) for path, content in self.files().items()},
            'unmanaged':   [] if self.config.purge else None,
            'certificate': {'key_bits': self.config.ssl_key_length, 'cert': True} if self.config.set_default else None,
            'checked':     True,
            'service': {
                'running': self.config.manage_service,
                'enabled': self.config.manage_service,
            },
        }

    def _validate(self, facts: dict) -> None:
        # No binary or certificate is a clean host: there is nothing to check with.
        certificate = facts.get('certificate') or {}
        ready = facts.get('binary') and (not self.config.set_default
                                         or (certificate.get('key_bits') and certificate.get('cert')))

        if ready:
            self.validate_file(host, candidate(self.config), f'{self.config.binary} -t -q -c %s')

    def _default(self, diff, facts: dict, force: bool) -> bool:
        if not self.config.set_default:
            present = self.file_needs_write(facts, self.config.default_file, None)

            # The package installed in this run ships the file the facts cannot see yet.
            if self.file_needs_write(facts, self.config.default_file, None, force):
                files.file(name='Remove the default server', path=self.config.default_file, present=False)

            return present

        changed = _certificate(self.config, diff, facts.get('certificate') or {})
        changed |= self._put(self.config.default_file, default_conf(), 'Write the default server', facts, force)

        return changed

    def _servers(self, facts: dict, force: bool) -> bool:
        changed = False

        for name, content in sorted(self.config.servers.items()):
            path = self.config.server_file(name)

            if content:
                changed |= self._put(path, server_text(content), f'Write server {name}', facts, force)
            elif self.file_needs_write(facts, path, None):
                files.file(name=f'Remove server {name}', path=path, present=False)
                changed = True

        return changed

    def _put(self, path: str, content: str, name: str, facts: dict, force: bool) -> bool:
        changed = self.file_needs_write(facts, path, content)

        if self.file_needs_write(facts, path, content, force):
            files.put(
                name=name,
                src=StringIO(content),
                dest=path,
                user='root',
                group='root',
                mode='644',
            )

        return changed


def _stale(config: Config, reported: str | None) -> bool:
    return reported != config.ensure


def _certificate(config: Config, diff, reported: dict) -> bool:
    missing = not (reported.get('key_bits') and reported.get('cert'))
    drifted = diff is not None and any(path[0] == 'certificate' for path in diff)

    if not (missing or drifted):
        return False

    key, certificate = junk_certificate(config.ssl_key_length)

    files.directory(
        name=f'Ensure {config.cert_dir} exists',
        path=config.cert_dir,
        user='root',
        group='root',
        mode='700',
    )

    files.put(
        name='Write the default server key',
        src=StringIO(key),
        dest=config.key_file,
        user='root',
        group='root',
        mode='600',
    )

    files.put(
        name='Write the default server certificate',
        src=StringIO(certificate),
        dest=config.cert_file,
        user='root',
        group='root',
        mode='644',
    )

    return True


def _purge(unmanaged: list) -> bool:
    for path in sorted(unmanaged):
        files.file(name=f'Remove unmanaged {path}', path=path, present=False)

    return bool(unmanaged)
