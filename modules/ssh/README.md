# ssh

Renders `/etc/ssh/sshd_config` and keeps the service up. Host keys, ciphers and
the crypto policy are the distribution's business, not this module's.

## Config

Flat names on purpose. A nested dict has to be restated in full to change one
key, and there are too many keys here for that to be safe.

| Key | Default |
| --- | ------- |
| `port` | `22` |
| `listen_addresses` | `[]` |
| `permit_root_login` | `no` |
| `password_authentication` | `no` |
| `pubkey_authentication` | `yes` |
| `permit_empty_passwords` | `no` |
| `use_pam` | `yes` |
| `x11_forwarding` | `no` |
| `tcp_forwarding` | `yes` |
| `log_level` | `INFO` |
| `max_auth_tries` | `4` |
| `login_grace_time` | `30` |
| `client_alive_interval` | `300` |
| `client_alive_count_max` | `2` |
| `allow_users`, `allow_groups` | `[]` — empty writes no directive at all |
| `include` | `/etc/ssh/sshd_config.d/*.conf` — empty leaves it out |
| `accept_env` | the locale set |
| `manage_service` | `true` |
| `lockout_check` | `true` |

`service`, `binary`, `sftp_server` and `print_motd` come from the OS layer,
`data/os/<family>/<release>.yaml`. The model has no defaults for the first
three: a family with no OS layer fails loudly on the control machine instead of
rendering a config for the wrong distribution.

A YAML `yes` is a boolean, and `PasswordAuthentication True` is a config sshd
rejects. Every such value is normalised back to `yes`/`no` by the model, so an
unquoted `true` in a node layer still works.

## `Include` is last, and that is the whole point

sshd keeps the **first** value it obtains for a directive. The stock EL config
puts `Include` at the top, which lets `/etc/ssh/sshd_config.d/50-redhat.conf`
quietly put `GSSAPIAuthentication` and `X11Forwarding` back to `yes`. Down at
the bottom the values above win, while `Ciphers`, `MACs` and `KexAlgorithms` —
which this template does not set — still come from the system crypto policy.

## Nothing is written before sshd has read it

The rendered config is staged on the target and put through
`<binary> -t -f <staged>` before `files.put` is ever declared. A rejected
config fails the run with sshd's own message and never reaches
`/etc/ssh/sshd_config`. The module refuses to run the check at all when
`/etc/ssh/ssh_host_ed25519_key` is missing, because `sshd -t` fails on absent
host keys rather than on the config, and that error blames the wrong thing.

`tests/sshd_config.baseline` is not deployed anywhere. It is the strict
baseline the render is asserted against in `tests/test_ssh.py`, so a weakened
default fails the tests.

## Facts

`sha256` of the live `/etc/ssh/sshd_config` and whether the service is running
and enabled. `expected()` renders the config on the control machine and hashes
that, so the diff compares the file that would be written against the file that
is there.
