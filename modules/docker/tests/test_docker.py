import importlib.util
import os
import re
import shlex

from pathlib import Path

import pytest

from suil.sdk.libs.merge import deep, deep_unwrap
from suil.sdk.libs.module import file_digest, get_defaults
from suil.sdk.models import Root

MODULES_DIR = Path(__file__).resolve().parents[2]

OS_LAYER = {
    'package':           'docker-ce',
    'cli_package':       'docker-ce-cli',
    'compose_package':   'docker-compose-plugin',
    'extra_packages':    ['containerd.io', 'docker-buildx-plugin', 'iptables-nft'],
    'modules_extra':     'kernel-modules-extra',
    'service':           'docker',
    'dockerd_binary':    '/usr/bin/dockerd',
    'config_file':       '/etc/docker/daemon.json',
    'sysctl_file':       '/etc/sysctl.d/90-docker.conf',
    'modules_load_file': '/etc/modules-load.d/br_netfilter.conf',
}

STACK = 'services:\n  web:\n    image: nginx:1\n'


def defaults():
    return get_defaults(Root(name='docker', path=MODULES_DIR / 'docker'))


def config(load, suil_context, **kwargs):
    return load('docker', 'config').Config(suil=suil_context, **{**defaults()['docker'], **OS_LAYER, **kwargs})


def test_a_name_has_to_be_a_unit_instance_an_account_and_a_directory(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, containers={'../evil': {'image': 'nginx:1'}})

    with pytest.raises(ValueError):
        config(load, suil_context, compose={'stacks': {'my app': {'content': STACK}}})

    with pytest.raises(ValueError):
        config(load, suil_context, compose={'stacks': {'docker': {'content': STACK}}})


def test_a_container_and_a_stack_cannot_share_a_name(load, suil_context):
    with pytest.raises(ValueError, match='both a container and a stack'):
        config(load, suil_context, containers={'web': {'image': 'nginx:1'}},
               compose={'stacks': {'web': {'content': STACK}}})


def test_opts_cannot_repeat_what_the_unit_passes(load, suil_context):
    for key in ('rm', 'publish', 'restart', 'name'):
        with pytest.raises(ValueError):
            config(load, suil_context, containers={'web': {'image': 'nginx:1', 'opts': {key: True}}})

    with pytest.raises(ValueError):
        config(load, suil_context, containers={'web': {'image': 'nginx:1', 'opts': {'Memory': '1g'}}})


def test_an_entry_is_checked_before_it_reaches_a_host(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, containers={'web': {'env': {'A': 'b'}}})

    with pytest.raises(ValueError):
        config(load, suil_context, containers={'web': {'image': 'nginx:1', 'env': {'A': 'one\ntwo'}}})

    with pytest.raises(ValueError):
        config(load, suil_context, compose={'stacks': {'app': {'content': 'just text'}}})

    with pytest.raises(ValueError):
        config(load, suil_context, compose={'ensure': 'absent', 'stacks': {'app': {'content': STACK}}})

    assert config(load, suil_context, containers={'old': {'ensure': 'absent'}})


def test_the_pins_become_dnf_arguments(load, suil_context):
    entry = config(load, suil_context, ensure='29.1.3', compose={'ensure': '5.5.1'})

    assert entry.packages == ['docker-ce-29.1.3', 'docker-ce-cli-29.1.3', 'containerd.io',
                              'docker-buildx-plugin', 'iptables-nft', 'docker-compose-plugin-5.5.1']
    assert 'docker-compose-plugin' not in config(load, suil_context, compose={'ensure': 'absent'}).packages

    with pytest.raises(ValueError):
        config(load, suil_context, ensure='29.1.3 && reboot')


def test_modules_extra_is_pinned_to_the_running_kernel(load, suil_context):
    main = load('docker')

    assert (main.modules_extra(config(load, suil_context), '6.12.0-55.el10.x86_64\n')
            == 'kernel-modules-extra-6.12.0-55.el10')


