from io import StringIO

from pyinfra.operations import files, server

from suil.sdk import Module

from .config import Config

CONFIG = """# Managed by suil, module `selinux`, for {node}. Local edits are lost.
SELINUX={mode}
SELINUXTYPE={policy}
"""


def config_text(config: Config) -> str:
    return CONFIG.format(node=config.suil.node, mode=config.mode, policy=config.policy)


def _mode(config: Config, facts: dict) -> None:
    """The file decides the next boot; this decides now.

    A command because pyinfra has no operation for the live mode, and a kernel
    left enforcing until a reboot keeps denying what the new mode would allow.
    """
    live = facts.get('mode')
    wanted = 'enforcing' if config.mode == 'enforcing' else 'permissive'

    if live in (wanted, 'disabled') or live is None:
        return

    server.shell(name=f'Set selinux {wanted} until the next boot',
                 commands=[f'setenforce {1 if wanted == "enforcing" else 0}'])


class Selinux(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        return {self.config.config_file: config_text(self.config)} if self.config.manage else {}

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if not self.config.manage or scope == {}:
            return

        content = config_text(self.config)

        if self.file_needs_write(facts, self.config.config_file, content, force):
            files.put(
                name='Write the selinux configuration',
                src=StringIO(content),
                dest=self.config.config_file,
                user='root',
                group='root',
                mode='644',
            )

        _mode(self.config, facts)

    def check(self, facts: dict) -> list[str]:
        """Only a kernel still deciding is a problem: a disabled policy reads as
        permissive until the machine reboots, and that is the run's own doing."""
        live = facts.get('mode')

        if not self.config.manage or live == self.config.mode:
            return []

        if self.config.mode != 'enforcing' and live == 'permissive':
            return []

        return [f'selinux is {live}, not {self.config.mode}']

    def expected(self) -> dict:
        if not self.config.manage:
            return {}

        return {'files': {path: self.file_digest(content) for path, content in self.files().items()}}
