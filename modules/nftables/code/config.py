import re

from pydantic import BaseModel, ConfigDict, model_validator

from suil.sdk import Config as Base

# What counts as a literal address rather than a set name or a DNS name.
# Deliberately loose: nft is what finally rejects a malformed address.
ADDRESS = re.compile(r'^(([0-9]{1,3}\.){3}[0-9]{1,3}|[0-9A-Fa-f:]*:[0-9A-Fa-f:.]*)(/[0-9]{1,3})?$')
PORTS = re.compile(r'^[0-9]+([:-][0-9]+)?$')
NON_WORD = re.compile(r'[^A-Za-z0-9_]')

PROTOCOLS = ('tcp', 'udp', 'icmp', 'gre', 'vrrp')

# Losing one of these is losing the firewall, so the model refuses a config
# that dropped it - the ansible role got this from `vars`, which host data
# could not reach, and the bottom layer here can be overridden by anything.
REQUIRED_BASELINE = {
    'established':  ('input', 100),
    'loopback':     ('input', 101),
    'icmpv6':       ('input', 103),
    'input_drop':   ('input', 990),
    'forward_drop': ('forward', 991),
}


def setname(value: str) -> str:
    return NON_WORD.sub('_', value)


class Chain(BaseModel):

    model_config = ConfigDict(extra='forbid')

    type:     str
    hook:     str
    priority: int
    policy:   str | None = None


class Table(BaseModel):

    model_config = ConfigDict(extra='forbid')

    family:    str = 'inet'
    min_order: int
    max_order: int
    chains:    dict[str, Chain] = {}


class ExtraChain(BaseModel):

    model_config = ConfigDict(extra='forbid')

    name:  str
    table: str = 'filter'


class Set(BaseModel):

    model_config = ConfigDict(extra='forbid')

    elems:    list[str] = []
    table:    str = 'filter'
    set_type: str = 'ipv4_addr'
    flags:    str | None = 'interval'
    order:    int = 5


class Direct(BaseModel):

    model_config = ConfigDict(extra='forbid')

    rule_string: str | None = None
    table:       str = 'filter'
    chain:       str | None = None
    order:       int = 500


class Rule(BaseModel):

    model_config = ConfigDict(extra='forbid')

    source:  str | None = None
    proto:   str | None = None
    port:    str | int | None = None
    chain:   str = 'input'
    order:   int = 500
    comment: str | None = None


class Nat(BaseModel):

    model_config = ConfigDict(extra='forbid')

    nat_type:  str = 'SNAT'
    to:        str
    interface: str | None = None
    proto:     str | None = None
    port:      str | int | None = None
    order:     int = 500
    comment:   str | None = None
    # `from` is a python keyword, so the field is named source and aliased.
    source:    str | None = None

    model_config = ConfigDict(extra='forbid', populate_by_name=True)

    @model_validator(mode='before')
    @classmethod
    def accept_from(cls, data):
        if isinstance(data, dict) and 'from' in data:
            data = dict(data)
            data['source'] = data.pop('from')

        return data


