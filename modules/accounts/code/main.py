import hashlib

from io import StringIO

from pyinfra import host, logger
from pyinfra.operations import files, server

from suil.sdk import Module

from .config import Account, Config


class Accounts(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        found = {}

        for name, account in self.config.users.items():
            account = account or Account()

            if account.ensure == 'absent':
                if name != self.config.suil.ssh_user:
                    found[_sudoers_file(name)] = None
            elif self.config.manage_sudo and account.sudo is not None:
                found[_sudoers_file(name)] = _sudoers(name, account)

        return found

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if scope == {}:
            return

        existing = set(facts.get('groups') or [])
        wanted = self.files()

        for name, account in sorted(self.config.users.items()):
            account = account or Account()
            path = _sudoers_file(name)

            if account.ensure != 'absent':
                if self.diff_touches(scope, 'users', name):
                    _ensure(name, account, self.config, existing)

                if path in wanted and self.file_needs_write(facts, path, wanted[path], force):
                    self._sudo(name, wanted[path])
            elif name == self.config.suil.ssh_user:
                # userdel refuses an account holding a session, and this one holds
                # ours. Connect as another account and the next run removes it.
                logger.warning(f'{self.config.suil.node}: leaving {name}, the run is connected as it')
            else:
                if self.diff_touches(scope, 'users', name):
                    server.user(name=f'Remove the account {name}', user=name, present=False)

                if self.file_needs_write(facts, path, None, force):
                    files.file(name=f'Remove the sudoers drop-in of {name}', path=path, present=False)

    def expected(self) -> dict:
        users = {}

        for name, account in self.config.users.items():
            account = account or Account()

            if account.ensure == 'absent':
                if name != self.config.suil.ssh_user:
                    users[name] = {'ensure': 'absent'}

                continue

            users[name] = {
                'ensure':   'present',
                'shell':    account.shell,
                'auth_key': _digest(account.auth_key.strip() if account.auth_key else None),
            }

        return {
            'users': users,
            'files': {path: self.file_digest(content) for path, content in self.files().items()},
        }

    def _sudo(self, name: str, content: str | None) -> None:
        path = _sudoers_file(name)

        if content is None:
            files.file(name=f'Remove the sudoers drop-in of {name}', path=path, present=False)
            return

        self.validate_file(host, content, f'{self.config.visudo} -cf %s')

        files.put(
            name=f'Ensure the sudoers drop-in of {name}',
            src=StringIO(content),
            dest=path,
            user='root',
            group='root',
            mode='440',
        )


def _ensure(name: str, account: Account, config: Config, existing: set) -> None:
    # A group the distribution does not have is skipped, not an error: wheel
    # exists on EL, sudo on Debian, and one site list has to work on both.
    groups = [group for group in account.groups if group in existing]

    # Plain userdel on removal: no -r and no -f, so an account still holding a
    # session survives it. See README.md, "What removal does not do".
    server.user(
        name=f'Ensure the account {name}',
        user=name,
        present=True,
        shell=account.shell,
        groups=groups,
        append=config.groups_append if account.append is None else account.append,
        system=account.system,
        password=account.password,
        public_keys=[account.auth_key] if account.auth_key else None,
        delete_keys=(config.keys_exclusive if account.keys_exclusive is None
                     else account.keys_exclusive),
    )


def _sudoers_file(name: str) -> str:
    return f'/etc/sudoers.d/{name}'


def _sudoers(name: str, account: Account) -> str | None:
    return account.sudo.strip() + '\n' if account.sudo else None


def _digest(value: str | None) -> str | None:
    return 'sha256:' + hashlib.sha256(value.encode()).hexdigest() if value else None
