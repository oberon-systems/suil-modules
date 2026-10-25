import re

from pydantic import BaseModel, ConfigDict, field_validator

from suil.sdk import Config as Base

VERSION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+:~-]*$')


class Package(BaseModel):

    model_config = ConfigDict(extra='forbid')

    ensure: str = 'present'

    @field_validator('ensure')
    @classmethod
    def check_ensure(cls, value: str) -> str:
        if value not in ('present', 'absent') and not VERSION.match(value):
            raise ValueError(f'ensure is present, absent or a version, not {value!r}')

        return value


class Config(Base):

    list: dict[str, Package | None] = {}

    @field_validator('list', mode='before')
    @classmethod
    def allow_bare_names(cls, value):
        # `tmux:` with nothing under it is YAML null, not an empty mapping.
        return {name: (spec or {}) for name, spec in (value or {}).items()}
