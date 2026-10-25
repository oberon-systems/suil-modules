from io import StringIO

from pyinfra.operations import files, server

from suil.sdk import Module

from .config import Config

CLOUD_INIT = """# Managed by suil, module `hostname`, for {fqdn}.
# Without this, update_hostname puts the provider's flattened name back on the
# next boot.
preserve_hostname: true
"""


class Hostname(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        if not (self.config.manage and self.config.manage_cloud_init):
            return {}

        return {self.config.cloud_init_file: CLOUD_INIT.format(fqdn=self.config.fqdn)}

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if not self.config.manage or scope == {}:
            return

        if self.diff_touches(scope, 'fqdn'):
            server.hostname(
                name=f'Set the hostname to {self.config.fqdn}',
                hostname=self.config.fqdn,
            )

        # Nothing to pin when the image carries no cloud-init at all.
        if not facts.get('cloud_init'):
            return

        for path, content in self.files().items():
            if self.file_needs_write(facts, path, content, force):
                files.put(
                    name='Stop cloud-init from re-asserting the provider hostname',
                    src=StringIO(content),
                    dest=path,
                    user='root',
                    group='root',
                    mode='644',
                )

    def expected(self) -> dict:
        return {
            'fqdn': self.config.fqdn,
            'preserve_hostname': self.config.manage_cloud_init,
        }
