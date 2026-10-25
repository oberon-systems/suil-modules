import hashlib
import json
import os
import subprocess
import sys
import zipfile

import pytest

from suil.sdk import ModuleError, ModuleValidateError, facter
from suil.sdk.libs.module import file_digest

# A throwaway key, never used on a host.
PRIVATE = 'aGVsbG8taGVsbG8taGVsbG8taGVsbG8taGVsbG8tMTI'

REALITY = {
    'tag':      'reality',
    'listen':   '192.0.2.1',
    'port':     443,
    'protocol': 'vless',
    'settings': {'clients': [], 'decryption': 'none'},
    'streamSettings': {
        'network':  'tcp',
        'security': 'reality',
        'realitySettings': {'dest': 'www.example.com:443', 'serverNames': ['www.example.com'],
                            'shortIds': ['0123abcd']},
    },
}


def config(load, suil_context, **kwargs):
    return load('xray', 'config').Config(suil=suil_context, **kwargs)


def with_reality(load, suil_context, inbound=None, **kwargs):
    return config(load, suil_context, inbounds=[inbound or REALITY], reality_private_key=PRIVATE, **kwargs)


@pytest.mark.parametrize('broken', [{'version': '26.3.27'}, {'version': 'latest'}, {'sha256': 'abc'}])
def test_a_version_or_checksum_the_url_cannot_carry_is_refused(load, suil_context, broken):
    with pytest.raises(ValueError):
        config(load, suil_context, **broken)


def test_every_inbound_needs_a_tag_of_its_own(load, suil_context):
    with pytest.raises(ValueError, match='tag'):
        config(load, suil_context, inbounds=[{**REALITY, 'tag': 'api'}], reality_private_key=PRIVATE)

    with pytest.raises(ValueError, match='tag'):
        config(load, suil_context, inbounds=[{'port': 1}])


def test_a_reality_inbound_without_its_settings_or_key_is_refused(load, suil_context):
    broken = {**REALITY, 'streamSettings': {**REALITY['streamSettings'],
                                            'realitySettings': {'dest': 'www.example.com:443'}}}

    with pytest.raises(ValueError, match='serverNames'):
        with_reality(load, suil_context, inbound=broken)

    with pytest.raises(ValueError, match='reality_private_key'):
        config(load, suil_context, inbounds=[REALITY])


def test_base_config_cannot_carry_what_the_module_renders(load, suil_context):
    with pytest.raises(ValueError, match='inbounds'):
        config(load, suil_context, base_config={'inbounds': []})


def test_the_document_puts_the_api_first_and_folds_the_key_in(load, suil_context):
    entry = with_reality(load, suil_context, base_config={'outbounds': [{'protocol': 'freedom'}]},
                         log_level='error')
    document = entry.document()

    assert [inbound['tag'] for inbound in document['inbounds']] == ['api', 'reality']
    assert document['inbounds'][1]['streamSettings']['realitySettings']['privateKey'] == PRIVATE
    assert 'privateKey' not in entry.inbounds[0]['streamSettings']['realitySettings']
    assert document['log'] == {'loglevel': 'error'}
    assert document['outbounds'] == [{'protocol': 'freedom'}]


def test_the_unit_runs_the_binary_on_the_config_as_the_service_user(load, suil_context):
    main = load('xray')
    unit = main.render(config(load, suil_context), 'xray.service.j2')

    assert 'ExecStart=/usr/local/bin/xray run -c /usr/local/etc/xray/config.json' in unit
    assert 'User=xray' in unit
    assert 'Environment=XRAY_LOCATION_ASSET=/usr/local/share/xray' in unit


def test_expected_names_every_file_the_check_and_the_service(load, suil_context):
    main = load('xray')
    entry = with_reality(load, suil_context)

    assert main.Xray(entry).expected() == {
        'files': {
            entry.stamp_file: file_digest('v26.3.27\n'),
            entry.unit_file:  file_digest(main.render(entry, 'xray.service.j2')),
        },
        'config':  main.config_digest(entry.document()),
        'checked': True,
        'service': {'running': True, 'enabled': True},
    }


def with_clients(document):
    document = json.loads(json.dumps(document))
    client = {'id': 'a709fc4b', 'email': 'someone', 'flow': 'xtls-rprx-vision'}
    document['inbounds'][1]['settings']['clients'] = [client]

    return document


def test_the_clients_the_agent_adds_are_no_drift(load, suil_context):
    main = load('xray')
    entry = with_reality(load, suil_context)

    assert main.config_digest(with_clients(entry.document())) == main.config_digest(entry.document())
    assert main.config_digest(with_reality(load, suil_context, log_level='error').document()) != \
        main.config_digest(entry.document())


def test_the_collector_reports_the_digest_expected_computes(load, suil_context, tmp_path, modules):
    main = load('xray')
    entry = with_reality(load, suil_context)

    (tmp_path / 'config.json').write_text(json.dumps(with_clients(entry.document()), indent=4))
    (tmp_path / 'systemctl').write_text('#!/bin/sh\necho inactive\n')
    (tmp_path / 'systemctl').chmod(0o755)
    (tmp_path / 'public.json').write_text(json.dumps({'config_dir': str(tmp_path), 'bin_dir': str(tmp_path)}))

    stdout = subprocess.run([sys.executable, facter.__file__, str(modules['xray'].path / 'facts' / 'collector.py'),
                             str(tmp_path / 'public.json')],
                            env={**os.environ, 'PATH': str(tmp_path)}, check=True, capture_output=True).stdout

    assert json.loads(stdout)['config'] == main.config_digest(entry.document())


def test_a_written_config_keeps_the_clients_of_the_live_one(load, suil_context, tmp_path):
    main = load('xray')
    entry = with_reality(load, suil_context, log_level='error')
    live = with_clients(with_reality(load, suil_context).document())

    (tmp_path / 'config.json').write_text(json.dumps(live))
    (tmp_path / 'config.json.suil').write_text(main.config_text(entry))

    subprocess.run([sys.executable, '-c', main.MERGE, str(tmp_path / 'config.json.suil'),
                    str(tmp_path / 'config.json')], check=True)

    written = json.loads((tmp_path / 'config.json').read_text())

    assert written['log'] == {'loglevel': 'error'}
    assert written['inbounds'][1]['settings']['clients'] == live['inbounds'][1]['settings']['clients']
    assert not (tmp_path / 'config.json.suil').exists()


def test_the_release_is_read_and_checked_on_the_control_machine(load, tmp_path):
    release = load('xray', 'release')
    archive = tmp_path / 'Xray-linux-64.zip'

    with zipfile.ZipFile(archive, 'w') as stream:
        for name in ('xray', 'geoip.dat', 'geosite.dat', 'README.md'):
            stream.writestr(name, name)

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    members = release.fetch_release(archive.as_uri(), digest)

    assert sorted(members) == ['geoip.dat', 'geosite.dat', 'xray']

    with pytest.raises(ModuleError, match='sha256'):
        release.fetch_release(archive.as_uri(), '0' * 64)


def test_the_release_binary_judges_config_json_before_it_is_written(load):
    release = load('xray', 'release')
    accepting = b'#!/bin/sh\ngrep -q inbounds "$4"\n'
    refusing = b'#!/bin/sh\necho "invalid privateKey" >&2\nexit 1\n'

    release.check_config(accepting, '{"inbounds": []}')

    with pytest.raises(ModuleValidateError, match='invalid privateKey'):
        release.check_config(refusing, '{"inbounds": []}')
