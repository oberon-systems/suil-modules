import copy
import re

from pydantic import field_validator, model_validator

from suil.sdk import Config as Base, Secret

VERSION = re.compile(r'^v[0-9]+\.[0-9]+\.[0-9]+$')
SHA256 = re.compile(r'^([0-9a-f]{64})?$')

LOG_LEVELS = ('debug', 'info', 'warning', 'error', 'none')

# A Reality inbound missing any of these starts and rejects every client.
REALITY_REQUIRED = ('dest', 'serverNames', 'shortIds')

# config.json renders these itself; base_config may not carry a second copy.
RENDERED = ('log', 'inbounds')


class Config(Base):

    version: str = 'v26.3.27'
    sha256:  str = ''

    release_base: str = 'https://github.com/XTLS/Xray-core/releases/download'
    asset:        str = 'Xray-linux-64.zip'

    manage_service: bool = True

    user:  str = 'xray'
    group: str = 'xray'

    # xray.service carries none of these as literals: the unit is rendered.
    bin_dir:      str = '/usr/local/bin'
    share_dir:    str = '/usr/local/share/xray'
    config_dir:   str = '/usr/local/etc/xray'
    stamp_file:   str = '/usr/local/lib/xray/version'
    unit_dir:     str = '/etc/systemd/system'

    log_level: str = 'warning'

    # The api inbound the awg-keeper agent drives through `xray api adu`.
    api_inbound: dict = {
        'tag':      'api',
        'listen':   '127.0.0.1',
        'port':     8085,
        'protocol': 'dokodemo-door',
        'settings': {'address': '127.0.0.1'},
    }

    inbounds: list[dict] = []

    reality_private_key: Secret = ''

    base_config: dict = {}

    @field_validator('version')
    @classmethod
    def check_version(cls, value: str) -> str:
        if not VERSION.match(value):
            raise ValueError(f'version is an upstream release tag like v26.3.27, not {value!r}')

        return value

    @field_validator('sha256')
    @classmethod
    def check_sha256(cls, value: str) -> str:
        if not SHA256.match(value):
            raise ValueError('sha256 is empty or 64 lowercase hex digits')

        return value

    @field_validator('log_level')
    @classmethod
    def check_log_level(cls, value: str) -> str:
        if value not in LOG_LEVELS:
            raise ValueError(f'log_level is one of {", ".join(LOG_LEVELS)}, not {value!r}')

        return value

    @model_validator(mode='after')
    def check(self) -> 'Config':
        if clash := sorted(set(self.base_config) & set(RENDERED)):
            raise ValueError(f'base_config cannot set {", ".join(clash)}: config.json renders it')

        tags = [inbound.get('tag') for inbound in [self.api_inbound, *self.inbounds]]

        # The agent addresses an inbound by its tag.
        if not all(tags) or len(tags) != len(set(tags)):
            raise ValueError(f'every inbound needs a tag of its own, got {tags}')

        for inbound in self.inbounds:
            stream = inbound.get('streamSettings') or {}

            if stream.get('security') != 'reality':
                continue

            settings = stream.get('realitySettings') or {}

            if missing := [key for key in REALITY_REQUIRED if not settings.get(key)]:
                raise ValueError(f'inbound {inbound["tag"]} is Reality without {", ".join(missing)}')

            if not self.reality_private_key:
                raise ValueError(f'inbound {inbound["tag"]} is Reality and reality_private_key is empty')

        return self

    def document(self) -> dict:
        """config.json as the first run writes it, the private key folded in."""
        inbounds = []

        for inbound in [self.api_inbound, *self.inbounds]:
            inbound = copy.deepcopy(inbound)
            stream = inbound.get('streamSettings') or {}

            if stream.get('security') == 'reality':
                stream.setdefault('realitySettings', {})['privateKey'] = self.reality_private_key

            inbounds.append(inbound)

        return {'log': {'loglevel': self.log_level}, **copy.deepcopy(self.base_config), 'inbounds': inbounds}

    @property
    def binary(self) -> str:
        return f'{self.bin_dir}/xray'

    @property
    def config_file(self) -> str:
        return f'{self.config_dir}/config.json'

    @property
    def unit(self) -> str:
        return 'xray.service'

    @property
    def unit_file(self) -> str:
        return f'{self.unit_dir}/{self.unit}'

    @property
    def url(self) -> str:
        return f'{self.release_base}/{self.version}/{self.asset}'
