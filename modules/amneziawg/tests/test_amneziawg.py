import pytest

from suil.sdk.libs.module import file_digest
from suil.testing import get_order, get_requires

# Throwaway keys generated for the ansible stand test, never used on a host.
PRIVATE = '8DqDPY3ATxKSM0d5gu/tvPN2nt6BXd0KZl2qZcD9gFc='
PUBLIC = 'PjlLJMAgomYSL96wgXAnArvSam1jNUjTGHVAGA/l8io='
PEER = '7TpoQF/wOwh/M4KDsKv9Uvnm0F+qzcVtQ0RfyEq1ECY='

OBFUSCATION = {'Jc': 3, 'Jmin': 40, 'Jmax': 70, 'S1': 30, 'S2': 90,
               'H1': 1234567, 'H2': 2345678, 'H3': 3456789, 'H4': 4567890}

# Throwaway as well: 32 zero bytes.
HEADER_KEY = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='

V31 = {'Jc': 6, 'Jmin': 50, 'Jmax': 1000, 'S1': 40, 'S2': 120, 'S3': 24, 'S4': 16,
       'H1': '100000-199999', 'H2': '200000-299999', 'H3': '300000-399999', 'H4': 400000,
       'I1': '<b 0xc0ff><r 32>', 'HeaderProtectionKey': HEADER_KEY,
       'ContentPaddingAddition': '2-10', 'KeepaliveTimeout': '20-30',
       'RandomTrailers': True, 'DisableCookies': 'off'}

PACKAGES = {'amneziawg-tools': {'ensure': '3.1.20260812-1.el10'},
            'amneziawg-go': {'ensure': '3.1.20260812-1.el10'}}


def interface(**kwargs):
    return {'address': '10.99.0.1/24', 'listen_port': 51820, 'private_key': PRIVATE,
            'peers': {'testpeer': {'public_key': PEER, 'allowed_ips': ['10.99.0.2/32']}},
            **kwargs}


def config(load, suil_context, interfaces=None, packages=None, **kwargs):
    return load('amneziawg', 'config').Config(
        suil=suil_context, packages=PACKAGES if packages is None else packages,
        interfaces={'awg-test': interface()} if interfaces is None else interfaces, **kwargs)


def test_the_public_key_is_derived_from_the_private_one(load):
    assert load('amneziawg', 'config').derive_public_key(PRIVATE) == PUBLIC


def test_a_public_key_the_private_key_does_not_match_is_refused(load, suil_context):
    config(load, suil_context, interfaces={'awg-test': interface(public_key=PUBLIC)})

    with pytest.raises(ValueError, match='belongs to'):
        config(load, suil_context, interfaces={'awg-test': interface(public_key=PEER)})


def test_a_peer_carrying_the_gateway_key_is_refused_without_a_declared_one(load, suil_context):
    # awg takes such a peer and drops it in silence.
    peers = {'testpeer': {'public_key': PUBLIC, 'allowed_ips': ['10.99.0.2/32']}}

    with pytest.raises(ValueError, match='own key'):
        config(load, suil_context, interfaces={'awg-test': interface(peers=peers)})


def test_two_peers_on_one_key_are_refused(load, suil_context):
    peers = {name: {'public_key': PEER, 'allowed_ips': [address]}
             for name, address in (('one', '10.99.0.2/32'), ('two', '10.99.0.3/32'))}

    with pytest.raises(ValueError, match='share a public_key'):
        config(load, suil_context, interfaces={'awg-test': interface(peers=peers)})


def test_a_peer_without_allowed_ips_is_refused(load, suil_context):
    peers = {'testpeer': {'public_key': PEER, 'allowed_ips': []}}

    with pytest.raises(ValueError):
        config(load, suil_context, interfaces={'awg-test': interface(peers=peers)})


@pytest.mark.parametrize('broken', [
    {'address': None},
    {'address': '10.99.0.1'},
    {'listen_port': None},
    {'private_key': ''},
    {'private_key': 'not-a-key'},
])
def test_a_present_interface_needs_an_address_a_port_and_a_key(load, suil_context, broken):
    with pytest.raises(ValueError):
        config(load, suil_context, interfaces={'awg-test': interface(**broken)})


def test_an_absent_interface_needs_nothing_else(load, suil_context):
    entry = config(load, suil_context, interfaces={'awg-test': {'ensure': 'absent'}})

    assert entry.interfaces['awg-test'].ensure == 'absent'


