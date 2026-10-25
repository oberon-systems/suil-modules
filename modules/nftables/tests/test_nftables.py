from pathlib import Path

import pytest

from suil.sdk.libs.module import get_defaults
from suil.sdk.models import Root

MODULES_DIR = Path(__file__).resolve().parents[2]

OS_LAYER = {'service': 'nftables', 'nft_binary': '/usr/sbin/nft',
            'conflicting_services': ['firewalld']}


def defaults():
    return get_defaults(Root(name='nftables', path=MODULES_DIR / 'nftables'))['nftables']


def config(load, suil_context, **kwargs):
    return load('nftables', 'config').Config(suil=suil_context, **{**defaults(), **OS_LAYER, **kwargs})


def test_the_baseline_survives_the_defaults(load, suil_context):
    entry = config(load, suil_context)

    assert entry.baseline['input_drop'].order == 990
    assert entry.baseline['forward_drop'].chain == 'forward'


def test_losing_a_baseline_rule_fails_on_the_control_machine(load, suil_context):
    baseline = {name: rule for name, rule in defaults()['baseline'].items()
                if name != 'input_drop'}

    with pytest.raises(ValueError, match='input_drop'):
        config(load, suil_context, baseline=baseline)


def test_moving_a_trailing_drop_fails(load, suil_context):
    baseline = dict(defaults()['baseline'])
    baseline['forward_drop'] = {**baseline['forward_drop'], 'order': 120}

    with pytest.raises(ValueError, match='forward_drop'):
        config(load, suil_context, baseline=baseline)


def test_an_order_outside_the_table_window_is_refused(load, suil_context):
    with pytest.raises(ValueError, match='order'):
        config(load, suil_context, direct={'x': {'rule_string': 'counter drop',
                                                 'chain': 'input', 'order': 5}})


def test_a_rule_naming_a_table_that_does_not_exist_is_refused(load, suil_context):
    with pytest.raises(ValueError, match='nosuchtable'):
        config(load, suil_context, direct={'x': {'rule_string': 'counter drop',
                                                 'table': 'nosuchtable'}})


def test_a_port_without_tcp_or_udp_is_refused(load, suil_context):
    with pytest.raises(ValueError, match='port'):
        config(load, suil_context, rules={'x': {'proto': 'icmp', 'port': 22}})


def test_a_nat_target_has_to_be_a_literal_address(load, suil_context):
    with pytest.raises(ValueError, match='literal address'):
        config(load, suil_context, nat={'x': {'nat_type': 'SNAT', 'to': 'example.com'}})


def test_two_dns_sources_that_collapse_to_one_set_name_are_refused(load, suil_context):
    with pytest.raises(ValueError, match='collapse'):
        config(load, suil_context, rules={
            'a': {'source': 'a.example.com', 'proto': 'tcp', 'port': 22},
            'b': {'source': 'a-example-com', 'proto': 'tcp', 'port': 22},
        })


def test_the_trailing_drops_come_last(load, suil_context):
    ruleset = load('nftables', 'ruleset').build(config(load, suil_context))
    lines = ruleset.splitlines()
    drops = [n for n, line in enumerate(lines) if line.endswith('counter drop')]
    accepts = [n for n, line in enumerate(lines) if 'counter accept' in line]

    assert drops and accepts
    assert min(drops) > max(accepts)


def test_an_unused_table_is_never_declared(load, suil_context):
    ruleset = load('nftables', 'ruleset').build(config(load, suil_context))

    assert 'table inet filter' in ruleset
    assert 'table inet nat' not in ruleset
    assert 'table inet mangle' not in ruleset


def test_a_set_source_renders_as_a_set_reference(load, suil_context):
    entry = config(load, suil_context,
                   sets={'vpn': {'elems': ['10.8.0.0/22']}},
                   rules={'ssh': {'source': 'vpn', 'proto': 'tcp', 'port': 22, 'order': 130}})
    ruleset = load('nftables', 'ruleset').build(entry)

    assert 'ip saddr @vpn tcp dport 22 counter accept' in ruleset


def test_a_dns_source_becomes_an_empty_set_carrying_the_name_as_its_comment(load, suil_context):
    entry = config(load, suil_context, rules={
        'ssh': {'source': 'host-01.example.com', 'proto': 'tcp', 'port': 22, 'order': 130}})
    ruleset = load('nftables', 'ruleset').build(entry)

    # nftables-resolve.sh reads the name back out of this comment, so the line
    # is a wire format rather than a formatting choice.
    assert ('add set inet filter host_01_example_com '
            '{ type ipv4_addr; comment "host-01.example.com"; }') in ruleset
    assert 'ip saddr @host_01_example_com' in ruleset


def test_a_port_list_is_braced_and_a_range_is_hyphenated(load, suil_context):
    ruleset = load('nftables', 'ruleset')
    entry = config(load, suil_context)

    assert ruleset.ports('tcp', '80,443') == 'tcp dport { 80, 443 }'
    assert ruleset.ports('tcp', '8000:8010') == 'tcp dport 8000-8010'
    assert entry.tables['filter'].family == 'inet'


def test_snat_spells_out_the_address_family_in_an_inet_table(load, suil_context):
    entry = config(load, suil_context, nat={
        'out': {'nat_type': 'SNAT', 'from': '10.0.0.0/24', 'to': '192.0.2.1', 'order': 100}})
    ruleset = load('nftables', 'ruleset').build(entry)

    assert 'counter snat ip to 192.0.2.1' in ruleset
    assert 'table inet nat' in ruleset


def test_the_default_units_are_named_after_suil(load, suil_context):
    main = load('nftables')
    entry = config(load, suil_context)

    assert main.unit_names(entry) == ['nftables-suil.service', 'nftables-suil-resolve.service',
                                      'nftables-suil-resolve.timer']
    assert ('ExecStart=/usr/local/sbin/nftables-apply.sh /etc/nftables/suil.nft'
            in main.unit_text(entry, 'nftables-suil.service'))


def test_a_renamed_unit_renders_from_the_same_templates(load, suil_context):
    main = load('nftables')
    entry = config(load, suil_context, unit='nftables-alpha', rules_file='/etc/nftables/alpha.nft')
    resolve = main.unit_text(entry, 'nftables-alpha-resolve.service')

    assert main.unit_names(entry) == ['nftables-alpha.service', 'nftables-alpha-resolve.service',
                                      'nftables-alpha-resolve.timer']
    assert 'Requires=nftables-alpha.service' in resolve
    assert 'ExecStart=/usr/local/sbin/nftables-resolve.sh /etc/nftables/alpha.nft' in resolve
    assert 'RandomizedDelaySec=30' in main.unit_text(entry, 'nftables-alpha-resolve.timer')
