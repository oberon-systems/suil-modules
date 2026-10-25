import re

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suil.sdk import Config as Base

# What `local-zone` accepts. A type unbound does not know is a start failure,
# and the file is written before anything gets to say so.
ZONE_TYPES = ('deny', 'refuse', 'static', 'transparent', 'typetransparent',
              'redirect', 'inform', 'inform_deny', 'inform_redirect', 'nodefault',
              'always_transparent', 'always_refuse', 'always_nxdomain', 'noview', 'block_a')

ACCESS_ACTIONS = ('allow', 'deny', 'refuse', 'allow_snoop', 'deny_non_local', 'refuse_non_local')

ACCESS_CONTROL = re.compile(r'^(\S+)\s+(\w+)$')


class Zone(BaseModel):

    model_config = ConfigDict(extra='forbid')

    name: str
    type: str = 'transparent'
    data: list[str] = []

    @field_validator('type')
    @classmethod
    def check_type(cls, value: str) -> str:
        if value not in ZONE_TYPES:
            raise ValueError(f'local-zone type is one of {", ".join(ZONE_TYPES)}, not {value!r}')

        return value


class Forward(BaseModel):

    model_config = ConfigDict(extra='forbid')

    name: str
    forward_addr: list[str] = []


class Config(Base):

    manage_service:   bool = True
    install_packages: bool = True

    config_file: str = '/etc/unbound/unbound.conf'
    verbosity:   int = 1

    listen_addresses: list[str] = []
    access_control:   list[str] = []

    ip_freebind: bool = True
    chroot:      str = ''

    msg_cache_size:   str = '2m'
    rrset_cache_size: str = '4m'

    forward_zones: list[Forward] = []
    local_zones:   list[Zone] = []

    # Not read by this host's own template: it is what the OTHER nodes read
    # through a !LOOKUP when they assemble a zone out of the inventory.
    host_address: str | list[str] = ''

    manage_resolv_conf: bool = False
    resolv_conf:        str = '/etc/resolv.conf'
    resolv_nameservers: list[str] = []
    resolv_options:     list[str] = []

    # From the OS layer, data/os/<family>/<release>.yaml.
    package:          str
    service:          str
    checkconf_binary: str
    config_group:     str
    nm_dropin:        str

    @field_validator('access_control')
    @classmethod
    def check_access_control(cls, value: list[str]) -> list[str]:
        for entry in value:
            match = ACCESS_CONTROL.match(entry.strip())

            if not match or match.group(2) not in ACCESS_ACTIONS:
                raise ValueError(
                    f'access_control entry {entry!r} is not "<netblock> <action>" with an '
                    f'action out of {", ".join(ACCESS_ACTIONS)}')

        return value

    @model_validator(mode='after')
    def check(self) -> 'Config':
        names = [zone.name for zone in self.local_zones]

        # Two local-zone statements on one apex is a start failure, and the
        # layers that build this list cannot see each other.
        if len(names) != len(set(names)):
            raise ValueError('two local_zones share a name: ' + ', '.join(sorted(names)))

        if self.manage_resolv_conf and not self.resolv_nameservers:
            raise ValueError(
                f'{self.suil.node}: manage_resolv_conf is on with no resolv_nameservers, '
                'which writes a resolv.conf that resolves nothing.')

        return self
