from io import StringIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pyinfra import host
from pyinfra.operations import dnf, files, systemd

from suil.sdk import Module

from .config import Config

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'

NM_DROPIN = """# Managed by suil, module `unbound`.
# NetworkManager rewrites resolv.conf on every network event unless told not to.
[main]
dns=none
"""


def render(config: Config, template: str) -> str:
    environment = Environment(loader=FileSystemLoader(TEMPLATES),
                              trim_blocks=True, keep_trailing_newline=True)

    return environment.get_template(template).render(config.model_dump())


class Unbound(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        found = {self.config.config_file: render(self.config, 'unbound.conf.j2')}

        if self.config.manage_resolv_conf:
            found[self.config.resolv_conf] = render(self.config, 'resolv.conf.j2')
            found[self.config.nm_dropin] = NM_DROPIN

        return found

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if scope == {}:
            return

        if self.config.install_packages and (force or not facts.get('checkconf')):
            dnf.packages(
                name=f'Install {self.config.package}',
                packages=[self.config.package],
                present=True,
            )

        content = render(self.config, 'unbound.conf.j2')
        changed = self.file_needs_write(facts, self.config.config_file, content)

        if self.file_needs_write(facts, self.config.config_file, content, force):
            # No checker is a clean host: there is nothing to check with.
            if facts.get('checkconf'):
                self.validate_file(host, content, f'{self.config.checkconf_binary} %s')

            files.put(
                name='Write unbound.conf',
                src=StringIO(content),
                dest=self.config.config_file,
                user='root',
                group=self.config.config_group,
                mode='640',
            )

        if self.config.manage_service and (changed or self.diff_touches(scope, 'service')):
            systemd.service(
                name=f'Ensure {self.config.service} is up',
                service=self.config.service,
                running=True,
                enabled=True,
                restarted=changed,
            )

        if self.config.manage_resolv_conf:
            self._resolv(facts, force)

    def check(self, facts: dict) -> list[str]:
        problems = []

        if self.config.manage_service and (facts.get('service') or {}).get('running') is not True:
            problems.append(f'{self.config.service} is not running')

        if facts.get('checked') is False:
            problems.append(f'{self.config.checkconf_binary} rejects {self.config.config_file}')

        return problems

    def expected(self) -> dict:
        # A host without NetworkManager never has the drop-in, so it cannot be converged on.
        watched = {path: content for path, content in self.files().items() if path != self.config.nm_dropin}

        return {
            'files':   {path: self.file_digest(content) for path, content in watched.items()},
            'checked': True,
            'service': {
                'running': self.config.manage_service,
                'enabled': self.config.manage_service,
            },
        }

    def _resolv(self, facts: dict, force: bool) -> None:
        if facts.get('nm_dir'):
            changed = self.file_needs_write(facts, self.config.nm_dropin, NM_DROPIN)

            if self.file_needs_write(facts, self.config.nm_dropin, NM_DROPIN, force):
                files.put(
                    name='Take resolv.conf away from NetworkManager',
                    src=StringIO(NM_DROPIN),
                    dest=self.config.nm_dropin,
                    user='root',
                    group='root',
                    mode='644',
                )

            # It lets go of the file only once it has reloaded, so this has to
            # happen before the file below is written, not after.
            if changed:
                systemd.service(
                    name='Reload NetworkManager',
                    service='NetworkManager.service',
                    reloaded=True,
                )

        content = render(self.config, 'resolv.conf.j2')

        if not (facts.get('resolv_link') or self.file_needs_write(facts, self.config.resolv_conf, content, force)):
            return

        # Otherwise the write follows the link into /run and the next boot loses it.
        if facts.get('resolv_link'):
            files.file(
                name='Remove the resolv.conf symlink',
                path=self.config.resolv_conf,
                present=False,
            )

        files.put(
            name='Point the host at its own resolver',
            src=StringIO(content),
            dest=self.config.resolv_conf,
            user='root',
            group='root',
            mode='644',
        )