def test_docker_args_carry_every_key_in_a_stable_order(load, suil_context):
    main = load('docker')
    entry = config(load, suil_context, containers={'web': {
        'image':  'nginx:1',
        'user':   '1000:1000',
        'env':    {'A': 1},
        'ports':  ['127.0.0.1:8080:80'],
        'mounts': ['/srv:/srv:ro'],
        'opts':   {'read-only': True, 'm': '512m', 'label': 'a b', 'cap-drop': ['ALL'], 'init': False},
    }})

    assert shlex.join(main.docker_args(entry, 'web', entry.containers['web'])) == (
        '--rm --user 1000:1000 --env-file /opt/web/.env '
        "-p 127.0.0.1:8080:80 -v /srv:/srv:ro --cap-drop=ALL '--label=a b' -m 512m --read-only")


def test_recreate_false_keeps_the_stopped_container(load, suil_context):
    main = load('docker')
    entry = config(load, suil_context, containers={'web': {'image': 'nginx:1', 'recreate': False}})

    assert '--rm' not in main.docker_args(entry, 'web', entry.containers['web'])


def test_the_run_dropin_is_escaped_for_systemd(load, suil_context):
    main = load('docker')
    entry = config(load, suil_context, containers={'web': {
        'image': 'nginx:1', 'pull': False, 'run_opts': ['sh', '-c', 'echo "$HOME" 100%']}})
    rendered = main.run_text(entry, 'web', entry.containers['web'])

    assert 'ExecStartPre' not in rendered
    assert """ExecStart=/usr/bin/docker run --name web --rm nginx:1 sh -c 'echo "$$HOME" 100%%'\n""" in rendered
    assert 'ExecStop=/usr/bin/docker stop --time 30 web\n' in rendered
    assert 'ExecStartPre=-/usr/bin/docker pull nginx:1\n' in main.run_text(
        entry, 'web', entry.containers['web'].model_copy(update={'pull': True}))


def test_the_env_file_is_sorted(load, suil_context):
    main = load('docker')
    rendered = main.env_file(config(load, suil_context), {'B': True, 'A': 'x y'})

    assert rendered.endswith('A=x y\nB=true\n')


def test_a_stack_env_is_single_quoted_against_interpolation(load, suil_context):
    main = load('docker')
    rendered = main.env_file(config(load, suil_context), {'B': True, 'A': '$2b$12$x'}, quoted=True)

    assert rendered.endswith("A='$2b$12$x'\nB='true'\n")


def test_the_static_units_work_in_the_entry_home_and_read_no_environment(load, suil_context):
    main = load('docker')
    entry = config(load, suil_context)
    container = main.unit_text('docker-container@.service')
    compose = main.unit_text('docker-compose@.service')

    assert f'WorkingDirectory={entry.dir}/%i' in container
    assert f'WorkingDirectory={entry.dir}/%i' in compose
    assert f'ConditionPathExists={entry.dir}/%i/docker-compose.yml' in compose
    assert 'EnvironmentFile' not in container + compose
    assert '--restart' not in container


def test_a_stack_reloads_unless_it_recreates(load, suil_context):
    main = load('docker')
    entry = config(load, suil_context, compose={'stacks': {
        'soft': {'content': STACK}, 'hard': {'content': STACK, 'recreate': True}}})

    assert main.stack_action(entry.compose.stacks['soft'], True) == (False, True)
    assert main.stack_action(entry.compose.stacks['hard'], True) == (True, False)
    assert main.stack_action(entry.compose.stacks['hard'], False) == (False, False)


def test_the_engine_reloads_unless_it_restarts(load, suil_context):
    main = load('docker')
    soft = config(load, suil_context)
    hard = config(load, suil_context, restart=True)

    assert main.engine_action(soft, False, True) == (False, True)
    assert main.engine_action(hard, False, True) == (True, False)
    assert main.engine_action(soft, True, True) == (True, False)
    assert main.engine_action(soft, False, False) == (False, False)


