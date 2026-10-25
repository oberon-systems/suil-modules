from io import StringIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pyinfra.operations import dnf, files, server, systemd

from suil.sdk import Module

from .config import Config, Repo, Store

ROOT = Path(__file__).resolve().parent.parent
UNIT_DIR = '/etc/systemd/system'


def _environment() -> Environment:
    return Environment(loader=FileSystemLoader(ROOT / 'templates'),
                       trim_blocks=True, keep_trailing_newline=True)


def render_repo(config: Config, name: str, repo: Repo) -> str:
    return _environment().get_template('repo.j2').render(id=name, pairs=repo_pairs(config, name, repo))


def render_store(config: Config, name: str, store: Store) -> str:
    return _environment().get_template('rclone.conf.j2').render(
        name=name, store=store.model_dump())


def render_unit(config: Config, name: str, store: Store) -> str:
    arguments = ''.join(f' {argument}' for argument in store.extra_args)

    return _environment().get_template('repo-store.service.j2').render(
        name=name, store=store.model_dump(), unit=config.unit(name),
        user=config.store_user, binary=config.rclone_binary,
        config_file=store_config_file(config, name), listen=store.listen,
        bucket=store.bucket, arguments=arguments)


def store_config_file(config: Config, name: str) -> str:
    return f'{config.store_config_dir}/{name}.conf'


def store_unit_file(config: Config, name: str) -> str:
    return f'{UNIT_DIR}/{config.unit(name)}.service'


def repo_file(config: Config, name: str) -> str:
    return f'{config.repos_dir}/{name}.repo'


def key_file(config: Config, name: str) -> str:
    return f'{config.gpg_dir}/{name}'


def repo_pairs(config: Config, name: str, repo: Repo) -> list[tuple[str, str]]:
    """What the .repo file says, in the order it says it."""
    pairs: list[tuple[str, str]] = [('name', repo.description or name)]

    if repo.store:
        pairs.append(('baseurl', store_baseurl(config, repo)))
    elif repo.baseurl:
        pairs.append(('baseurl', ' '.join(repo.baseurl)))
    elif repo.metalink:
        pairs.append(('metalink', repo.metalink))
    elif repo.mirrorlist:
        pairs.append(('mirrorlist', repo.mirrorlist))

    pairs.append(('enabled', _flag(repo.enabled)))
    pairs.append(('gpgcheck', _flag(repo.gpgcheck)))

    if repo.gpgkey:
        pairs.append(('gpgkey', ' '.join(repo.gpgkey)))

    # A store-backed repository is unreachable while its unit is down, and dnf
    # aborts a transaction over one repository it cannot read.
    skip = repo.skip_if_unavailable

    if skip is None:
        skip = True if repo.store else None

    for key, value in (('repo_gpgcheck', repo.repo_gpgcheck), ('priority', repo.priority),
                       ('module_hotfixes', repo.module_hotfixes), ('cost', repo.cost),
                       ('sslverify', repo.sslverify), ('skip_if_unavailable', skip),
                       ('username', repo.username), ('password', repo.password)):
        if value is not None:
            pairs.append((key, _value(value)))

    for key, value in (('exclude', repo.exclude), ('includepkgs', repo.includepkgs)):
        if value:
            pairs.append((key, ' '.join(value)))

    pairs += [(key, _value(value)) for key, value in sorted(repo.options.items())]

    return [(key, value) for key, value in pairs if value is not None]


def store_baseurl(config: Config, repo: Repo) -> str:
    store = config.stores[repo.store]
    path = repo.path.strip('/')

    return f'http://{store.listen}/{path}/' if path else f'http://{store.listen}/'


