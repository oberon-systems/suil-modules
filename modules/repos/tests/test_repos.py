import configparser

import pytest

OS_LAYER = {
    'repos_dir':      '/etc/yum.repos.d',
    'gpg_dir':        '/etc/pki/rpm-gpg',
    'rclone_package': 'rclone',
    'rclone_binary':  '/usr/bin/rclone',
}

STORE = {
    'provider':          'Cloudflare',
    'endpoint':          'https://account.r2.cloudflarestorage.com',
    'bucket':            'repo',
    'access_key_id':     'key',
    'secret_access_key': 'secret',
    'listen':            '127.0.0.1:8083',
}

SITE = {'store_user': 'alpha-repo', 'unit_format': 'repo-{store}-alpha'}


def config(load, suil_context, **kwargs):
    return load('repos', 'config').Config(suil=suil_context, **OS_LAYER, **kwargs)


def parse(text):
    parser = configparser.ConfigParser()
    parser.read_string(text)

    return parser


def test_a_repository_without_a_source_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, list={'epel': {'gpgcheck': False}})


def test_a_repository_with_two_sources_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, list={'epel': {
            'baseurl': 'https://example.net/', 'metalink': 'https://example.net/m', 'gpgcheck': False}})


def test_an_id_dnf_would_not_accept_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, list={'not a repoid': {
            'baseurl': 'https://example.net/', 'gpgcheck': False}})


def test_a_store_nothing_declares_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, list={'example': {'store': 'repo', 'gpgcheck': False}})


def test_gpgcheck_without_a_key_is_refused(load, suil_context):
    # dnf fails the first install on an unknown key, and says nothing useful.
    with pytest.raises(ValueError):
        config(load, suil_context, list={'epel': {'baseurl': 'https://example.net/'}})


def test_a_gpgkey_no_keys_entry_writes_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, list={'example': {
            'baseurl': 'https://example.net/',
            'gpgkey':  'file:///etc/pki/rpm-gpg/RPM-GPG-KEY-example'}})


def test_a_gpgkey_a_keys_entry_writes_is_accepted(load, suil_context):
    entry = config(
        load, suil_context,
        keys={'RPM-GPG-KEY-example': {'content': 'key'}},
        list={'example': {'baseurl': 'https://example.net/',
                          'gpgkey': 'file:///etc/pki/rpm-gpg/RPM-GPG-KEY-example'}})

    assert entry.list['example'].gpgkey == ['file:///etc/pki/rpm-gpg/RPM-GPG-KEY-example']


def test_two_stores_on_one_port_are_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, **SITE, stores={'one': STORE, 'two': dict(STORE, bucket='other')})


def test_a_store_without_credentials_is_refused(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, **SITE, stores={'repo': dict(STORE, secret_access_key='')})


def test_the_rendered_file_is_ini_dnf_can_read(load, suil_context):
    main = load('repos')
    entry = config(load, suil_context, list={'epel': {
        'description': 'Extra Packages $releasever',
        'metalink':    'https://mirrors.example.net/metalink?repo=epel-$releasever',
        'gpgkey':      ['https://example.net/KEY-1', 'https://example.net/KEY-2'],
        'priority':    10,
        'options':     {'countme': 1},
    }})

    parsed = parse(main.render_repo(entry, 'epel', entry.list['epel']))

    assert parsed['epel']['name'] == 'Extra Packages $releasever'
    assert parsed['epel']['metalink'] == 'https://mirrors.example.net/metalink?repo=epel-$releasever'
    assert parsed['epel']['gpgkey'] == 'https://example.net/KEY-1 https://example.net/KEY-2'
    assert parsed['epel']['gpgcheck'] == '1'
    assert parsed['epel']['priority'] == '10'
    assert parsed['epel']['countme'] == '1'
    assert 'baseurl' not in parsed['epel']


