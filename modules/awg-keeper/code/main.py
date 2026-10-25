from io import StringIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pyinfra import logger
from pyinfra.operations import dnf, files, systemd

from suil.sdk import Module

from .config import Config

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'


def render(config: Config, template: str) -> str:
    environment = Environment(loader=FileSystemLoader(TEMPLATES),
                              trim_blocks=True, keep_trailing_newline=True)

    return environment.get_template(template).render(config=config)


def dropin_text(config: Config) -> str | None:
    return config.unit_dropin.strip() + '\n' if config.unit_dropin else None


class AwgKeeper(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        return {
            self.config.env_file:    render(self.config, 'agent.env.j2'),
            self.config.dropin_file: dropin_text(self.config),
        }

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if scope == {}:
            return

        fresh = _stale(self.config, facts.get('package'))

        if self.diff_touches(scope, 'package'):
            _install(self.config)

        # The package mints a token of its own on a first install; the file is
        # written after it, so the token the Panel was given wins.
        env = render(self.config, 'agent.env.j2')
        written = self.file_needs_write(facts, self.config.env_file, env)

        if self.file_needs_write(facts, self.config.env_file, env, force):
            files.put(name='Write agent.env', src=StringIO(env), dest=self.config.env_file,
                      user='root', group='root', mode='600')

        written |= self._dropin(facts, force)
        restart = fresh or written

        if self.config.manage_service and (restart or self.diff_touches(scope, 'service')):
            systemd.service(
                name=f'Ensure {self.config.unit} is up',
                service=self.config.unit,
                running=True,
                enabled=True,
                restarted=restart,
            )

    def check(self, facts: dict) -> list[str]:
        if self.config.manage_service and (facts.get('service') or {}).get('running') is not True:
            return [f'{self.config.unit} is not running']

        return []

    def expected(self) -> dict:
        return {
            'package': self.config.package_version,
            'files':   {path: self.file_digest(content) for path, content in self.files().items()},
            'service': {
                'running': self.config.manage_service,
                'enabled': self.config.manage_service,
            },
        }

    def _dropin(self, facts: dict, force: bool) -> bool:
        content = dropin_text(self.config)
        changed = self.file_needs_write(facts, self.config.dropin_file, content)

        if not self.file_needs_write(facts, self.config.dropin_file, content, force):
            return False

        if content is None:
            files.directory(name='Remove the agent drop-in', path=self.config.dropin_dir, present=False)
        else:
            files.directory(name='Ensure the agent drop-in directory', path=self.config.dropin_dir,
                            user='root', group='root', mode='755')
            files.put(name='Write the agent drop-in', src=StringIO(content), dest=self.config.dropin_file,
                      user='root', group='root', mode='644')

        if changed:
            systemd.daemon_reload(name='Reload systemd')

        return changed


def _stale(config: Config, reported: str | None) -> bool:
    return reported != config.package_version


def _install(config: Config) -> None:
    if not config.sha256:
        logger.warning(f'{config.suil.node}: awg-keeper sha256 is empty, {config.url} is not pinned')

    files.directory(
        name=f'Ensure {config.download_dir} exists',
        path=config.download_dir,
        user='root',
        group='root',
        mode='700',
    )

    files.download(
        name=f'Fetch {config.artifact_name}',
        src=config.url,
        dest=config.artifact_path,
        sha256sum=config.sha256 or None,
    )

    # nfpm signs nothing, and dnf does not gpg-check a local file by default.
    dnf.packages(
        name=f'Install {config.package} {config.package_version}',
        packages=[config.artifact_path],
        present=True,
    )