class Repos(Module[Config]):

    def files(self) -> dict[str, str | bytes | None]:
        """A repository file fetched from a url is left out: nothing here knows its content."""
        if not self.config.manage:
            return {}

        found = {key_file(self.config, name): (_key_content(self.config, name) if key.ensure == 'present' else None)
                 for name, key in self.config.keys.items()}

        for name, repo in self.config.list.items():
            if repo.ensure == 'absent':
                found[repo_file(self.config, name)] = None
            elif not (repo.file and repo.file.url):
                found[repo_file(self.config, name)] = _repo_content(self.config, name, repo)

        for name, store in self.config.stores.items():
            present = store.ensure == 'present'
            found[store_config_file(self.config, name)] = render_store(self.config, name, store) if present else None
            found[store_unit_file(self.config, name)] = render_unit(self.config, name, store) if present else None

        return found

    def deploy(self, facts: dict, force: bool) -> None:
        scope = None if force else self.diff_configs(self.expected(), facts)

        if not self.config.manage or scope == {}:
            return

        self._keys(facts, force)
        self._repos(facts, force, backed=False)
        self._stores(facts, force)
        self._repos(facts, force, backed=True)

        if self.config.purge:
            _purge(self.config, facts.get('unmanaged') or [])

    def check(self, facts: dict) -> list[str]:
        if not self.config.manage:
            return []

        reported = facts.get('stores') or {}
        problems = []

        for name, store in sorted(self.config.stores.items()):
            current = reported.get(name) or {}

            if store.ensure != 'present':
                continue

            if (current.get('service') or {}).get('running') is not True:
                problems.append(f'{self.config.unit(name)}.service is not running')

            if current.get('listening') is not True:
                problems.append(f'the {name} store front is not listening on {store.listen}')

        return problems

    def expected(self) -> dict:
        stores = {}

        for name, store in self.config.stores.items():
            present = store.ensure == 'present'
            stores[name] = {
                'listening': present,
                'service':   {'running': present, 'enabled': present},
            }

        return {
            'files':     {path: self.file_digest(content) for path, content in self.files().items()},
            'list':      {name: {'ensure': repo.ensure} for name, repo in self.config.list.items()},
            'stores':    stores,
            'unmanaged': [] if self.config.purge else None,
        }

    def _keys(self, facts: dict, force: bool) -> None:
        writes = {name: (_key_content(self.config, name) if key.ensure == 'present' else None)
                  for name, key in sorted(self.config.keys.items())}
        writes = {name: content for name, content in writes.items()
                  if self.file_needs_write(facts, key_file(self.config, name), content, force)}

        if any(content is not None for content in writes.values()):
            files.directory(
                name=f'Ensure {self.config.gpg_dir} exists',
                path=self.config.gpg_dir,
                user='root',
                group='root',
                mode='755',
            )

        for name, content in writes.items():
            if content is None:
                files.file(name=f'Remove the gpg key {name}', path=key_file(self.config, name), present=False)
                continue

            files.put(
                name=f'Install the gpg key {name}',
                src=StringIO(content),
                dest=key_file(self.config, name),
                user='root',
                group='root',
                mode='644',
            )

    def _repos(self, facts: dict, force: bool, backed: bool) -> None:
        reported = facts.get('list') or {}

        for name, repo in sorted(self.config.list.items()):
            if bool(repo.store) != backed:
                continue

            path = repo_file(self.config, name)

            if repo.ensure == 'absent':
                if self.file_needs_write(facts, path, None, force):
                    files.file(name=f'Remove the repository {name}', path=path, present=False)
                continue

            if repo.file and repo.file.url:
                # Downloaded once, because that is all files.download promises.
                if force or (reported.get(name) or {}).get('ensure') != 'present':
                    files.download(
                        name=f'Fetch the repository file of {name}',
                        src=repo.file.url,
                        dest=path,
                        user='root',
                        group='root',
                        mode='644',
                    )
                continue

            content = _repo_content(self.config, name, repo)

            if self.file_needs_write(facts, path, content, force):
                files.put(
                    name=f'Write the repository {name}',
                    src=StringIO(content),
                    dest=path,
                    user='root',
                    group='root',
                    mode='644',
                )

    def _stores(self, facts: dict, force: bool) -> None:
        reported = facts.get('stores') or {}
        wanted = {name: store for name, store in sorted(self.config.stores.items()) if store.ensure == 'present'}

        for name, store in sorted(self.config.stores.items()):
            if store.ensure == 'absent' and (force or (reported.get(name) or {}).get('ensure') == 'present'):
                _remove_store(self.config, name)

        if not wanted:
            return

        if force or any((reported.get(name) or {}).get('ensure') != 'present' for name in wanted):
            dnf.packages(
                name=f'Install {self.config.rclone_package}',
                packages=[self.config.rclone_package],
                present=True,
            )

            server.user(
                name=f'Ensure the account {self.config.store_user}',
                user=self.config.store_user,
                system=True,
                shell='/sbin/nologin',
                home=f'/var/lib/{self.config.store_user}',
                ensure_home=False,
                create_home=False,
            )

            files.directory(
                name=f'Ensure {self.config.store_config_dir} exists',
                path=self.config.store_config_dir,
                user='root',
                group=self.config.store_user,
                mode='750',
            )

        changed = False

        for name, store in wanted.items():
            changed |= self._store(name, store, facts, force)

        if changed:
            systemd.daemon_reload(name='Reload systemd')

        for name, store in wanted.items():
            current = reported.get(name) or {}
            up = (current.get('service') or {}).get('running') is True and current.get('listening') is True

            if force or changed or not up:
                systemd.service(
                    name=f'Ensure the {name} store front is up',
                    service=f'{self.config.unit(name)}.service',
                    running=True,
                    enabled=True,
                    restarted=changed,
                )

    def _store(self, name: str, store: Store, facts: dict, force: bool) -> bool:
        content = render_store(self.config, name, store)
        unit = render_unit(self.config, name, store)
        path = store_config_file(self.config, name)
        unit_path = store_unit_file(self.config, name)

        changed = self.file_needs_write(facts, path, content) or self.file_needs_write(facts, unit_path, unit)

        if self.file_needs_write(facts, path, content, force):
            files.put(
                name=f'Write the credentials of the {name} store',
                src=StringIO(content),
                dest=path,
                user='root',
                group=self.config.store_user,
                mode='640',
            )

        if self.file_needs_write(facts, unit_path, unit, force):
            files.put(
                name=f'Install {self.config.unit(name)}.service',
                src=StringIO(unit),
                dest=unit_path,
                user='root',
                group='root',
                mode='644',
            )

        return changed


def _key_content(config: Config, name: str) -> str:
    key = config.keys[name]

    if key.content:
        return key.content if key.content.endswith('\n') else key.content + '\n'

    return (ROOT / 'files' / key.src).read_text()


def _repo_content(config: Config, name: str, repo: Repo) -> str:
    if repo.file:
        return repo.file.content if repo.file.content else (ROOT / 'files' / repo.file.src).read_text()

    return render_repo(config, name, repo)


def _remove_store(config: Config, name: str) -> None:
    systemd.service(
        name=f'Stop the {name} store front',
        service=f'{config.unit(name)}.service',
        running=False,
        enabled=False,
    )

    files.file(name=f'Remove {config.unit(name)}.service', path=store_unit_file(config, name), present=False)
    files.file(name=f'Remove the credentials of the {name} store',
               path=store_config_file(config, name), present=False)

    systemd.daemon_reload(name='Reload systemd')


def _purge(config: Config, unmanaged: list) -> None:
    for name in unmanaged:
        files.file(name=f'Remove the undeclared repository file {name}',
                   path=f'{config.repos_dir}/{name}', present=False)


def _flag(value: bool) -> str:
    return '1' if value else '0'


def _value(value) -> str:
    return _flag(value) if isinstance(value, bool) else str(value)
