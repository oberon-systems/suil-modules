import pytest

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

from suil.sdk.libs.module import file_digest

OS_LAYER = {
    'package':    'nginx',
    'service':    'nginx',
    'binary':     '/usr/sbin/nginx',
    'user':       'nginx',
    'config_dir': '/etc/nginx',
    'confd_dir':  '/etc/nginx/conf.d',
    'cert_dir':   '/etc/nginx/cert',
    'log_dir':    '/var/log/nginx',
    'pid_file':   '/run/nginx.pid',
    'ca_bundle':  '/etc/pki/tls/certs/ca-bundle.crt',
}

SERVER = 'server {\n    listen 80;\n    server_name me.example.com;\n}'


def config(load, suil_context, **kwargs):
    return load('nginx', 'config').Config(suil=suil_context, **OS_LAYER, **kwargs)


def test_settings_cannot_repeat_the_fixed_block(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, settings={'ssl_protocols': 'TLSv1.2 TLSv1.3'})

    with pytest.raises(ValueError):
        config(load, suil_context, settings={'Sendfile': 'on'})


def test_a_server_cannot_take_the_default_name_or_a_path(load, suil_context):
    with pytest.raises(ValueError):
        config(load, suil_context, servers={'default': SERVER})

    with pytest.raises(ValueError):
        config(load, suil_context, servers={'../evil': SERVER})

    with pytest.raises(ValueError):
        config(load, suil_context, servers={'me.example.com': 'server {'})


def test_a_version_pin_becomes_the_dnf_argument(load, suil_context):
    assert config(load, suil_context, ensure='1.30.4').package_spec == 'nginx-1.30.4'
    assert config(load, suil_context).package_spec == 'nginx'

    with pytest.raises(ValueError):
        config(load, suil_context, ensure='1.30.4 && reboot')


def test_nginx_conf_carries_the_ssl_block_and_sorted_settings(load, suil_context):
    main = load('nginx')
    rendered = main.render(config(load, suil_context,
                                  settings={'sendfile': 'on', 'gzip': 'on', 'gzip_types': ['text/css', 'text/xml']}),
                           'nginx.conf.j2')

    for line in ('ssl_protocols TLSv1.3;', 'ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;',
                 'ssl_prefer_server_ciphers off;', 'ssl_stapling on;', 'ssl_stapling_verify on;',
                 'ssl_trusted_certificate /etc/pki/tls/certs/ca-bundle.crt;', 'resolver 127.0.0.1;',
                 'include /etc/nginx/conf.d/*.conf;'):
        assert line in rendered

    assert rendered.index('gzip on;') < rendered.index('gzip_types text/css;') < rendered.index('sendfile on;')
    assert 'gzip_types text/xml;' in rendered


def test_default_conf_listens_on_both_ports_and_redirects_http(load):
    static = load('nginx').default_conf()

    assert 'listen 80 default_server;' in static
    assert 'listen 443 ssl default_server;' in static
    assert 'return 302 https://$host$request_uri;' in static


def test_default_conf_names_the_certificate_the_module_writes(load, suil_context):
    # The file is static, so this is what catches cert_dir moving without it.
    entry = config(load, suil_context)
    static = load('nginx').default_conf()

    assert f'ssl_certificate     {entry.cert_file};' in static
    assert f'ssl_certificate_key {entry.key_file};' in static
    assert f'access_log {entry.log_dir}/default.log main;' in static


def test_without_the_default_server_nothing_of_it_is_expected(load, suil_context):
    main = load('nginx')
    entry = config(load, suil_context, set_default=False, servers={'me.example.com': SERVER})
    reported = main.Nginx(entry).expected()

    assert reported['files'][entry.default_file] is None
    assert reported['certificate'] is None
    assert 'server_name _;' not in main.candidate(entry)
    assert 'server_name me.example.com;' in main.candidate(entry)


def test_the_candidate_inlines_conf_d(load, suil_context):
    main = load('nginx')
    rendered = main.candidate(config(load, suil_context, servers={'me.example.com': SERVER, 'gone': None}))

    assert 'include /etc/nginx/conf.d/*.conf;' not in rendered
    assert 'server_name me.example.com;' in rendered
    assert 'server_name _;' in rendered
    assert rendered.count('{') == rendered.count('}')


def test_the_junk_certificate_matches_its_key(load):
    key_pem, cert_pem = load('nginx', 'certificate').junk_certificate(2048)
    key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    cert = x509.load_pem_x509_certificate(cert_pem.encode())

    assert key.key_size == 2048
    assert cert.public_key().public_numbers() == key.public_key().public_numbers()
    assert cert.subject == cert.issuer
    assert cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value.endswith('.example.com')


def test_expected_names_every_file_the_certificate_and_the_check(load, suil_context):
    main = load('nginx')
    entry = config(load, suil_context, ensure='1.30.4', servers={'me.example.com': SERVER, 'gone': None})
    reported = main.Nginx(entry).expected()

    assert reported['package'] == '1.30.4'
    assert reported['files'] == {
        entry.main_file:                     file_digest(main.render(entry, 'nginx.conf.j2')),
        entry.default_file:                  file_digest(main.default_conf()),
        entry.server_file('me.example.com'): file_digest(SERVER + '\n'),
        entry.server_file('gone'):           None,
    }
    assert reported['unmanaged'] == []
    assert reported['certificate'] == {'key_bits': 2048, 'cert': True}
    assert reported['checked'] is True
    assert main.Nginx(config(load, suil_context, ensure='absent')).expected() == {'package': 'absent'}


def test_a_package_is_stale_until_the_facts_report_the_pin(load, suil_context):
    main = load('nginx')
    pinned = config(load, suil_context, ensure='1.30.4')

    assert not main._stale(pinned, '1.30.4')
    assert main._stale(pinned, '1.30.40')
    assert main._stale(pinned, 'absent')
    assert not main._stale(config(load, suil_context), 'present')


def test_the_resolver_is_one_directive_of_its_own(load, suil_context):
    rendered = load('nginx').render(config(load, suil_context, resolver='192.0.2.53 valid=300s'), 'nginx.conf.j2')

    assert 'resolver 192.0.2.53 valid=300s;' in rendered
    assert 'resolver 127.0.0.1;' not in rendered

    for broken in ('', '1.1.1.1; include /tmp/x', '1.1.1.1\nuser root'):
        with pytest.raises(ValueError, match='resolver'):
            config(load, suil_context, resolver=broken)
