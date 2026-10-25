import pytest


def config(load, suil_context, **kwargs):
    return load('hostname', 'config').Config(suil=suil_context, **kwargs)


def test_the_fqdn_defaults_to_the_node_key(load, suil_context):
    assert config(load, suil_context).fqdn == suil_context['node']


def test_a_single_label_name_is_refused(load, suil_context):
    # The flattened form a provider puts in instance metadata is exactly what
    # this module exists to replace, so accepting it would make it a no-op.
    with pytest.raises(ValueError):
        config(load, suil_context, fqdn='host-01-example-com')


def test_an_uppercase_name_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, fqdn='Host-01.example.com')


def test_a_label_over_63_characters_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, fqdn='a' * 64 + '.example.com')


def test_expected_reports_the_name_and_the_pin(load, suil_context):
    main = load('hostname')

    assert main.Hostname(config(load, suil_context)).expected() == {
        'fqdn': suil_context['node'], 'preserve_hostname': True}
