from io import StringIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pyinfra import host
from pyinfra.operations import files, systemd

from suil.sdk import Module, ModuleValidateError

from .config import Config

CONFIG_PATH = '/etc/ssh/sshd_config'
TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'


def render(config: Config) -> str:
    environment = Environment(loader=FileSystemLoader(TEMPLATES),
                              trim_blocks=True, keep_trailing_newline=True)

    return environment.get_template('sshd_config.j2').render(
        config.model_dump(exclude={'suil'}))


class Ssh(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        return {CONFIG_PATH: render(self.config)}

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if scope == {}:
            return

        content = render(self.config)
        changed = self.file_needs_write(facts, CONFIG_PATH, content)

        if self.file_needs_write(facts, CONFIG_PATH, content, force):
            # sshd -t refuses to run without host keys, so a target that has never
            # started sshd would fail the check rather than the config.
            if not facts.get('host_key'):
                raise ModuleValidateError(
                    f'{self.config.suil.node} has no /etc/ssh/ssh_host_ed25519_key, so sshd -t cannot run. '
                    'Install openssh-server, or run ssh-keygen -A on the host once.')

            self.validate_file(host, content, f'{self.config.binary} -t -f %s')

            files.put(
                name='Write sshd_config',
                src=StringIO(content),
                dest=CONFIG_PATH,
                user='root',
                group='root',
                mode='600',
            )

        if self.config.manage_service and (changed or self.diff_touches(scope, 'service')):
            systemd.service(
                name=f'Ensure {self.config.service} is up',
                service=self.config.service,
                running=True,
                enabled=True,
                restarted=changed,
            )

    def check(self, facts: dict) -> list[str]:
        if self.config.manage_service and (facts.get('service') or {}).get('running') is not True:
            return [f'{self.config.service} is not running']

        return []

    def expected(self) -> dict:
        return {
            'files': {path: self.file_digest(content) for path, content in self.files().items()},
            'service': {
                'running': self.config.manage_service,
                'enabled': self.config.manage_service,
            },
        }
