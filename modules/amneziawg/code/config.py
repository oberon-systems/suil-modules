import base64
import binascii
import re

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suil.sdk import Config as Base, Secret

KEY = re.compile(r'^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$')

# A version-release as rpm reports it, the same shape the packages module takes.
VERSION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+:~-]*$')

# An interface name reaches a systemd instance name and IFNAMSIZ at once.
NAME = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,14}$')

# What src/config.c accepts. J1-J3 and Itime are not among them, whatever the
# blog posts say.
OBFUSCATION_KEYS = ('Jc', 'Jmin', 'Jmax', 'S1', 'S2', 'S3', 'S4', 'H1', 'H2', 'H3', 'H4',
                    'I1', 'I2', 'I3', 'I4', 'I5', 'HeaderProtectionKey', 'ContentPaddingAddition',
                    'RekeyAfterTime', 'RekeyTimeout', 'RejectAfterTime', 'KeepaliveTimeout',
                    'MaxHandshakeAttempts', 'RandomTrailers', 'DisableCookies')

HEADER_KEYS = ('H1', 'H2', 'H3', 'H4')

# uint16 values awg 3.1 also takes as an a-b range.
RANGE_KEYS = ('ContentPaddingAddition', 'RekeyAfterTime', 'RekeyTimeout', 'RejectAfterTime',
              'KeepaliveTimeout', 'MaxHandshakeAttempts')

SWITCH_KEYS = ('RandomTrailers', 'DisableCookies')

INT_KEYS = ('Jc', 'Jmin', 'Jmax', 'S1', 'S2', 'S3', 'S4')

PADDING_KEYS = ('S1', 'S2', 'S3', 'S4')

CPS_KEYS = ('I1', 'I2', 'I3', 'I4', 'I5')

RANGE = re.compile(r'^(\d+)(?:-(\d+))?$')


