import posixpath
import re
import shlex

from typing import Any

import yaml

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suil.sdk import Config as Base, Secret

VERSION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+:~-]*$')
NAME = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
OPTION = re.compile(r'^[a-z][a-z0-9-]*$')
ENV_KEY = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
MODE = re.compile(r'^[0-7]{3,4}$')

# An entry name becomes a system account, and these are already somebody's.
RESERVED = ('root', 'docker', 'nobody')

# The unit or a key of the entry already passes these, and a second copy either
# fails `docker run` or silently wins over the one the module meant.
OWNED = ('name', 'rm', 'user', 'u', 'env', 'e', 'env-file', 'publish', 'p',
         'volume', 'v', 'restart', 'detach', 'd')

EnvValue = Secret | str | int | float | bool


def check_ensure(value: str, versions: bool = False) -> str:
    if value in ('present', 'absent') or (versions and VERSION.match(value)):
        return value

    wanted = 'present, absent or a version' if versions else 'present or absent'
    raise ValueError(f'ensure is {wanted}, not {value!r}')


def check_env(value: dict) -> dict:
    for key, item in value.items():
        if not ENV_KEY.match(key):
            raise ValueError(f'env key {key!r} is not a variable name')

        if '\n' in str(item):
            raise ValueError(f'env {key} holds a newline, which an env file cannot carry')

    return value


def spec(package: str, ensure: str) -> str:
    return package if ensure in ('present', 'absent') else f'{package}-{ensure}'


class Container(BaseModel):

    model_config = ConfigDict(extra='forbid')

    ensure:       str = 'present'
    image:        str | None = None
    user:         str | None = None
    env:          dict[str, EnvValue] = {}
    ports:        list[str] = []
    mounts:       list[str] = []
    opts:         dict[str, EnvValue | list[str | int] | None] = {}
    run_opts:     list[str] = []
    pull:         bool = True
    recreate:     bool = True
    stop_timeout: int = 30
    unit_dropin:  str | None = None

    @field_validator('ensure')
    @classmethod
    def check_ensure(cls, value: str) -> str:
        return check_ensure(value)

    @field_validator('env')
    @classmethod
    def check_env(cls, value: dict) -> dict:
        return check_env(value)

    @field_validator('run_opts', mode='before')
    @classmethod
    def split_run_opts(cls, value):
        return shlex.split(value) if isinstance(value, str) else value

    @field_validator('opts')
    @classmethod
    def check_opts(cls, value: dict) -> dict:
        for key in value:
            if not OPTION.match(key):
                raise ValueError(f'opts key {key!r} is not a docker run option name')

            if key in OWNED:
                raise ValueError(f'opts cannot set {key}: the unit or a key of the entry already passes it')

        return value

    @model_validator(mode='after')
    def check_image(self) -> 'Container':
        if self.ensure == 'absent':
            return self

        if not self.image or re.search(r'\s', self.image):
            raise ValueError('a present container needs an image, one word')

        if self.user and re.search(r'\s', self.user):
            raise ValueError(f'user is name, uid or uid:gid, not {self.user!r}')

        return self


class Directory(BaseModel):

    model_config = ConfigDict(extra='forbid')

    owner: str | int | None = None
    group: str | int | None = None
    mode:  str = '750'

    @field_validator('mode', mode='before')
    @classmethod
    def check_mode(cls, value) -> str:
        # yaml reads an unquoted 750 as an int; its digits are still the octal mode.
        mode = str(value).lstrip('0').rjust(3, '0')

        if not MODE.match(mode):
            raise ValueError(f'mode is an octal mode such as 750, not {value!r}')

        return mode


