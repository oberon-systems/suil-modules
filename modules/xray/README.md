# xray

Installs [Xray](https://github.com/XTLS/Xray-core) from its GitHub release,
writes `config.json` without touching its clients, and runs it as
`xray.service`. The usual inbound is VLESS/Reality on TCP/443, which gets
through where unclassified UDP is shaped.

- [Why the module exists](#why-the-module-exists)
- [Config](#config)
- [Install](#install)
- [The clients belong to the agent](#the-clients-belong-to-the-agent)
- [Facts](#facts)

## Why the module exists

The awg-keeper agent manages Xray users by calling the binary - `xray api adu`
and `rmu` - and then rewriting `config.json`, because the api changes only the
running process. The binary has to sit beside the agent, and the agent's unit
is `ProtectSystem=strict` with no docker socket, so Xray runs on the host
rather than in a container. The module is a port of the retired ansible
`roles/xray`.

## Config

```yaml
xray:
  version: v26.3.27
  sha256:  <64 hex>

  inbounds:
    - tag:      reality
      listen:   192.0.2.1
      port:     443
      protocol: vless
      settings:
        clients:    []
        decryption: none
      streamSettings:
        network:  tcp
        security: reality
        realitySettings:
          dest:        "www.example.com:443"
          serverNames: ["www.example.com"]
          shortIds:    ["0123abcd"]

  reality_private_key: !ENC[...]
```

| Key | Default | What it does |
| --- | ------- | ------------ |
| `version` | `v26.3.27` | The upstream release tag |
| `sha256` | `""` | Digest of `asset`; empty warns and installs unpinned |
| `manage_service` | `true` | Start and enable `xray.service`, restart it on a change |
| `user`, `group` | `xray` | The service account, created as system account and group |
| `log_level` | `warning` | `log.loglevel` |
| `api_inbound` | `127.0.0.1:8085`, tag `api` | The inbound the agent drives; its port is the agent's `xray_api` |
| `inbounds` | `[]` | The inbounds that carry traffic |
| `reality_private_key` | `""` | Folded into every inbound with `security: reality` |
| `base_config` | api, stats, policy, `freedom` and `blackhole` outbounds, routing | Everything in `config.json` but `log` and `inbounds` |

Validation refuses a tag that is missing or used twice - the agent addresses an
inbound by it - and a Reality inbound without `dest`, `serverNames`, `shortIds`
or a private key. All four faults share one symptom: the inbound starts and
rejects every client. The key pair comes from `xray x25519`.

Clients reach the internet and nothing else: a routing rule sends loopback,
where the api that adds users listens, and the private and reserved ranges the
host's own services sit in to the `blackhole` outbound. The ranges are written
out rather than `geoip:private`, because `xray run -test` on the control machine
has no `geoip.dat` beside the file it tests. A node adds its own public address
the same way, in its data.
The policy counts traffic and online addresses per user, which the Panel
shows.

## Install

pyinfra's `unarchive` and `copy` check their paths while the run is planned, so
an archive downloaded by the same run could never be unpacked on the host. The
release is therefore downloaded and checked against `sha256` on the control
machine, and `xray`, `geoip.dat` and `geosite.dat` are put onto the host. It
happens only when `stamp_file` holds a version other than `version`; a changed
version restarts the service.

## The clients belong to the agent

The module owns `config.json`; the agent owns `settings.clients` in it. Drift is
the digest of the file with every inbound's `clients` removed, so a user the
agent adds is not drift, and a changed inbound, route or log level is. A write
stages the rendered file as `config.json.suil`, carries the live file's
`clients` over per inbound tag, and replaces `config.json` with the result, so
users survive a run. A tag that is new has no clients to carry.

Every write is judged with `xray run -test` before it is staged. A run that
installs Xray does it on the control machine with the release binary, any other
run with the host's own. A rejection fails the run with Xray's message, rather
than leaving the service to restart in a loop. The directory is `root:xray`
with mode `2770`. The setgid bit is load-bearing: the agent replaces the file
with a temporary one of its own and never chowns it, so only the directory's
group lets `xray` read the result. The agent reaches the directory through
`SupplementaryGroups=xray` in its drop-in, see `modules/awg-keeper`.

## Facts

The collector reports the digest of `config.json` without its clients, whether
the live file passes `xray run -test`, and the state of the service. The runner
records the digests of `stamp_file` and the unit.
