from pydantic import BaseModel, ConfigDict, field_validator

from suil.sdk import Config as Base, Secret


class Account(BaseModel):

    model_config = ConfigDict(extra='forbid')

    ensure:         str = 'present'
    shell:          str = '/bin/bash'
    system:         bool = False
    groups:         list[str] | str = []
    append:         bool | None = None
    password:       Secret | None = None
    auth_key:       str | None = None
    keys_exclusive: bool | None = None
    sudo:           str | None = None

    @field_validator('ensure')
    @classmethod
    def check_ensure(cls, value: str) -> str:
        if value not in ('present', 'absent'):
            raise ValueError(f'ensure is present or absent, not {value!r}')

        return value

    @field_validator('groups')
    @classmethod
    def one_group_is_a_list(cls, value):
        return [value] if isinstance(value, str) else value


class Config(Base):

    users:          dict[str, Account | None] = {}
    groups_append:  bool = True
    manage_sudo:    bool = True
    keys_exclusive: bool = False
    visudo:         str = '/usr/sbin/visudo'

    @field_validator('users', mode='before')
    @classmethod
    def allow_bare_names(cls, value):
        return {name: (spec or {}) for name, spec in (value or {}).items()}