def test_expected_names_every_entry_it_manages(load, suil_context):
    main = load('docker')
    entry = config(load, suil_context, ensure='29.1.3',
                   containers={'web': {'image': 'nginx:1', 'env': {'A': 1}}, 'old': {'ensure': 'absent'}},
                   compose={'ensure': '5.5.1',
                            'stacks': {'app': {'content': STACK, 'unit_dropin': '[Service]\nNice=5\n\n'}}})
    reported = main.Docker(entry).expected()
    files = reported['files']

    assert reported['packages'] == {'docker-ce': '29.1.3', 'docker-compose-plugin': '5.5.1'}
    assert files[entry.config_file] == file_digest(main.daemon_json(entry))
    assert files[entry.env_file('web')] == file_digest(main.env_file(entry, {'A': 1}))
    assert files[entry.run_file(entry.container_unit('web'))] == file_digest(
        main.run_text(entry, 'web', entry.containers['web']))
    assert reported['containers']['old'] == {'present': False, 'service': {'running': False, 'enabled': False}}
    assert not any(path.startswith(entry.entry_dir('old')) for path in files)
    assert files[entry.dropin_file(entry.stack_unit('app'))] == file_digest('[Service]\nNice=5\n')
    assert files[entry.compose_file('app')] == file_digest(STACK)
    assert files[entry.env_file('app')] is None
    assert reported['unmanaged'] == {'containers': [], 'stacks': []}
    assert reported['legacy'] == []
    assert main.Docker(config(load, suil_context, ensure='absent')).expected() == {'packages': {'docker-ce': 'absent'}}


def test_a_stack_directory_stays_below_the_stack_or_is_absolute(load, suil_context):
    for path in ('.', '../other', 'db/../../etc', '/'):
        with pytest.raises(ValueError, match='directories'):
            config(load, suil_context, compose={'stacks': {'app': {'content': STACK, 'directories': {path: {}}}}})

    with pytest.raises(ValueError, match='octal'):
        config(load, suil_context,
               compose={'stacks': {'app': {'content': STACK, 'directories': {'db': {'mode': '0789'}}}}})


def test_expected_names_each_stack_directory_by_its_host_path(load, suil_context):
    main = load('docker')
    entry = config(load, suil_context, compose={'stacks': {
        'app': {'content': STACK, 'directories': {'db': {'owner': 10001, 'group': 10001, 'mode': 750},
                                                  '/srv/app': {'mode': '0700'}}},
        'old': {'ensure': 'absent', 'directories': {'db': {}}}}})
    stacks = main.Docker(entry).expected()['stacks']

    assert stacks['app']['directories'] == {
        '/opt/app/db': {'owner': 10001, 'group': 10001, 'mode': '750'},
        '/srv/app':    {'owner': 'app', 'group': 'app', 'mode': '700'},
    }
    assert 'directories' not in stacks['old']
    assert main.Docker(config(load, suil_context, compose={'stacks': {'web': {'content': STACK}}})).expected()[
        'stacks']['web']['directories'] == {}


def test_the_collector_reports_a_directory_the_way_the_config_names_its_owner(tmp_path):
    spec = importlib.util.spec_from_file_location('docker_collector', MODULES_DIR / 'docker' / 'facts' / 'collector.py')
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    (tmp_path / 'app' / 'db').mkdir(parents=True, mode=0o750)
    (tmp_path / 'app' / 'db').chmod(0o750)
    uid, gid = os.getuid(), os.getgid()

    found = collector.directories(str(tmp_path), 'app', {
        'db': {'owner': uid, 'group': str(gid)}, 'gone': {}})

    assert found[f'{tmp_path}/app/db'] == {'owner': uid, 'group': str(gid), 'mode': '750'}
    assert found[f'{tmp_path}/app/gone'] is None


def test_docker_brings_its_forward_rules_to_nftables(load, suil_context):
    merged = deep_unwrap(deep(get_defaults(Root(name='nftables', path=MODULES_DIR / 'nftables')), defaults()))
    entry = load('nftables', 'config').Config(suil=suil_context, **merged['nftables'],
                                              service='nftables', nft_binary='/usr/sbin/nft')
    ruleset = load('nftables', 'ruleset').build(entry)

    for rule in ('ct state established,related counter accept',
                 'iifname "docker0" oifname != "docker0" counter accept',
                 'iifname "br-*" oifname != "br-*" counter accept',
                 'iifname "br-*" oifname "br-*" counter accept'):
        assert f'add rule inet filter forward {rule}' in ruleset

    assert not re.search(r'oifname "docker0"', ruleset)


def test_docker_brings_its_repository_to_repos(load, suil_context):
    entry = load('repos', 'config').Config(suil=suil_context, **defaults()['repos'],
                                           repos_dir='/etc/yum.repos.d', gpg_dir='/etc/pki/rpm-gpg',
                                           rclone_package='rclone', rclone_binary='/usr/bin/rclone')

    assert entry.list['docker-ce-stable'].baseurl == [
        'https://download.docker.com/linux/rhel/$releasever/$basearch/stable']
