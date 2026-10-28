import pytest

from suil.sdk.libs.module import file_digest
from suil.testing import get_order

TOKEN = 't' * 40

OS_LAYER = {'artifact': 'awg-keeper-agent-{version}-{release}.x86_64.rpm'}

# Every field of agent/src/awg_agent/config.py Settings at awg-keeper-agent-v0.4.0.
AGENT_FIELDS = ('token', 'bind', 'port', 'allowed_subnets', 'interfaces', 'awg_bin', 'awg_conf_dir', 'ip_bin',
                'xray_bin', 'xray_api', 'xray_config', 'command_timeout', 'log_level', 'docs')


def config(load, suil_context, **kwargs):
    values = {'token': TOKEN, 'allowed_subnets': ['172.18.0.0/16'], **OS_LAYER, **kwargs}

    return load('awg-keeper', 'config').Config(suil=suil_context, **values)


def test_a_short_token_is_refused_without_being_echoed(load, suil_context):
    with pytest.raises(ValueError, match='shorter') as error:
        config(load, suil_context, token='tooshort-secret')

    assert 'tooshort-secret' not in str(error.value)


@pytest.mark.parametrize('bind', ['0.0.0.0', '::', ''])
def test_a_wildcard_listener_is_refused(load, suil_context, bind):
    with pytest.raises(ValueError, match='wildcard'):
        config(load, suil_context, bind=bind)


@pytest.mark.parametrize('subnets', [[], ['0.0.0.0/0'], ['172.18.0.1'], ['not-a-network']])
def test_the_allowlist_is_a_list_of_real_networks(load, suil_context, subnets):
    with pytest.raises(ValueError):
        config(load, suil_context, allowed_subnets=subnets)


def test_an_interface_name_awg_quick_could_not_carry_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, interfaces=['awg-a-very-long-name'])


def test_agent_env_carries_exactly_what_the_agent_knows(load, suil_context):
    main = load('awg-keeper')
    rendered = main.render(config(load, suil_context, interfaces=['awg0'], bind='172.18.0.1'),
                           'agent.env.j2')
    lines = dict(line.split('=', 1) for line in rendered.splitlines() if line and not line.startswith('#'))

    assert set(lines) == {f'AWG_KEEPER_{field.upper()}' for field in AGENT_FIELDS}
    assert lines['AWG_KEEPER_TOKEN'] == TOKEN
    assert lines['AWG_KEEPER_ALLOWED_SUBNETS'] == '172.18.0.0/16'
    assert lines['AWG_KEEPER_INTERFACES'] == 'awg0'
    assert lines['AWG_KEEPER_DOCS'] == 'false'


def test_the_release_url_carries_the_sub_project_tag(load, suil_context):
    entry = config(load, suil_context)

    assert entry.url == ('https://github.com/oberon-systems/awg-keeper/releases/download/'
                         'awg-keeper-agent-v0.1.1/awg-keeper-agent-0.1.1-1.x86_64.rpm')
    assert entry.artifact_path == '/var/cache/awg-keeper/awg-keeper-agent-0.1.1-1.x86_64.rpm'


def test_a_package_at_another_version_is_stale(load, suil_context):
    main = load('awg-keeper')
    entry = config(load, suil_context)

    assert main._stale(entry, '0.1.1-1') is False
    assert main._stale(entry, '0.1.0-1') is True
    assert main._stale(entry, None) is True


def test_expected_names_the_package_the_files_and_the_service(load, suil_context):
    main = load('awg-keeper')
    entry = config(load, suil_context, unit_dropin='[Unit]\nAfter=docker.service\n\n')

    assert main.AwgKeeper(entry).expected() == {
        'package': '0.1.1-1',
        'files': {
            entry.env_file:    file_digest(main.render(entry, 'agent.env.j2')),
            entry.dropin_file: file_digest('[Unit]\nAfter=docker.service\n'),
        },
        'service': {'running': True, 'enabled': True},
    }
    assert main.AwgKeeper(config(load, suil_context)).expected()['files'][entry.dropin_file] is None


def test_the_agent_runs_after_the_modules_whose_paths_it_mounts(modules):
    order = get_order(['awg-keeper'], modules)

    assert order.index('amneziawg') < order.index('awg-keeper')
    assert order.index('xray') < order.index('awg-keeper')
    assert order[-1] == 'awg-keeper'


def test_the_default_xray_api_is_the_xray_modules_api_inbound(load, suil_context):
    inbound = load('xray', 'config').Config(suil=suil_context).api_inbound

    assert config(load, suil_context).xray_api == f"{inbound['listen']}:{inbound['port']}"
