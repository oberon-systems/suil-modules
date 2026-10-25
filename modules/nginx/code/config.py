import re

from pydantic import field_validator, model_validator

from suil.sdk import Config as Base

VERSION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+:~-]*$')
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
DIRECTIVE = re.compile(r'^[a-z][a-z0-9_]*$')

# nginx.conf.j2 renders these whatever the data says, and a second copy of
# any of them in the same context is a start failure.
FIXED = ('user', 'worker_processes', 'error_log', 'pid', 'include', 'default_type',
         'server_tokens', 'log_format', 'access_log', 'ssl_protocols', 'ssl_ecdh_curve',
         'ssl_prefer_server_ciphers', 'ssl_stapling', 'ssl_stapling_verify',
         'ssl_trusted_certificate', 'resolver')

KEY_LENGTHS = (2048, 3072, 4096)


class Config(Base):

    ensure:         str = 'present'
    manage_service: bool = True
    purge:          bool = True

    worker_connections: int = 1024
    ssl_key_length:     int = 2048

    set_default: bool = True

    resolver: str = '127.0.0.1'

    settings: dict[str, str | int | list[str | int]] = {}
    servers:  dict[str, str | None] = {}

    # From the OS layer, data/os/<family>/<release>.yaml. files/default.conf
    # carries cert_dir and log_dir as literals; moving either breaks the pair.
    package:    str
    service:    str
    binary:     str
    user:       str
    config_dir: str
    confd_dir:  str
    cert_dir:   str
    log_dir:    str
    pid_file:   str
    ca_bundle:  str

    @field_validator('ensure')
    @classmethod
    def check_ensure(cls, value: str) -> str:
        if value not in ('present', 'absent') and not VERSION.match(value):
            raise ValueError(f'ensure is present, absent or a version, not {value!r}')

        return value

    @field_validator('ssl_key_length')
    @classmethod
    def check_key_length(cls, value: int) -> int:
        if value not in KEY_LENGTHS:
            raise ValueError(f'ssl_key_length is one of {", ".join(map(str, KEY_LENGTHS))}, not {value}')

        return value

    @field_validator('resolver')
    @classmethod
    def check_resolver(cls, value: str) -> str:
        if not value.strip() or any(char in value for char in ';{}\n'):
            raise ValueError(f'resolver is the arguments of one nginx resolver directive, not {value!r}')

        return value

    @field_validator('settings')
    @classmethod
    def check_settings(cls, value: dict) -> dict:
        for key in value:
            if not DIRECTIVE.match(key):
                raise ValueError(f'settings key {key!r} is not an nginx directive name')

            if key in FIXED:
                raise ValueError(f'settings cannot set {key}: nginx.conf already renders it')

        return value

    @model_validator(mode='after')
    def check_servers(self) -> 'Config':
        for name, content in self.servers.items():
            if not NAME.match(name) or name == 'default':
                raise ValueError(f'{name!r} is not a usable server file name '
                                 '(default.conf is the module\'s own)')

            if content and content.count('{') != content.count('}'):
                raise ValueError(f'server {name} has unbalanced braces')

        return self

    @property
    def main_file(self) -> str:
        return f'{self.config_dir}/nginx.conf'

    @property
    def default_file(self) -> str:
        return f'{self.confd_dir}/default.conf'

    @property
    def key_file(self) -> str:
        return f'{self.cert_dir}/default.key'

    @property
    def cert_file(self) -> str:
        return f'{self.cert_dir}/default.crt'

    @property
    def package_spec(self) -> str:
        return self.package if self.ensure in ('present', 'absent') else f'{self.package}-{self.ensure}'

    def server_file(self, name: str) -> str:
        return f'{self.confd_dir}/{name}.conf'