def test_two_interfaces_on_one_port_are_refused(load, suil_context):
    other = interface(address='10.98.0.1/24', peers={})

    with pytest.raises(ValueError, match='both listen'):
        config(load, suil_context, interfaces={'awg-test': interface(), 'awg-other': other})


def test_an_interface_name_longer_than_ifnamsiz_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, interfaces={'awg-a-very-long-name': interface()})


@pytest.mark.parametrize('broken', [
    {**OBFUSCATION, 'J1': 1},
    {**OBFUSCATION, 'Itime': 60},
    {key: value for key, value in OBFUSCATION.items() if key != 'H4'},
    {**OBFUSCATION, 'H1': 4},
    {**OBFUSCATION, 'H2': OBFUSCATION['H1']},
    {**OBFUSCATION, 'S2': OBFUSCATION['S1'] + 56},
    {**V31, 'H2': '150000-250000'},
    {**V31, 'H1': '199999-100000'},
    {**V31, 'H4': '400000-4294967296'},
    {**V31, 'ContentPaddingAddition': '2-70000'},
    {**V31, 'KeepaliveTimeout': 'soon'},
    {**V31, 'RandomTrailers': 'yes'},
    {**V31, 'S4': 11},
    {**V31, 'HeaderProtectionKey': PUBLIC[:20]},
    {**V31, 'I1': '<b 0xc0ff><c>'},
    {**V31, 'Jmin': 2000},
])
def test_an_obfuscation_profile_awg_would_not_parse_is_refused(load, suil_context, broken):
    with pytest.raises(ValueError):
        config(load, suil_context, obfuscation=broken)


def test_a_31_profile_with_ranges_is_taken(load, suil_context):
    entry = config(load, suil_context, obfuscation=V31)

    assert entry.obfuscation['RandomTrailers'] == 'on'


def test_an_interface_moves_to_its_own_profile_without_the_others(load, suil_context):
    main = load('amneziawg')
    entry = config(load, suil_context, obfuscation=OBFUSCATION, interfaces={
        'awg-test': interface(),
        'awg-new': interface(listen_port=51821, obfuscation=V31),
    })
    old, new = main.render(entry, 'awg-test'), main.render(entry, 'awg-new')

    assert 'Jc = 3' in old and 'HeaderProtectionKey' not in old
    assert 'Jc = 6' in new and 'Jc = 3' not in new
    assert f'HeaderProtectionKey = {HEADER_KEY}' in new
    assert 'H1 = 100000-199999' in new and 'RandomTrailers = on' in new


def test_an_interface_profile_is_checked_over_the_global_one(load, suil_context):
    with pytest.raises(ValueError, match='awg-test'):
        config(load, suil_context, obfuscation=OBFUSCATION,
               interfaces={'awg-test': interface(obfuscation={'H4': OBFUSCATION['H1']})})


def test_the_rendered_file_sorts_the_obfuscation_and_the_peers(load, suil_context):
    main = load('amneziawg')
    peers = {'zeta': {'public_key': PEER, 'allowed_ips': ['10.99.0.3/32'], 'keepalive': 25},
             'alpha': {'public_key': PUBLIC.replace('P', 'Q', 1), 'allowed_ips': ['10.99.0.2/32']}}
    rendered = main.render(config(load, suil_context, obfuscation=OBFUSCATION,
                                  interfaces={'awg-test': interface(mtu=1280, peers=peers)}),
                           'awg-test')

    assert 'Address = 10.99.0.1/24' in rendered
    assert f'PrivateKey = {PRIVATE}' in rendered
    assert 'MTU = 1280' in rendered
    assert rendered.index('H1 = 1234567') < rendered.index('Jc = 3') < rendered.index('S2 = 90')
    assert rendered.index('# alpha') < rendered.index('# zeta')
    assert 'PersistentKeepalive = 25' in rendered
    assert 'Endpoint' not in rendered


def test_an_interface_without_peers_renders_no_peer_section(load, suil_context):
    main = load('amneziawg')
    rendered = main.render(config(load, suil_context,
                                  interfaces={'awg-test': interface(peers={})}), 'awg-test')

    assert '[Peer]' not in rendered


