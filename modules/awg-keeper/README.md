# awg-keeper

Installs the agent half of [awg-keeper](https://github.com/oberon-systems/awg-keeper)
from its GitHub release, writes `/etc/awg-keeper/agent.env`, and keeps
`awg-keeper-agent.service` up. The Panel is not here: it is a container, and
`modules/docker` owns compose stacks.

- [Why the module exists](#why-the-module-exists)
- [Config](#config)
- [Install](#install)
- [The drop-in](#the-drop-in)
- [Facts](#facts)

## Why the module exists

The Panel issues client profiles, and the agent is what it calls to add and
remove peers on an AmneziaWG interface and users in Xray. The agent holds no
capabilities: `awg` reaches amneziawg-go through `systemd-socket-proxyd`
sockets that the agent's package ships. Whoever can call the agent can still
change every peer, so where it listens and who may call it are the whole of
its security. The module is a port of the retired ansible `roles/awg-keeper`.

## Config

```yaml
awg-keeper:
  token:           !ENC[...]
  bind:            172.18.0.1
  allowed_subnets: [172.18.0.0/16]
  interfaces:      [awg0]
  unit_dropin: |
    [Service]
    SupplementaryGroups=xray
    ReadWritePaths=/usr/local/etc/xray
```

| Key | Default | What it does |
| --- | ------- | ------------ |
| `version`, `release` | `0.4.0`, `1` | The agent release and the packager's release field |
| `sha256` | `""` | Digest of the rpm; empty warns and installs unpinned |
| `manage_service` | `true` | Start and enable the agent, restart it on a change |
| `unit_dropin` | none | `awg-keeper-agent.service.d/override.conf`; dropping it removes the directory |
| `token` | required | The Panel's bearer token, at least 32 characters |
| `bind`, `port` | `127.0.0.1`, `8081` | The listener; never a wildcard |
| `allowed_subnets` | `[]` | Who may call; empty is refused |
| `interfaces` | `[]` | The awg interfaces the agent may drive |
| `awg_bin`, `awg_conf_dir` | `awg`, `/etc/amnezia/amneziawg` | What the agent calls and rewrites |
| `ip_bin` | `ip` | What the agent reads interface addresses with |
| `xray_bin`, `xray_api`, `xray_config` | `xray`, `127.0.0.1:8085`, `/usr/local/etc/xray/config.json` | The same for Xray |
| `command_timeout`, `log_level`, `docs` | `10.0`, `INFO`, `false` | Passed through |

`artifact` comes from the OS layer, `data/os/<family>/<release>.yaml`, because
nfpm names the rpm and the deb differently.

The agent parses `agent.env` with `extra="forbid"` and refuses any
`AWG_KEEPER_*` variable its `config.py` does not know. The template therefore
renders exactly the fields of the agent's `Settings`, and a test fails when the
two drift. Add a key to both or to neither.

## Install

Only when rpm reports a version other than `<version>-<release>`: the rpm is
downloaded on the host from
`releases/download/awg-keeper-agent-v<version>/` into `/var/cache/awg-keeper`
and installed with dnf. nfpm signs nothing, and dnf does not gpg-check a local
file. The package's postinstall mints a token on a first install; `agent.env`
is written after it, so the token from the data wins.

## The drop-in

The unit lists `/etc/amnezia/amneziawg` in `ReadWritePaths` without a `-`, and
systemd fails it with 226/NAMESPACE when the path is missing, naming nothing
useful. `requires.yaml` puts `amneziawg` and `xray` first for that reason: the
modules that create those paths run before this one.

Xray's `config.json` is reached through the drop-in rather than ownership:
`SupplementaryGroups=xray` plus `ReadWritePaths=/usr/local/etc/xray`, into a
setgid `root:xray` directory. The agent's account never has to exist before
`xray` runs, which is what removes the circular dependency the ansible roles
had.

## Facts

The collector reports the installed version, the digests of `agent.env` and
the drop-in - `agent.env` carries the token, so only its digest ever leaves the
host - and the state of the service.
