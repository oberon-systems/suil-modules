# docker

Installs [Docker Engine](https://docs.docker.com/engine/) and the
[compose plugin](https://docs.docker.com/compose/) from the upstream
repository, writes the whole of `daemon.json`, and runs every container and
compose stack as an instance of one of two static systemd template units.

- [Why the module exists](#why-the-module-exists)
- [Config](#config)
- [Containers](#containers)
- [Compose stacks](#compose-stacks)
- [Overriding a unit](#overriding-a-unit)
- [The firewall](#the-firewall)
- [The engine on an nftables host](#the-engine-on-an-nftables-host)
- [Validation and facts](#validation-and-facts)

## Why the module exists

A host that runs containers needs the engine, the compose plugin and a way
to keep both running. The module is a port of the retired ansible
`roles/docker`, which was in turn a port of the puppet `docker_distribution`.
Nothing relies on docker's own restart policy: whatever must survive a reboot
is a unit, so `systemctl` answers what runs and why.

## Config

```yaml
docker:
  ensure: 29.1.3

  config:
    bip: 192.168.200.1/24

  containers:
    registry:
      image:  docker.io/library/registry:2
      ports:  ["127.0.0.1:5000:5000"]
      mounts: ["/var/lib/registry:/var/lib/registry"]

  compose:
    ensure: 5.5.1
    stacks:
      monitoring:
        env:
          GRAFANA_PORT: "3000"
        content: |
          services:
            grafana:
              image: docker.io/grafana/grafana:12.0.0
              ports:
                - "127.0.0.1:${GRAFANA_PORT}:3000"
```

| Key | Default | What it does |
| --- | ------- | ------------ |
| `ensure` | `present` | `present`, `absent`, or a version pinning `docker-ce` and `docker-ce-cli` |
| `manage_service` | `true` | Start and enable docker and every instance, restart them on a change |
| `restart` | `false` | On a `daemon.json` change: `false` reloads docker, `true` restarts it and every instance with it |
| `purge` | `true` | Stop and remove a container or stack no layer declares, with its account |
| `config` | nftables backend, log rotation, `overlay2`, `live-restore`, no userland proxy | Rendered whole into `daemon.json`, keys sorted |
| `containers` | `{}` | `<name>: <container>`, see [Containers](#containers) |
| `compose.ensure` | `present` | `present`, `absent`, or a version pinning `docker-compose-plugin` |
| `compose.stacks` | `{}` | `<name>: <stack>`, see [Compose stacks](#compose-stacks) |

`package`, `cli_package`, `compose_package`, `extra_packages`,
`modules_extra`, `service`, `dockerd_binary`, `config_file`, `sysctl_file` and
`modules_load_file` come from the OS layer, `data/os/<family>/<release>.yaml`.
A container or stack name becomes a unit instance, a system account and the
directory `/opt/<name>` at once. So it matches `[a-z][a-z0-9_-]{0,31}`, is not
`root`, `docker` or `nobody`, and a container and a stack never share one.

## Containers

Each entry is `docker-container@<name>.service`, running `docker run --name
<name>` in the foreground under `Restart=always`. The entry gets a system
account and group of its own name, with `/opt/<name>` as its home: mode `750`,
and the unit's working directory.

| Key | Default | Becomes |
| --- | ------- | ------- |
| `ensure` | `present` | `absent` stops and disables the instance and removes its files, drop-ins and account |
| `image` | required | The image, one argument |
| `user` | none | `--user`, a name, `uid` or `uid:gid` |
| `env` | `{}` | `/opt/<name>/.env`, mode `600`, sorted, passed with `--env-file` |
| `ports` | `[]` | `-p` per item, verbatim |
| `mounts` | `[]` | `-v` per item, verbatim |
| `opts` | `{}` | `--key=value` sorted; `true` is a bare flag, `false` drops it, a list repeats it |
| `run_opts` | `[]` | Arguments after the image; a string is split like a shell would |
| `pull` | `true` | `docker pull` before every start |
| `recreate` | `true` | `--rm`; `false` keeps the stopped container for logs and `inspect` |
| `stop_timeout` | `30` | `docker stop --time` |
| `unit_dropin` | none | See [Overriding a unit](#overriding-a-unit) |

`opts` refuses what the unit or another key already passes: `name`, `rm`,
`user`, `env`, `env-file`, `publish`, `volume`, `restart`, `detach` and their
short forms.

The static unit carries no command of its own beyond `docker rm -f <name>`
before every start, so a container kept by `recreate: false` never blocks the
next one. The pull, the `docker run` and the `docker stop` are rendered into
the `run.conf` drop-in of the instance, quoted for systemd. A changed `.env`,
`run.conf` or drop-in restarts the instance.

The container `.env` is written unquoted: `docker run --env-file` keeps quotes
as part of the value.

## Compose stacks

Each entry is `docker-compose@<name>.service`, a oneshot working in
`/opt/<name>`, with the same account and home as a container. That directory
holds `docker-compose.yml` from `content` and `.env` from `env`, both mode
`600`. A stack has no `ports` or `mounts`: the document says it.

| Key | Default | What it does |
| --- | ------- | ------------ |
| `ensure` | `present` | `absent` runs `compose down`, then removes the directory, drop-ins and account |
| `content` | required | The compose document, verbatim; it must parse and carry `services` |
| `env` | `{}` | `.env`, sorted, values single-quoted so compose does not interpolate them |
| `recreate` | `false` | On a change: `false` reloads, `true` restarts |
| `unit_dropin` | none | See [Overriding a unit](#overriding-a-unit) |

Start and reload are both `compose up -d --remove-orphans`, which recreates
only the services whose definition changed. A restart is `compose down` and
then `compose up`, so every container and the stack's network are rebuilt.

## Overriding a unit

`files/docker-container@.service` and `files/docker-compose@.service` are
copied verbatim and carry `/usr/bin/docker` and `/opt` as literals. Moving
`dir` means editing both units too, and a test fails otherwise.

`unit_dropin` is rendered with jinja (`name`, `entry`, `node`) into
`<unit>.d/override.conf`. A changed or dropped drop-in restarts the instance:

```yaml
docker:
  compose:
    stacks:
      vpn-panel:
        unit_dropin: |
          [Unit]
          After=awg-quick@awg0.service
          Wants=awg-quick@awg0.service
        content: |
          services: ...
```

## The firewall

**A container is unreachable from outside until a rule says otherwise**, even
with a published port. The module brings four `forward` rules to `nftables`
through `data/nftables.yaml`, a port of puppet
`docker_distribution::nftables`:

| Order | Rule |
| ----- | ---- |
| 110 | `ct state established,related counter accept` |
| 111 | `iifname "docker0" oifname != "docker0" counter accept` |
| 112 | `iifname "br-*" oifname != "br-*" counter accept` |
| 113 | `iifname "br-*" oifname "br-*" counter accept` |

A published port is DNAT'ed, reaches `forward` as `ct state new`, matches none
of them and dies on `forward_drop` at 991. There is deliberately no
`oifname "docker0" accept`, and a test fails if one appears. A port reached
from the host itself still works, because local traffic never passes
`forward`.

The rules are data rather than code: suil merges every module's `data/` into
the node, so they reach `nftables` only on a node carrying `docker`.
`data/repos.yaml` adds `docker-ce-stable` the same way. An opening is a
`nftables.direct` entry at order 120 or above in a role or node layer:

```yaml
nftables:
  direct:
    docker_registry:
      rule_string: 'iifname != "docker0" oifname "docker0" ip saddr @lan tcp dport 5000 counter accept comment "registry"'
      chain:       forward
      order:       120
```

`requires.yaml` names `nftables`, so list `docker` after `base` in a role. A
role listing it earlier pulls `nftables` ahead of `ssh` and `accounts`.

## The engine on an nftables host

`firewall-backend: nftables` needs docker 29 or newer. That backend does not
enable forwarding, so the module sets `net.ipv4.ip_forward` in
`/etc/sysctl.d/90-docker.conf`. `iptables-nft` is installed by name, because
docker-ce requires `(iptables-nft or iptables)` and a third-party
`iptables-legacy` can win that `or`.

`userland-proxy: false` needs `br_netfilter`: dockerd refuses to start without
`/proc/sys/net/bridge/bridge-nf-call-iptables`. The module loads it and writes
`/etc/modules-load.d/br_netfilter.conf`. On EL it ships in
`kernel-modules-extra`, installed **pinned to the running kernel and before
docker-ce**: the bare name resolves to the newest build and drags a second,
half-installed kernel in.

## Validation and facts

`daemon.json` is judged by `dockerd --validate` on the host before it is
written. A host without `dockerd` is a clean one: there is nothing to check
with, and the file is written.

A changed `daemon.json` **reloads** docker. A restart is not survivable:
every instance unit `Requires=docker.service`, so systemd restarts them all,
and `live-restore` does not help a container whose `docker run` client loses
the daemon. A reload applies only the keys dockerd rereads on `SIGHUP` —
`debug`, `labels`, `live-restore`, `registry-mirrors`, `insecure-registries`,
`max-concurrent-*`, `runtimes`, `default-runtime`, `shutdown-timeout`,
`features`. The rest, `log-opts` and `bip` among them, wait for the next start
of dockerd: a reboot, a package off its pin, which always restarts, or a run
with `restart: true`.

The collector reports the installed versions, the digests of `daemon.json`,
both units and every declared entry's files and drop-in, whether
`br_netfilter` is loaded and forwarding is on, the state of docker and each
instance, and the undeclared directories. **It never calls the docker
client**: a wedged daemon would hang the collector with it.

It also reports `/etc/docker/containers` and `/etc/docker/compose`, where
entries lived before each got an account and `/opt/<name>`; a run removes
them.
