"""Reports which repository files and object store fronts are there, and whether
the fronts listen, in the shape of the module's config.

The digests of the keys, the repository files, the store credentials and the
units are recorded by the runner from files()."""

import fnmatch
import os
import socket
import subprocess

from suil.sdk import Facter


def systemctl(verb, service):
    result = subprocess.run(['systemctl', verb, service],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    return result.stdout.decode().strip() in ('active', 'enabled', 'enabled-runtime')


def listening(listen):
    host, _, port = listen.rpartition(':')

    try:
        with socket.create_connection((host.strip('[]') or '127.0.0.1', int(port)), timeout=2):
            return True
    except (OSError, ValueError):
        return False


def unit_name(name, store, unit_format):
    return store.get('unit') or unit_format.format(store=name)


def present(path):
    return 'present' if os.path.isfile(path) else 'absent'


def unmanaged(config, repos_dir):
    if not config.get('purge'):
        return None

    declared = {'{}.repo'.format(name) for name in (config.get('list') or {})}
    keep = config.get('purge_keep') or []
    found = []

    for name in sorted(os.listdir(repos_dir)):
        if not name.endswith('.repo') or name in declared:
            continue

        if not any(fnmatch.fnmatch(name, pattern) for pattern in keep):
            found.append(name)

    return found


class ReposFacter(Facter):

    def collect(self) -> dict:
        repos_dir = self.config.get('repos_dir') or '/etc/yum.repos.d'
        store_dir = self.config.get('store_config_dir') or '/etc/rclone'

        repos = {name: {'ensure': present(os.path.join(repos_dir, '{}.repo'.format(name)))}
                 for name in (self.config.get('list') or {})}

        stores = {}

        for name, spec in (self.config.get('stores') or {}).items():
            spec = spec or {}
            unit = unit_name(name, spec, self.config.get('unit_format'))

            stores[name] = {
                'ensure':    present(os.path.join(store_dir, '{}.conf'.format(name))),
                'listening': listening(spec.get('listen') or '127.0.0.1:8083'),
                'service': {
                    'running': systemctl('is-active', unit),
                    'enabled': systemctl('is-enabled', unit),
                },
            }

        return {'list': repos, 'stores': stores, 'unmanaged': unmanaged(self.config, repos_dir)}
