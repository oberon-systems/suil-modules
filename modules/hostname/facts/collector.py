"""Reports the host's own name and whether cloud-init has been pinned."""

import os
import socket

from suil.sdk import Facter


class HostnameFacter(Facter):

    def collect(self) -> dict:
        cloud_init = self.config.get('cloud_init_file') or '/etc/cloud/cloud.cfg.d/99-hostname.cfg'

        # A host with no cloud-init has nothing to pin, and reports as pinned: the
        # alternative is a diff that can never be closed.
        present = os.path.isdir(os.path.dirname(cloud_init))
        preserved = not present

        try:
            with open(cloud_init) as stream:
                preserved = 'preserve_hostname: true' in stream.read()
        except OSError:
            pass

        return {'fqdn': socket.getfqdn(), 'preserve_hostname': preserved, 'cloud_init': present}
