from pydantic import field_validator

from suil.sdk import Config as Base

MODES = ('enforcing', 'permissive', 'disabled')


class Config(Base):

    manage: bool = True
    mode:   str = 'enforcing'
    policy: str = 'targeted'

    config_file:  str = '/etc/selinux/config'
    enforce_file: str = '/sys/fs/selinux/enforce'

    @field_validator('mode')
    @classmethod
    def check_mode(cls, value: str) -> str:
        if value not in MODES:
            raise ValueError(f'mode is one of {", ".join(MODES)}, not {value!r}')

        return value
