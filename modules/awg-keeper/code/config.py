import ipaddress
import re

from pydantic import ConfigDict, field_validator, model_validator

from suil.sdk import Config as Base, Secret

VERSION = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+$')
SHA256 = re.compile(r'^([0-9a-f]{64})?$')

# The same names awg-quick accepts, because they are the same interfaces.
NAME = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,14}$')

# agent/src/awg_agent/config.py: token: str = Field(min_length=TOKEN_MIN).
TOKEN_MIN = 32

LOG_LEVELS = ('CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG')

# Whoever reaches the agent can change every peer; a wildcard listener is the
# one mistake it cannot survive.
FORBIDDEN_BINDS = ('', '0.0.0.0', '::', '*')


class Config(Base):

    # pydantic prints input_value in every error, and token is the Panel's bearer token.
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)

    version: str = '0.1.1'
    release: int = 1
    sha256:  str = ''

    release_base: str = 'https://github.com/oberon-systems/awg-keeper/releases/download'
    download_dir: str = '/var/cache/awg-keeper'

    manage_service: bool = True

    package:    str = 'awg-keeper-agent'
    unit:       str = 'awg-keeper-agent.service'
    config_dir: str = '/etc/awg-keeper'
    unit_dir:   str = '/etc/systemd/system'

    unit_dropin: str | None = None

    # Everything below is one AWG_KEEPER_* line of agent.env, and nothing else
    # is: the agent refuses a variable its config.py does not know.
    token:           Secret
    bind:            str = '127.0.0.1'
    port:            int = 8081
    allowed_subnets: list[str] = []
    interfaces:      list[str] = []
    awg_bin:         str = 'awg'
    awg_conf_dir:    str = '/etc/amnezia/amneziawg'
    ip_bin:          str = 'ip'
    xray_bin:        str = 'xray'
    xray_api:        str = '127.0.0.1:8085'
    xray_config:     str = '/usr/local/etc/xray/config.json'
    command_timeout: float = 10.0
    log_level:       str = 'INFO'
    docs:            bool = False

    # From the OS layer, data/os/<family>/<release>.yaml.
    artifact: str

    @field_validator('version')
    @classmethod
    def check_version(cls, value: str) -> str:
        if not VERSION.match(value):
            raise ValueError(f'version is the agent release like 0.1.1, not {value!r}')

        return value

    @field_validator('sha256')
    @classmethod
    def check_sha256(cls, value: str) -> str:
        if not SHA256.match(value):
            raise ValueError('sha256 is empty or 64 lowercase hex digits')

        return value

    @field_validator('token')
    @classmethod
    def check_token(cls, value: str) -> str:
        # Never echo the value: it is the Panel's bearer token.
        if len(value) < TOKEN_MIN:
            raise ValueError(f'token is shorter than {TOKEN_MIN} characters, which the agent refuses')

        return value

    @field_validator('bind')
    @classmethod
    def check_bind(cls, value: str) -> str:
        if value in FORBIDDEN_BINDS:
            raise ValueError(f'bind is {value!r}; the agent binds the gateway of the Panel\'s docker '
                             'network, never a wildcard')

        return value

    @field_validator('port')
    @classmethod
    def check_port(cls, value: int) -> int:
        if not 0 < value < 65536:
            raise ValueError(f'port {value} is not a port')

        return value

    @field_validator('allowed_subnets')
    @classmethod
    def check_allowed_subnets(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError('allowed_subnets is empty, which leaves the agent on loopback and the '
                             'Panel locked out')

        for item in value:
            network = ipaddress.ip_network(item, strict=False)

            if '/' not in item or network.prefixlen == 0:
                raise ValueError(f'allowed_subnets holds {item!r}; name the Panel\'s docker subnet')

        return value

    @field_validator('interfaces')
    @classmethod
    def check_interfaces(cls, value: list[str]) -> list[str]:
        for name in value:
            if not NAME.match(name):
                raise ValueError(f'{name!r} is not an interface name: at most 15 of [a-zA-Z0-9_.-]')

        return value

    @field_validator('log_level')
    @classmethod
    def check_log_level(cls, value: str) -> str:
        if value not in LOG_LEVELS:
            raise ValueError(f'log_level is one of {", ".join(LOG_LEVELS)}, not {value!r}')

        return value

    @model_validator(mode='after')
    def check(self) -> 'Config':
        if '{version}' not in self.artifact or '{release}' not in self.artifact:
            raise ValueError('artifact has to carry {version} and {release}')

        return self

    @property
    def env_file(self) -> str:
        return f'{self.config_dir}/agent.env'

    @property
    def dropin_dir(self) -> str:
        return f'{self.unit_dir}/{self.unit}.d'

    @property
    def dropin_file(self) -> str:
        return f'{self.dropin_dir}/override.conf'

    @property
    def artifact_name(self) -> str:
        return self.artifact.format(version=self.version, release=self.release)

    @property
    def artifact_path(self) -> str:
        return f'{self.download_dir}/{self.artifact_name}'

    @property
    def url(self) -> str:
        return f'{self.release_base}/{self.package}-v{self.version}/{self.artifact_name}'

    @property
    def package_version(self) -> str:
        return f'{self.version}-{self.release}'