def derive_public_key(private_key: str) -> str:
    raw = X25519PrivateKey.from_private_bytes(base64.b64decode(private_key)).public_key()

    return base64.b64encode(raw.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def _key(value: str, what: str) -> str:
    if not KEY.match(value or ''):
        raise ValueError(f'{what} is not a base64 curve25519 key')

    try:
        base64.b64decode(value, validate=True)
    except binascii.Error as error:
        raise ValueError(f'{what} is not a base64 curve25519 key') from error

    return value


def _span(value: int | str, what: str, top: int) -> tuple[int, int]:
    match = RANGE.match(str(value)) if not isinstance(value, bool) else None

    if not match:
        raise ValueError(f'{what} is a number or an a-b range, not {value!r}')

    low, high = int(match[1]), int(match[2] or match[1])

    if low > high or high > top:
        raise ValueError(f'{what} {value!r} is not a range within 0-{top}')

    return low, high


def check_obfuscation(values: dict, where: str) -> None:
    """What awg 3.1 refuses to parse, or parses into a tunnel that never handshakes."""
    if unknown := sorted(set(values) - set(OBFUSCATION_KEYS)):
        raise ValueError(f'{where} does not take {", ".join(unknown)}; '
                         f'awg knows {", ".join(OBFUSCATION_KEYS)}')

    for key in INT_KEYS:
        if key in values and (isinstance(values[key], bool) or not isinstance(values[key], int)
                              or not 0 <= values[key] <= 65535):
            raise ValueError(f'{where}: {key} is an integer within 0-65535')

    for key in RANGE_KEYS:
        if key in values:
            _span(values[key], f'{where}: {key}', 65535)

    for key in SWITCH_KEYS:
        if key in values and values[key] not in ('on', 'off'):
            raise ValueError(f'{where}: {key} is on or off')

    if values.get('Jmin', 0) > values.get('Jmax', 65535):
        raise ValueError(f'{where}: Jmin is above Jmax')

    # An init and a response of one size are the plain WireGuard pair again.
    if 'S1' in values and values['S1'] + 56 == values.get('S2'):
        raise ValueError(f'{where}: S1 + 56 equals S2')

    headers = [values[key] for key in HEADER_KEYS if key in values]

    if len(headers) not in (0, 4):
        raise ValueError(f'{where}: H1-H4 are given all four or not at all')

    spans = sorted(_span(value, f'{where}: H1-H4', 4294967295) for value in headers)

    if any(low < 5 for low, _ in spans):
        raise ValueError(f'{where}: H1-H4 are greater than 4')

    if any(left[1] >= right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError(f'{where}: H1-H4 have to be four distinct, non-overlapping values')

    if 'HeaderProtectionKey' in values:
        try:
            raw = base64.b64decode(str(values['HeaderProtectionKey']), validate=True)
        except binascii.Error:
            raw = b''

        if len(raw) != 32:
            raise ValueError(f'{where}: HeaderProtectionKey is a base64 32-byte key')

        if any(values.get(key, 0) < 12 for key in PADDING_KEYS):
            raise ValueError(f'{where}: HeaderProtectionKey needs S1-S4 of 12 and more')

    # amneziawg-go has no <c> tag and refuses the whole configuration over it.
    if any('<c>' in str(values[key]) for key in CPS_KEYS if key in values):
        raise ValueError(f'{where}: I1-I5 cannot carry a <c> tag')


def _switches(value: dict) -> dict:
    # YAML reads a bare on/off as a bool.
    return {key: (('on' if item else 'off') if isinstance(item, bool) and key in SWITCH_KEYS else item)
            for key, item in (value or {}).items()}


class Package(BaseModel):

    model_config = ConfigDict(extra='forbid')

    ensure: str = 'present'

    @field_validator('ensure')
    @classmethod
    def check_ensure(cls, value: str) -> str:
        if value not in ('present', 'absent') and not VERSION.match(value):
            raise ValueError(f'ensure is present, absent or a version-release, not {value!r}')

        return value


class Peer(BaseModel):

    model_config = ConfigDict(extra='forbid')

    public_key:    str
    allowed_ips:   list[str]
    endpoint:      str | None = None
    keepalive:     int | None = None
    preshared_key: Secret | None = None

    @field_validator('public_key')
    @classmethod
    def check_public_key(cls, value: str) -> str:
        return _key(value, 'public_key')

    @field_validator('preshared_key')
    @classmethod
    def check_preshared_key(cls, value: str | None) -> str | None:
        return value if value is None else _key(value, 'preshared_key')

    @field_validator('allowed_ips')
    @classmethod
    def check_allowed_ips(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError('allowed_ips is empty, which routes nothing to the peer')

        return value


class Interface(BaseModel):

    model_config = ConfigDict(extra='forbid')

    ensure:  str = 'present'
    enabled: bool = True

    address:     str | None = None
    listen_port: int | None = None
    mtu:         int | None = None
    fwmark:      int | None = None

    private_key: Secret = ''
    # When given, the public half the gateway is known by - checked against
    # the private key, so a wrong key fails here rather than on the tunnel.
    public_key: str | None = None

    peers: dict[str, Peer] = {}

    # The awg-keeper agent owns the peer list: the file is written once and
    # the address comes back through a unit drop-in, see README.md.
    peers_external: bool = False

    # Merged over the module-wide set, so one interface moves without the rest.
    obfuscation: dict[str, bool | int | str] = {}

    @field_validator('obfuscation', mode='before')
    @classmethod
    def check_switches(cls, value: dict) -> dict:
        return _switches(value)

    @field_validator('ensure')
    @classmethod
    def check_ensure(cls, value: str) -> str:
        if value not in ('present', 'absent'):
            raise ValueError(f'ensure is present or absent, not {value!r}')

        return value

    @model_validator(mode='after')
    def check(self) -> 'Interface':
        if self.ensure == 'absent':
            return self

        if not self.address or '/' not in self.address:
            raise ValueError('a present interface needs an address carrying a prefix length')

        if not self.listen_port or not 0 < self.listen_port < 65536:
            raise ValueError('a present interface needs a listen_port')

        _key(self.private_key, 'private_key')

        if self.peers_external and self.peers:
            raise ValueError('peers_external hands the peers to the agent, so peers has to stay empty')

        derived = self.derived_public_key

        if self.public_key is not None and self.public_key != derived:
            raise ValueError(f'public_key says {self.public_key} but private_key belongs to {derived}; '
                             'every profile naming this gateway would fail its handshake')

        keys = [peer.public_key for peer in self.peers.values()]

        if len(keys) != len(set(keys)):
            raise ValueError('two peers share a public_key')

        # awg takes a peer carrying the device's own key and drops it in silence.
        if derived in keys:
            raise ValueError(f'a peer carries the interface\'s own key {derived}; '
                             'a peer key is the person\'s, never the gateway\'s')

        return self

    @property
    def derived_public_key(self) -> str:
        return derive_public_key(self.private_key)


class Config(Base):

    manage_service:    bool = True
    manage_ip_forward: bool = True
    install_packages:  bool = True

    # awg-quick@.service from amneziawg-tools carries /usr/bin/awg-quick as a
    # literal and reads <config_dir>/<iface>.conf; moving either breaks the pair.
    config_dir:  str = '/etc/amnezia/amneziawg'
    awg_binary:  str = '/usr/bin/awg'
    unit_prefix: str = 'awg-quick'
    sysctl_file: str = '/etc/sysctl.d/90-amneziawg.conf'
    unit_dir:    str = '/etc/systemd/system'
    ip_binary:   str = '/usr/sbin/ip'

    obfuscation: dict[str, bool | int | str] = {}
    interfaces:  dict[str, Interface | None] = {}

    # From the OS layer, data/os/<family>/<release>.yaml: the names are an OS
    # fact, and so is the dist tag in the version they are pinned to.
    packages: dict[str, Package]

    @field_validator('interfaces', 'packages', mode='before')
    @classmethod
    def allow_bare_names(cls, value):
        return {name: (spec or {}) for name, spec in (value or {}).items()}

    @field_validator('obfuscation', mode='before')
    @classmethod
    def check_switches(cls, value: dict) -> dict:
        return _switches(value)

    @model_validator(mode='after')
    def check(self) -> 'Config':
        ports = {}

        for name, interface in self.interfaces.items():
            if not NAME.match(name):
                raise ValueError(f'{name!r} is not an interface name: at most 15 of [a-zA-Z0-9_.-]')

            if interface.ensure != 'present':
                continue

            if interface.listen_port in ports:
                raise ValueError(f'interfaces {ports[interface.listen_port]} and {name} both '
                                 f'listen on {interface.listen_port}')

            ports[interface.listen_port] = name

        check_obfuscation(self.obfuscation, 'obfuscation')

        for name, interface in self.interfaces.items():
            if interface.ensure == 'present':
                check_obfuscation(self.effective_obfuscation(name), f'obfuscation of {name}')

        return self

    def effective_obfuscation(self, name: str) -> dict:
        return {**self.obfuscation, **self.interfaces[name].obfuscation}

    def config_file(self, name: str) -> str:
        return f'{self.config_dir}/{name}.conf'

    def unit(self, name: str) -> str:
        return f'{self.unit_prefix}@{name}.service'

    def dropin_dir(self, name: str) -> str:
        return f'{self.unit_dir}/{self.unit(name)}.d'

    def dropin_file(self, name: str) -> str:
        return f'{self.dropin_dir(name)}/override.conf'
