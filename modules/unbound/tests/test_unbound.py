import pytest

from suil.sdk.libs.module import file_digest

OS_LAYER = {
    'package':          'unbound',
    'service':          'unbound',
    'checkconf_binary': '/usr/sbin/unbound-checkconf',
    'config_group':     'unbound',
    'nm_dropin':        '/etc/NetworkManager/conf.d/90-dns-none.conf',
}


def config(load, suil_context, **kwargs):
    return load('unbound', 'config').Config(suil=suil_context, **OS_LAYER, **kwargs)


def test_an_unknown_local_zone_type_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, local_zones=[{'name': 'example.com', 'type': 'passthrough'}])


def test_an_access_control_entry_without_an_action_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, access_control=['10.0.0.0/8'])

    with pytest.raises(ValueError):
        config(load, suil_context, access_control=['10.0.0.0/8 maybe'])


def test_two_local_zones_on_one_name_are_refused(load, suil_context):
    # unbound refuses to start on a duplicate apex, and the layers that build
    # this list cannot see each other.
    with pytest.raises(ValueError):
        config(load, suil_context, local_zones=[{'name': 'example.com'}, {'name': 'example.com'}])


def test_owning_resolv_conf_without_a_nameserver_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, manage_resolv_conf=True, resolv_nameservers=[])


def test_the_rendered_configuration_carries_the_zones_and_the_forwarder(load, suil_context):
    main = load('unbound')
    rendered = main.render(config(
        load, suil_context,
        listen_addresses=['127.0.0.1'],
        access_control=['127.0.0.0/8 allow'],
        local_zones=[{'name': 'example.com', 'type': 'transparent',
                      'data': ['host.example.com. A 10.0.0.1']}],
        forward_zones=[{'name': '.', 'forward_addr': ['8.8.8.8']}],
    ), 'unbound.conf.j2')

    assert 'interface: 127.0.0.1' in rendered
    assert 'access-control: 127.0.0.0/8 allow' in rendered
    assert 'local-zone: "example.com" transparent' in rendered
    assert 'local-data: "host.example.com. A 10.0.0.1"' in rendered
    assert 'forward-addr: 8.8.8.8' in rendered


def test_expected_names_the_digest_the_check_and_the_service(load, suil_context):
    main = load('unbound')
    entry = config(load, suil_context)
    reported = main.Unbound(entry).expected()

    assert reported['files'] == {entry.config_file: file_digest(main.render(entry, 'unbound.conf.j2'))}
    # The module cannot validate before the package it installs exists, so the
    # collector is what checks the live file - and expected() demands a pass.
    assert reported['checked'] is True
    assert reported['service'] == {'running': True, 'enabled': True}
