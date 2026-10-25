from typing import Annotated

from pydantic import BeforeValidator, field_validator, model_validator

from suil.sdk import Config as Base

# sshd wants yes/no. YAML turns an unquoted yes into True and would render it
# as `True`, which sshd rejects, so every such value is normalised here.
YESNO = {True: 'yes', False: 'no'}


def _yesno(value):
    return YESNO.get(value, value) if isinstance(value, bool) else value


YesNo = Annotated[str, BeforeValidator(_yesno)]


class Config(Base):

    port:                    int = 22
    listen_addresses:        list[str] = []

    permit_root_login:       YesNo = 'no'
    password_authentication: YesNo = 'no'
    pubkey_authentication:   YesNo = 'yes'
    permit_empty_passwords:  YesNo = 'no'
    use_pam:                 YesNo = 'yes'

    x11_forwarding:          YesNo = 'no'
    tcp_forwarding:          YesNo = 'yes'
    log_level:               str = 'INFO'
    max_auth_tries:          int = 4
    login_grace_time:        int = 30
    client_alive_interval:   int = 300
    client_alive_count_max:  int = 2

    allow_users:             list[str] = []
    allow_groups:            list[str] = []
    include:                 str = '/etc/ssh/sshd_config.d/*.conf'
    accept_env:              list[str] = []

    manage_service:          bool = True
    lockout_check:           bool = True

    # From the OS layer, data/os/<family>/<release>.yaml.
    service:                 str
    binary:                  str
    sftp_server:             str
    print_motd:              YesNo = 'no'

    @field_validator('log_level')
    @classmethod
    def check_log_level(cls, value: str) -> str:
        levels = ('QUIET', 'FATAL', 'ERROR', 'INFO', 'VERBOSE',
                  'DEBUG', 'DEBUG1', 'DEBUG2', 'DEBUG3')

        if value not in levels:
            raise ValueError(f'LogLevel is one of {", ".join(levels)}, not {value!r}')

        return value

    @model_validator(mode='after')
    def refuse_to_lock_the_connecting_account_out(self) -> 'Config':
        if not self.lockout_check:
            return self

        if self.suil.ssh_user == 'root' and self.permit_root_login in ('no', 'false'):
            raise ValueError(
                f'{self.suil.node} is reached as root and this config sets '
                f'PermitRootLogin no. Connect as another account, or set lockout_check: false.')

        return self