def test_a_store_backed_repository_points_at_the_loopback_front(load, suil_context):
    main = load('repos')
    entry = config(load, suil_context, **SITE, stores={'repo': STORE}, list={'example': {
        'store': 'repo', 'path': '/rpm/rocky/10/x86_64/', 'gpgcheck': False}})

    parsed = parse(main.render_repo(entry, 'example', entry.list['example']))

    assert parsed['example']['baseurl'] == 'http://127.0.0.1:8083/rpm/rocky/10/x86_64/'
    # dnf aborts a whole transaction over one repository it cannot reach, and
    # the front is not up yet when the first run installs rclone.
    assert parsed['example']['skip_if_unavailable'] == '1'


def test_a_plain_repository_keeps_dnfs_own_skip_default(load, suil_context):
    main = load('repos')
    entry = config(load, suil_context, list={'local': {
        'baseurl': 'file:///srv/repo/x86_64', 'gpgcheck': False}})

    assert 'skip_if_unavailable' not in parse(
        main.render_repo(entry, 'local', entry.list['local']))['local']


def test_the_unit_runs_rclone_read_only_as_the_store_account(load, suil_context):
    main = load('repos')
    entry = config(load, suil_context, **SITE, stores={'repo': STORE})
    unit = main.render_unit(entry, 'repo', entry.stores['repo'])

    assert 'User=alpha-repo' in unit
    assert '/usr/bin/rclone serve http --read-only' in unit
    assert '--addr 127.0.0.1:8083' in unit
    assert 'repo:repo' in unit
    assert 'CacheDirectory=repo-repo-alpha' in unit


def test_expected_carries_the_shape_the_collector_prints(load, suil_context):
    main = load('repos')
    entry = config(
        load, suil_context,
        keys={'RPM-GPG-KEY-example': {'content': 'key'}},
        **SITE,
        stores={'repo': STORE},
        list={'example': {'store': 'repo', 'path': 'rpm', 'gpgcheck': False},
              'gone': {'ensure': 'absent'}})

    expected = main.Repos(entry).expected()

    assert set(expected) == {'files', 'list', 'stores', 'unmanaged'}
    assert expected['list']['gone'] == {'ensure': 'absent'}
    assert expected['files'][main.repo_file(entry, 'gone')] is None
    assert expected['stores']['repo']['service'] == {'running': True, 'enabled': True}
    assert expected['stores']['repo']['listening'] is True
    assert expected['files'][main.key_file(entry, 'RPM-GPG-KEY-example')] is not None


def test_a_file_fetched_from_a_url_has_no_digest_to_expect(load, suil_context):
    main = load('repos')
    entry = config(load, suil_context, list={'docker-ce': {
        'file': {'url': 'https://download.docker.com/linux/centos/docker-ce.repo'}}})

    assert main.repo_file(entry, 'docker-ce') not in main.Repos(entry).expected()['files']
    assert main.Repos(entry).expected()['list']['docker-ce'] == {'ensure': 'present'}


def test_a_host_without_stores_needs_no_store_account(load, suil_context):
    entry = config(load, suil_context, list={'epel': {'baseurl': 'https://example.net/', 'gpgcheck': False}})

    assert entry.store_user is None and entry.unit_format is None


@pytest.mark.parametrize('missing', ['store_user', 'unit_format'])
def test_a_store_without_its_site_settings_is_refused(load, suil_context, missing):
    site = {key: value for key, value in SITE.items() if key != missing}

    with pytest.raises(ValueError, match=missing):
        config(load, suil_context, **site, stores={'repo': STORE})


def test_a_unit_format_without_the_store_placeholder_is_refused(load, suil_context):
    with pytest.raises(ValueError, match='placeholder'):
        config(load, suil_context, store_user='alpha-repo', unit_format='repo-alpha', stores={'repo': STORE})


def test_a_store_unit_wins_over_the_format(load, suil_context):
    entry = config(load, suil_context, store_user='alpha-repo',
                   stores={'repo': dict(STORE, unit='beta-front')})

    assert entry.unit('repo') == 'beta-front'