class Config(Base):

    rules_file:     str = '/etc/nftables/suil.nft'
    apply_script:   str = '/usr/local/sbin/nftables-apply.sh'
    resolve_script: str = '/usr/local/sbin/nftables-resolve.sh'
    state_dir:      str = '/var/lib/nftables'
    unit:           str = 'nftables-suil'
    completion_dir: str = '/usr/share/bash-completion/completions'

    manage_service:      bool = True
    disable_conflicting: bool = True

    resolve_dns:      bool = True
    resolve_interval: str = '5min'

    tables:   dict[str, Table]
    baseline: dict[str, Direct] = {}
    chains:   list[ExtraChain] = []
    sets:     dict[str, Set] = {}
    direct:   dict[str, Direct] = {}
    rules:    dict[str, Rule] = {}
    nat:      dict[str, Nat] = {}

    # From the OS layer, data/os/<family>/<release>.yaml.
    service:              str
    nft_binary:           str
    conflicting_services: list[str] = []

    @model_validator(mode='after')
    def check(self) -> 'Config':
        self._check_baseline()
        self._check_tables()
        self._check_orders()
        self._check_rules()
        self._check_nat()
        self._check_dns_sources()

        return self

    def _check_baseline(self) -> None:
        for name, (chain, order) in REQUIRED_BASELINE.items():
            entry = self.baseline.get(name)

            if entry is None:
                raise ValueError(f'baseline rule {name!r} is gone; a layer above the module deleted it')

            if entry.chain != chain or entry.order != order:
                raise ValueError(
                    f'baseline rule {name!r} moved to {entry.chain}/{entry.order}, '
                    f'expected {chain}/{order}: the trailing drops must stay last')

    def _check_tables(self) -> None:
        named = ([entry.table for entry in self.sets.values()]
                 + [entry.table for entry in self.chains]
                 + [entry.table for entry in {**self.baseline, **self.direct}.values()])

        for table in named:
            if table not in self.tables:
                raise ValueError(f'{table!r} is not in tables: {", ".join(self.tables)}')

    def _check_orders(self) -> None:
        # Below 11 lands on top of the table skeleton, at the window width or
        # above it lands in the next table's window.
        for name, entry in {**self.baseline, **self.direct}.items():
            table = self.tables[entry.table]
            width = table.max_order - table.min_order

            if not 10 < entry.order < width:
                raise ValueError(
                    f'rule {name!r} has order {entry.order}; table {entry.table!r} '
                    f'allows 11 - {width - 1}')

    def _check_rules(self) -> None:
        for name, rule in self.rules.items():
            port = '' if rule.port is None else str(rule.port)

            if rule.proto and rule.proto not in PROTOCOLS:
                raise ValueError(f'rules[{name!r}].proto is one of {", ".join(PROTOCOLS)}')

            if port and rule.proto not in ('tcp', 'udp'):
                raise ValueError(f'rules[{name!r}] has a port, which needs proto tcp or udp')

            if ',' in port and any(not PORTS.match(item.strip()) for item in port.split(',')):
                raise ValueError(f'rules[{name!r}].port list may only hold numbers and ranges')

            if rule.chain not in ('input', 'forward'):
                raise ValueError(f'rules[{name!r}].chain is input or forward; use direct for anything else')

    def _check_nat(self) -> None:
        for name, entry in self.nat.items():
            port = '' if entry.port is None else str(entry.port)

            if entry.nat_type not in ('SNAT', 'DNAT'):
                raise ValueError(f'nat[{name!r}].nat_type is SNAT or DNAT')

            if entry.proto and entry.proto not in ('tcp', 'udp'):
                raise ValueError(f'nat[{name!r}].proto is tcp or udp')

            if port and entry.proto not in ('tcp', 'udp'):
                raise ValueError(f'nat[{name!r}] has a port, which needs proto tcp or udp')

            target = re.sub(r':[0-9]+$', '', entry.to)

            if target != entry.to and not entry.proto:
                raise ValueError(f'nat[{name!r}].to maps a port, so proto has to be matched as well')

            # A translation is one address. `dnat to @set` does not exist, and a
            # name behind a round robin would pick a different backend per reload.
            if not ADDRESS.match(target):
                raise ValueError(f'nat[{name!r}].to has to be a literal address, not {entry.to!r}')

    def _check_dns_sources(self) -> None:
        sources = [value for value in
                   [rule.source for rule in self.rules.values()]
                   + [entry.source for entry in self.nat.values()]
                   if value and value not in self.sets and not ADDRESS.match(value)]
        sources = list(dict.fromkeys(sources))

        if len({setname(value) for value in sources}) != len(sources):
            raise ValueError(
                'two DNS sources collapse to the same nft set name: ' + ', '.join(sources))
