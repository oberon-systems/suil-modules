import pytest

from suil.sdk.libs.module import file_digest, get_order


def config(load, suil_context, **kwargs):
    return load('selinux', 'config').Config(suil=suil_context, **kwargs)


def test_the_default_is_what_the_distribution_ships(load, suil_context):
    assert config(load, suil_context).mode == 'enforcing'


def test_an_unknown_mode_is_refused(load, suil_context):
    with pytest.raises(ValueError, match='enforcing'):
        config(load, suil_context, mode='off')


def test_the_file_carries_the_mode_and_the_policy(load, suil_context):
    main = load('selinux')
    entry = config(load, suil_context, mode='permissive')
    rendered = main.config_text(entry)

    assert 'SELINUX=permissive\n' in rendered
    assert 'SELINUXTYPE=targeted\n' in rendered
    assert main.Selinux(entry).expected()['files'] == {entry.config_file: file_digest(rendered)}


def test_nothing_is_expected_or_managed_while_manage_is_off(load, suil_context):
    main = load('selinux')
    entry = config(load, suil_context, manage=False)

    assert main.Selinux(entry).expected() == {}
    assert main.Selinux(entry).files() == {}
    assert main.Selinux(entry).check({'mode': 'enforcing'}) == []


def test_the_live_mode_is_what_check_judges(load, suil_context):
    main = load('selinux')
    entry = config(load, suil_context, mode='disabled')

    # permissive is what setenforce leaves behind until the machine reboots.
    assert main.Selinux(entry).check({'mode': 'disabled'}) == []
    assert main.Selinux(entry).check({'mode': 'permissive'}) == []
    assert main.Selinux(entry).check({'mode': 'enforcing'}) == ['selinux is enforcing, not disabled']
    assert main.Selinux(config(load, suil_context, mode='enforcing')).check({'mode': 'permissive'}) == [
        'selinux is permissive, not enforcing']


def test_base_brings_selinux_before_the_packages_it_would_label(modules):
    order = get_order(['base'], modules)

    assert order.index('selinux') < order.index('packages')
