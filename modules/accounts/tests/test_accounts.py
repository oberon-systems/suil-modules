import pytest


def config(load, suil_context, **kwargs):
    return load('accounts', 'config').Config(suil=suil_context, **kwargs)


def test_an_unknown_ensure_value_is_refused(load, suil_context):
    with pytest.raises(ValueError, match='present or absent'):
        config(load, suil_context, users={'deploy': {'ensure': 'gone'}})


def test_one_group_may_be_written_as_a_string(load, suil_context):
    entry = config(load, suil_context, users={'alpha': {'groups': 'wheel'}})

    assert entry.users['alpha'].groups == ['wheel']


def test_expected_carries_digests_and_never_a_secret(load, suil_context):
    main = load('accounts')
    key = 'ssh-ed25519 AAAA... alpha'
    entry = config(load, suil_context, users={
        'alpha': {'auth_key': key, 'sudo': 'alpha ALL=(ALL) NOPASSWD: ALL'},
        'ubuntu': {'ensure': 'absent'},
    })

    reported = main.Accounts(entry).expected()['users']

    assert reported['ubuntu'] == {'ensure': 'absent'}
    assert reported['alpha']['auth_key'].startswith('sha256:')
    assert key not in str(reported)