class Stack(BaseModel):

    model_config = ConfigDict(extra='forbid')

    ensure:      str = 'present'
    env:         dict[str, EnvValue] = {}
    recreate:    bool = False
    content:     str | None = None
    unit_dropin: str | None = None
    directories: dict[str, Directory] = {}

    @field_validator('ensure')
    @classmethod
    def check_ensure(cls, value: str) -> str:
        return check_ensure(value)

    @field_validator('env')
    @classmethod
    def check_env(cls, value: dict) -> dict:
        return check_env(value)

    @field_validator('directories')
    @classmethod
    def check_directories(cls, value: dict) -> dict:
        for path in value:
            if posixpath.normpath(path) in ('.', '/') or '..' in path.split('/'):
                raise ValueError(f'directories holds {path!r}; name a directory below the stack or an absolute one')

        return value

    @model_validator(mode='after')
    def check_content(self) -> 'Stack':
        if self.ensure == 'absent':
            return self

        try:
            document = yaml.safe_load(self.content or '')
        except yaml.YAMLError as error:
            raise ValueError(f'content is not yaml: {error}') from error

        if not isinstance(document, dict) or not document.get('services'):
            raise ValueError('content is a compose document, a mapping with services')

        return self


class Compose(BaseModel):

    model_config = ConfigDict(extra='forbid')

    ensure: str = 'present'
    stacks: dict[str, Stack] = {}

    @field_validator('ensure')
    @classmethod
    def check_ensure(cls, value: str) -> str:
        return check_ensure(value, versions=True)


class Config(Base):

    ensure:         str = 'present'
    manage_service: bool = True
    restart:        bool = False
    purge:          bool = True

    config:     dict[str, Any] = {}
    containers: dict[str, Container] = {}
    compose:    Compose = Compose()

    # files/*.service carry these as literals; moving one breaks the pair.
    unit_dir: str = '/etc/systemd/system'
    dir:      str = '/opt'

    # From the OS layer, data/os/<family>/<release>.yaml.
    package:           str
    cli_package:       str
    compose_package:   str
    extra_packages:    list[str]
    modules_extra:     str
    service:           str
    dockerd_binary:    str
    config_file:       str
    sysctl_file:       str
    modules_load_file: str

    @field_validator('ensure')
    @classmethod
    def check_ensure(cls, value: str) -> str:
        return check_ensure(value, versions=True)

    @model_validator(mode='after')
    def check_names(self) -> 'Config':
        for kind, names in (('container', self.containers), ('stack', self.compose.stacks)):
            for name in names:
                if not NAME.match(name) or name in RESERVED:
                    raise ValueError(f'{name!r} is not a usable {kind} name: it becomes a unit '
                                     f'instance, a system account and {self.dir}/{name}')

        if shared := sorted(set(self.containers) & set(self.compose.stacks)):
            raise ValueError(f'{", ".join(shared)} is both a container and a stack, and both would own '
                             f'the same account and directory')

        stacks = [name for name, stack in self.compose.stacks.items() if stack.ensure == 'present']

        if self.compose.ensure == 'absent' and stacks:
            raise ValueError(f'compose is absent but stacks {", ".join(sorted(stacks))} are present')

        return self

    @property
    def packages(self) -> list[str]:
        names = [spec(self.package, self.ensure), spec(self.cli_package, self.ensure), *self.extra_packages]

        if self.compose.ensure != 'absent':
            names.append(spec(self.compose_package, self.compose.ensure))

        return names

    @staticmethod
    def container_unit(name: str) -> str:
        return f'docker-container@{name}.service'

    @staticmethod
    def stack_unit(name: str) -> str:
        return f'docker-compose@{name}.service'

    def entry_dir(self, name: str) -> str:
        return f'{self.dir}/{name}'

    def env_file(self, name: str) -> str:
        return f'{self.entry_dir(name)}/.env'

    def compose_file(self, name: str) -> str:
        return f'{self.entry_dir(name)}/docker-compose.yml'

    def stack_directory(self, name: str, path: str) -> str:
        """A relative path is the stack's own, beside its compose file, as ./<path> is in it."""
        return posixpath.normpath(posixpath.join(self.entry_dir(name), path))

    def dropin_file(self, unit: str) -> str:
        return f'{self.unit_dir}/{unit}.d/override.conf'

    def run_file(self, unit: str) -> str:
        return f'{self.unit_dir}/{unit}.d/run.conf'
