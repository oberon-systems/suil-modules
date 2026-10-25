"""Builds the nft ruleset text.

The ansible role assembled this in jinja, with `regex_replace` and `combine`
doing the work; plain jinja2 has neither, and the logic was never really
template logic. Here it is python, and `suil/tests` can assert on it.
"""

from .config import ADDRESS, PORTS, Config, setname

HEADER = ('# Managed by suil, module `nftables`, for {node}.\n'
          '# Local edits are lost on the next run.')


def addr_match(config: Config, keyword: str, value: str) -> str:
    if value in config.sets:
        return f'{keyword} @{value}'

    if ADDRESS.match(value):
        return f'{keyword} {value}'

    # Neither a literal nor a declared set: a DNS name, which becomes a set of
    # its own that nftables-resolve.sh fills on the host.
    return f'{keyword} @{setname(value)}'


def ports(proto: str, port) -> str:
    elems = [item.strip() for item in str(port).split(',')]
    norm = [item.replace(':', '-') for item in elems if PORTS.match(item)]

    if len(norm) != len(elems):
        return f'{proto} dport @{port}'

    if len(norm) == 1:
        return f'{proto} dport {norm[0]}'

    return f'{proto} dport {{ {", ".join(norm)} }}'


def allow_rule(config: Config, name: str, rule) -> str:
    parts = []

    if rule.source:
        parts.append(addr_match(config, 'ip saddr', rule.source))

    if rule.proto:
        port = '' if rule.port is None else str(rule.port)

        if rule.proto in ('tcp', 'udp') and port:
            parts.append(ports(rule.proto, rule.port))
        else:
            parts.append(f'ip protocol {rule.proto}')

    # `counter` is not implicit the way it is in iptables, and the comment has
    # to come last, after the verdict.
    parts.append(f'counter accept comment "{rule.comment or name}"')

    return ' '.join(parts)


def nat_rule(config: Config, name: str, entry) -> str:
    kind = entry.nat_type
    # In an inet table the address family of the translation is not implied by
    # the rule, it has to be spelled out: `snat ip to ...`.
    family = ' ip' if config.tables['nat'].family == 'inet' else ''
    keyword = 'ip saddr' if kind == 'SNAT' else 'ip daddr'
    interface = 'oif' if kind == 'SNAT' else 'iif'
    parts = []

    if entry.source:
        parts.append(addr_match(config, keyword, entry.source))

    if entry.interface:
        parts.append(f'{interface} "{entry.interface}"')

    if entry.proto:
        port = '' if entry.port is None else str(entry.port)
        parts.append(f'{entry.proto} dport {port}' if port else f'meta l4proto {entry.proto}')

    parts.append(f'counter {kind.lower()}{family} to {entry.to}')
    parts.append(f'comment "{entry.comment or name}"')

    return ' '.join(parts)


def _rules(config: Config) -> list[dict]:
    rules = []

    for source in ({**config.baseline, **config.direct},):
        for name, entry in source.items():
            rules.append({'table': entry.table, 'chain': entry.chain, 'order': entry.order,
                          'text': entry.rule_string or name})

    for name, rule in config.rules.items():
        rules.append({'table': 'filter', 'chain': rule.chain, 'order': rule.order,
                      'text': allow_rule(config, name, rule)})

    for name, entry in config.nat.items():
        chain = 'postrouting' if entry.nat_type == 'SNAT' else 'prerouting'
        rules.append({'table': 'nat', 'chain': chain, 'order': entry.order,
                      'text': nat_rule(config, name, entry)})

    return rules


def _autosets(config: Config) -> list[tuple[str, str]]:
    found = []

    for rule in config.rules.values():
        if rule.source and rule.source not in config.sets and not ADDRESS.match(rule.source):
            found.append(('filter', rule.source))

    for entry in config.nat.values():
        if entry.source and entry.source not in config.sets and not ADDRESS.match(entry.source):
            found.append(('nat', entry.source))

    return list(dict.fromkeys(found))


def _skeleton(config: Config, used: set) -> list[dict]:
    fragments = []

    for name, table in config.tables.items():
        if name not in used:
            continue

        lines = [f'add table {table.family} {name}',
                 f'delete table {table.family} {name}',
                 f'table {table.family} {name} {{']

        for chain_name, chain in table.chains.items():
            policy = f' policy {chain.policy};' if chain.policy else ''
            lines.append(f'  chain {chain_name} {{')
            lines.append(f'    type {chain.type} hook {chain.hook} '
                         f'priority {chain.priority};{policy}')
            lines.append('  }')

        lines.append('}')
        fragments.append({'order': table.min_order, 'text': '\n'.join(lines)})

    return fragments


def build(config: Config) -> str:
    rules = _rules(config)
    autosets = _autosets(config)

    # Only the tables something actually uses are declared, so an unused nat or
    # mangle table does not register hooks on every host.
    used = ({rule['table'] for rule in rules}
            | {entry.table for entry in config.sets.values()}
            | {entry.table for entry in config.chains}
            | {table for table, _ in autosets})

    fragments = _skeleton(config, used)

    for entry in config.chains:
        table = config.tables[entry.table]
        fragments.append({'order': table.min_order + 2,
                          'text': f'add chain {table.family} {entry.table} {entry.name}'})

    for name, entry in config.sets.items():
        table = config.tables[entry.table]
        flags = f' flags {entry.flags};' if entry.flags else ''
        fragments.append({
            'order': table.min_order + entry.order,
            'text': (f'add set {table.family} {entry.table} {name} '
                     f'{{ type {entry.set_type};{flags} '
                     f'elements = {{ {", ".join(entry.elems)} }} }}')})

    # Rendered empty on purpose: nftables-resolve.sh fills it on the host, and
    # reads the DNS name back out of the comment. Do not change this line.
    for table_name, source in autosets:
        table = config.tables[table_name]
        fragments.append({
            'order': table.min_order + 5,
            'text': (f'add set {table.family} {table_name} {setname(source)} '
                     f'{{ type ipv4_addr; comment "{source}"; }}')})

    for rule in rules:
        table = config.tables[rule['table']]
        text = (f'add rule {table.family} {rule["table"]} {rule["chain"]} {rule["text"]}'
                if rule['chain'] else rule['text'])
        fragments.append({'order': table.min_order + rule['order'], 'text': text})

    body = '\n'.join(item['text'] for item in sorted(fragments, key=lambda item: item['order']))

    return HEADER.format(node=config.suil.node) + '\n' + body + '\n'
