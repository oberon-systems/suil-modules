import re

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suil.sdk import Config as Base, Secret

# What dnf accepts as a repoid, and what a .repo file is named after.
REPO_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]*$')

LISTEN = re.compile(r'^(?P<host>[^\s:]+|\[[0-9A-Fa-f:]+\]):(?P<port>\d{1,5})$')

KEY_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


def _bare(value):
    return {name: (spec or {}) for name, spec in (value or {}).items()}


class Key(BaseModel):
    """A gpg public key the module delivers to gpg_dir."""

    model_config = ConfigDict(extra='forbid')

    ensure:  str = 'present'
    src:     str | None = None
    content: str | None = None

    @model_validator(mode='after')
    def one_source(self) -> 'Key':
        if self.ensure == 'absent':
            return self

        if bool(self.src) == bool(self.content):
            raise ValueError('a key takes exactly one of src (a file in modules/repos/files/) '
                             'or content')

        return self


class File(BaseModel):
    """A ready-made .repo file, delivered verbatim."""

    model_config = ConfigDict(extra='forbid')

    src:     str | None = None
    url:     str | None = None
    content: str | None = None

    @model_validator(mode='after')
    def one_source(self) -> 'File':
        if len([value for value in (self.src, self.url, self.content) if value]) != 1:
            raise ValueError('file takes exactly one of src, url or content')

        return self


class Repo(BaseModel):

    model_config = ConfigDict(extra='forbid')

    ensure:      str = 'present'
    description: str = ''

    baseurl:    list[str] = []
    mirrorlist: str | None = None
    metalink:   str | None = None
    file:       File | None = None
    store:      str | None = None
    path:       str = ''

    enabled:             bool = True
    gpgcheck:            bool = True
    repo_gpgcheck:       bool | None = None
    gpgkey:              list[str] = []
    priority:            int | None = None
    module_hotfixes:     bool | None = None
    exclude:             list[str] = []
    includepkgs:         list[str] = []
    skip_if_unavailable: bool | None = None
    sslverify:           bool | None = None
    cost:                int | None = None
    username:            str | None = None
    password:            Secret | None = None

    # Anything dnf.conf(5) knows and this model does not, written as it stands.
    options: dict[str, str | int | bool] = {}

    @field_validator('ensure')
    @classmethod
    def check_ensure(cls, value: str) -> str:
        if value not in ('present', 'absent'):
            raise ValueError(f'ensure is present or absent, not {value!r}')

        return value

    @field_validator('baseurl', 'gpgkey', 'exclude', 'includepkgs', mode='before')
    @classmethod
    def one_entry_is_a_list(cls, value):
        return [value] if isinstance(value, str) else value

    @model_validator(mode='after')
    def one_source(self) -> 'Repo':
        if self.ensure == 'absent':
            return self

        sources = [name for name, value in (('baseurl', self.baseurl), ('mirrorlist', self.mirrorlist),
                                            ('metalink', self.metalink), ('file', self.file),
                                            ('store', self.store)) if value]

        if len(sources) != 1:
            raise ValueError('a repository takes exactly one of baseurl, mirrorlist, metalink, '
                             f'file or store, got {", ".join(sources) or "none"}')

        if self.path and not self.store:
            raise ValueError('path is where a repository sits inside a store, and there is no store')

        if self.gpgcheck and not self.gpgkey and not self.file:
            raise ValueError('gpgcheck is on with no gpgkey, which fails the first install on an '
                             'unknown key; give a gpgkey or say gpgcheck: false')

        return self


class Store(BaseModel):
    """An S3-compatible bucket, served read-only on a loopback port."""

    model_config = ConfigDict(extra='forbid')

    ensure:   str = 'present'
    provider: str = 'Cloudflare'

    endpoint: str = ''
    bucket:   str = ''
    region:   str = 'auto'

    access_key_id:     Secret = ''
    secret_access_key: Secret = ''

    listen: str = '127.0.0.1:8083'
    unit:   str | None = None

    extra_args: list[str] = []

    @field_validator('ensure')
    @classmethod
    def check_ensure(cls, value: str) -> str:
        if value not in ('present', 'absent'):
            raise ValueError(f'ensure is present or absent, not {value!r}')

        return value

    @model_validator(mode='after')
    def complete(self) -> 'Store':
        if self.ensure == 'absent':
            return self

        missing = [name for name in ('endpoint', 'bucket', 'access_key_id', 'secret_access_key')
                   if not getattr(self, name)]

        if missing:
            raise ValueError(f'a store needs {", ".join(missing)}')

        if not LISTEN.match(self.listen):
            raise ValueError(f'listen is <host>:<port>, not {self.listen!r}')

        return self

    @property
    def address(self) -> str:
        return LISTEN.match(self.listen).group('host')

    @property
    def port(self) -> str:
        return LISTEN.match(self.listen).group('port')


class Config(Base):

    manage:     bool = True
    purge:      bool = False
    purge_keep: list[str] = []

    keys:   dict[str, Key | None] = {}
    list:   dict[str, Repo | None] = {}
    stores: dict[str, Store | None] = {}

    # Site data, needed only once a store is declared.
    store_user:       str | None = None
    unit_format:      str | None = None
    store_config_dir: str = '/etc/rclone'

    # From the OS layer, data/os/<family>/<release>.yaml.
    repos_dir:      str
    gpg_dir:        str
    rclone_package: str
    rclone_binary:  str

    @field_validator('keys', 'list', 'stores', mode='before')
    @classmethod
    def allow_bare_names(cls, value):
        return _bare(value)

    @model_validator(mode='after')
    def check(self) -> 'Config':
        for name in self.keys:
            if not KEY_NAME.match(name):
                raise ValueError(f'{name!r} is not a usable file name for a gpg key')

        ports = {}

        if self.unit_format and '{store}' not in self.unit_format:
            raise ValueError(f'unit_format {self.unit_format!r} has no {{store}} placeholder')

        for name, store in self.stores.items():
            if not (store.unit or self.unit_format):
                raise ValueError(f'store {name} needs unit_format or its own unit')

            if store.ensure != 'present':
                continue

            if not self.store_user:
                raise ValueError(f'store {name} needs store_user, the account its front runs as')

            if store.listen in ports:
                raise ValueError(f'stores {ports[store.listen]} and {name} both listen on {store.listen}')

            ports[store.listen] = name

        for name, repo in self.list.items():
            if not REPO_ID.match(name):
                raise ValueError(f'{name!r} is not a repoid dnf accepts')

            if repo.store and repo.store not in self.stores:
                raise ValueError(f'repository {name} reads store {repo.store!r}, which is not declared')

            self._check_keys(name, repo)

        return self

    def _check_keys(self, name: str, repo: Repo) -> None:
        prefix = f'file://{self.gpg_dir}/'

        for key in repo.gpgkey:
            if not key.startswith(prefix):
                continue

            # A gpgkey pointing at a file nothing delivers is a dnf failure at
            # install time; it is data, so it is caught here instead.
            if key[len(prefix):] not in self.keys:
                raise ValueError(
                    f'repository {name} points gpgkey at {key}, which no keys: entry writes - '
                    f'declare repos.keys.{key[len(prefix):]} with src: a file in '
                    'modules/repos/files/, or point gpgkey at a URL')

    def unit(self, name: str) -> str:
        store = self.stores[name]

        return store.unit or self.unit_format.format(store=name)
