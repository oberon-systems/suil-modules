import re

from pathlib import Path

import pytest

from suil.sdk.libs.module import file_digest, get_order, get_requires

BASELINE = Path(__file__).resolve().parent / 'sshd_config.baseline'

OS_LAYER = {'service': 'sshd', 'binary': '/usr/sbin/sshd',
            'sftp_server': '/usr/libexec/openssh/sftp-server', 'print_motd': 'no'}


def config(load, suil_context, **kwargs):
    return load('ssh', 'config').Config(suil=suil_context, **{**OS_LAYER, **kwargs})


def directives(text):
    found = {}

    for line in text.splitlines():
        line = line.strip()

        if line and not line.startswith('#'):
            key, _, value = line.partition(' ')
            found.setdefault(key, []).append(value.strip())

    return found


def test_a_yaml_boolean_is_normalised_back_to_yes_no(load, suil_context):
    entry = config(load, suil_context, password_authentication=False, use_pam=True)

    assert entry.password_authentication == 'no'
    assert entry.use_pam == 'yes'


def test_the_os_layer_is_required_rather_than_defaulted(load, suil_context):
    with pytest.raises(ValueError):
        load('ssh', 'config').Config(suil=suil_context)


def test_the_render_keeps_the_strict_baseline(load, suil_context):
    rendered = directives(load('ssh').render(config(load, suil_context)))
    baseline = directives(BASELINE.read_text())

    # The baseline is the file the ansible role kept as its own yardstick; a
    # weakened default has to fail here rather than on a host.
    for key in ('PermitRootLogin', 'PasswordAuthentication', 'PubkeyAuthentication',
                'PermitEmptyPasswords', 'HostbasedAuthentication', 'IgnoreRhosts',
                'StrictModes', 'ChallengeResponseAuthentication'):
        assert rendered[key] == baseline[key], key


def test_gssapi_is_off_whatever_the_baseline_predates(load, suil_context):
    assert directives(load('ssh').render(config(load, suil_context)))['GSSAPIAuthentication'] == ['no']


def test_include_is_the_last_directive_in_the_file(load, suil_context):
    lines = [line for line in load('ssh').render(config(load, suil_context)).splitlines()
             if line.strip() and not line.strip().startswith('#')]

    # sshd keeps the FIRST value it obtains, so an Include at the top lets
    # 50-redhat.conf put GSSAPIAuthentication and X11Forwarding back to yes.
    assert lines[-1].startswith('Include ')


def test_an_empty_allow_list_writes_no_directive(load, suil_context):
    rendered = load('ssh').render(config(load, suil_context))

    assert 'AllowUsers' not in rendered
    assert 'AllowGroups' not in rendered


def test_allow_users_is_one_space_separated_line(load, suil_context):
    rendered = load('ssh').render(config(load, suil_context, allow_users=['deploy', 'alpha']))

    assert re.search(r'^AllowUsers deploy alpha$', rendered, re.M)


def test_expected_hashes_the_config_that_would_be_written(load, suil_context):
    main = load('ssh')
    entry = config(load, suil_context)

    assert main.Ssh(entry).expected()['files'] == {main.CONFIG_PATH: file_digest(main.render(entry))}


def test_ssh_declares_accounts_rather_than_relying_on_position(modules):
    # The lockout guard reads the authorized_keys accounts is what writes.
    assert get_requires(modules['ssh']) == ['accounts']
    assert get_order(['ssh'], modules) == ['accounts', 'ssh']
