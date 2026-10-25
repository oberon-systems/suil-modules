import re

from pydantic import Field, field_validator, model_validator

from suil.sdk import Config as Base

# At least two labels: the single-label form a provider's metadata carries is
# exactly what this module replaces, so it must not pass.
FQDN = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$')


class Config(Base):

    manage:            bool = True
    fqdn:              str | None = None
    manage_cloud_init: bool = True
    cloud_init_file:   str = Field(default='/etc/cloud/cloud.cfg.d/99-hostname.cfg')

    @model_validator(mode='after')
    def default_fqdn_to_the_node_key(self) -> 'Config':
        if self.fqdn is None:
            object.__setattr__(self, 'fqdn', self.suil.node)

        return self

    @field_validator('fqdn')
    @classmethod
    def check_fqdn(cls, value: str | None) -> str | None:
        if value is None:
            return value

        if not FQDN.match(value):
            raise ValueError(f'{value!r} is not a dotted lowercase FQDN')

        if len(value) > 253:
            raise ValueError(f'{value!r} is longer than 253 characters')

        if max(len(label) for label in value.split('.')) > 63:
            raise ValueError(f'{value!r} has a label longer than 63 characters')

        return value