def test_expected_names_the_digest_the_live_key_and_the_peers(load, suil_context):
    main = load('amneziawg')
    entry = config(load, suil_context, interfaces={'awg-test': interface(),
                                                   'awg-gone': {'ensure': 'absent'}})
    reported = main.Amneziawg(entry).expected()

    assert reported['packages'] == PACKAGES
    assert reported['ip_forward'] is True

    assert reported['interfaces']['awg-test'] == {
        'ensure':     'present',
        'public_key': PUBLIC,
        'peers':      [PEER],
        'service':    {'running': True, 'enabled': True},
    }
    assert reported['files'][entry.config_file('awg-test')] == file_digest(main.render(entry, 'awg-test'))
    assert reported['files'][entry.dropin_file('awg-test')] is None

    assert reported['interfaces']['awg-gone'] == {
        'ensure': 'absent', 'public_key': None, 'peers': None,
        'service': {'running': False, 'enabled': False},
    }
    assert reported['files'][entry.config_file('awg-gone')] is None


def test_external_peers_leave_the_peer_list_empty(load, suil_context):
    with pytest.raises(ValueError, match='peers_external'):
        config(load, suil_context, interfaces={'awg-test': interface(peers_external=True)})


def test_an_external_interface_is_judged_by_its_dropin_not_its_file(load, suil_context):
    main = load('amneziawg')
    entry = config(load, suil_context,
                   interfaces={'awg-test': interface(peers={}, peers_external=True, mtu=1280)})
    wanted = main.Amneziawg(entry).expected()
    reported = wanted['interfaces']['awg-test']

    assert entry.config_file('awg-test') not in wanted['files']
    assert reported['peers'] is None
    assert reported['public_key'] == PUBLIC
    assert wanted['files'][entry.dropin_file('awg-test')] == file_digest(main.dropin_text(entry, 'awg-test'))


def test_the_dropin_restores_the_address_and_the_mtu(load, suil_context):
    main = load('amneziawg')
    entry = config(load, suil_context,
                   interfaces={'awg-test': interface(peers={}, peers_external=True, mtu=1280),
                               'awg-bare': interface(address='10.98.0.1/24', listen_port=51821,
                                                     peers={}, peers_external=True)})
    text = main.dropin_text(entry, 'awg-test')

    assert entry.dropin_file('awg-test') == '/etc/systemd/system/awg-quick@awg-test.service.d/override.conf'
    assert 'ExecStartPost=-/usr/sbin/ip address replace 10.99.0.1/24 dev awg-test' in text
    assert 'ExecStartPost=-/usr/sbin/ip link set mtu 1280 dev awg-test' in text
    assert 'mtu' not in main.dropin_text(entry, 'awg-bare')
    assert '[Peer]' not in main.render(entry, 'awg-test')


def test_a_pin_reaches_dnf_as_a_versioned_name(load, suil_context):
    main = load('amneziawg')
    entry = config(load, suil_context, packages={**PACKAGES, 'amneziawg-dkms': {'ensure': 'absent'},
                                                 'awg-tool': {'ensure': 'present'}})

    assert main._wanted(entry, absent=False) == [
        'amneziawg-go-3.1.20260812-1.el10', 'amneziawg-tools-3.1.20260812-1.el10', 'awg-tool']
    assert main._wanted(entry, absent=True) == ['amneziawg-dkms']


def test_a_package_at_another_version_than_the_pin_is_stale(load, suil_context):
    main = load('amneziawg')
    entry = config(load, suil_context)
    pinned = {'amneziawg-tools': {'ensure': '3.1.20260812-1.el10'},
              'amneziawg-go':    {'ensure': '3.1.20260812-1.el10'}}

    assert main._stale(entry, pinned) is False
    assert main._stale(entry, {**pinned, 'amneziawg-go': {'ensure': '3.1.20260701-1.el10'}}) is True
    assert main._stale(entry, {'amneziawg-tools': {'ensure': '3.1.20260812-1.el10'}}) is True


def test_an_ensure_that_is_not_a_version_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, packages={'amneziawg-go': {'ensure': 'latest please'}})


def test_only_a_live_device_disagreeing_with_its_file_counts_as_drift(load):
    main = load('amneziawg')
    down = {('interfaces', 'awg-test', 'public_key'): {'expected': PUBLIC, 'actual': None}}
    drifted = {('interfaces', 'awg-test', 'peers'): {'expected': [PEER], 'actual': []}}

    assert main._drifted(None, 'awg-test') is False
    assert main._drifted(down, 'awg-test') is False
    assert main._drifted(drifted, 'awg-test') is True
    assert main._drifted(drifted, 'awg-other') is False


def test_amneziawg_declares_repos_rather_than_relying_on_position(modules):
    # The packages come from a repository declared through the repos module.
    assert get_requires(modules['amneziawg']) == ['repos']
    assert get_order(['amneziawg'], modules) == ['repos', 'amneziawg']
