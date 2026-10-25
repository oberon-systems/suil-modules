# amneziawg

Installs [AmneziaWG](https://github.com/amnezia-vpn/amneziawg-tools) from a
repository declared through the `repos` module, writes one configuration file
per interface and keeps each interface up as an instance of the `awg-quick@`
unit. It is the gateway side of a VPN: the network its peers reach through it.

- [Why the module exists](#why-the-module-exists)
- [Config](#config)
- [Keys](#keys)
- [Firewall and routing](#firewall-and-routing)
- [Facts](#facts)

## Why the module exists

Plain WireGuard is recognised by its UDP signature. AmneziaWG hides the
handshake behind junk packets and randomised headers, and the `obfuscation`
profile is what switches that on - an empty profile is plain WireGuard again.
AmneziaWG pushes nothing to a client: a route exists because the client
profile's `AllowedIPs` names it, and a resolver because the profile carries
`DNS =`. Building those profiles is not this module's job.

The packages are `amneziawg-tools` and `amneziawg-go`, served from a repository
the `repos` module declares, which is why `requires.yaml` names it. `amneziawg-go` is
the userspace data path `awg-quick` falls back to when no kernel module is
loaded. The module writes no unit: `amneziawg-tools` ships `awg-quick@.service`
with `/usr/bin/awg-quick` as a literal, and `awg-quick` reads
`<config_dir>/<iface>.conf`, so `config_dir` cannot move on its own.

## Config

| Key | Default | What it does |
| --- | ------- | ------------ |
| `manage_service` | `true` | Start, enable and restart `awg-quick@<iface>` |
| `manage_ip_forward` | `true` | `net.ipv4.ip_forward = 1`, persisted in `sysctl_file` |
| `install_packages` | `true` | Install `packages` |
| `config_dir` | `/etc/amnezia/amneziawg` | Where `<iface>.conf` goes |
| `awg_binary` | `/usr/bin/awg` | What the collector asks |
| `unit_prefix` | `awg-quick` | The template unit an interface is an instance of |
| `sysctl_file` | `/etc/sysctl.d/90-amneziawg.conf` | Where ip forwarding persists |
| `obfuscation` | `{}` | `Jc`, `Jmin`, `Jmax`, `S1`-`S4`, `H1`-`H4`, ... written into `[Interface]` |
| `interfaces` | `{}` | name -> interface, see below |
| `packages` | from the OS layer | name -> `{ensure}`, `present`, `absent` or a version |

`packages` comes from the OS layer, `data/os/<family>/<release>.yaml`, names and
versions both: the dist tag in `3.1.20260812-1.el10` is as much an OS fact as the
name is. Every package here is **pinned** rather than `present`, because dnf
never upgrades a package it was only told to install. An upgrade is a changed
version in that file, and the run then restarts the interfaces onto the new
binary - the module compares the pin against what rpm reports, not merely whether
the package is there.

An interface is `{ensure, enabled, address, listen_port, mtu, fwmark,
private_key, public_key, peers, obfuscation}`, and a peer is `{public_key, allowed_ips,
endpoint, keepalive, preshared_key}`. What every gateway shares - the
obfuscation profile, the listen port, the MTU - lives in
`data/modules/amneziawg.yaml`. The address and the peers live in
`data/nodes/<node>.yaml`, because each gateway owns its own range - one `/24`
such as `192.168.201.0/24` out of a shared aggregate, say - and two gateways
sharing an address would hand it to two people.
An interface's own `obfuscation` is merged over the module-wide one, so one
interface can move to another profile while the rest keep theirs.

```yaml
amneziawg:
  interfaces:
    awg0:
      address:     192.168.201.1/24
      public_key:  <gateway public key>
      private_key: !ENC[...]
      peers:
        alice:
          public_key:  <peer public key>
          allowed_ips: [192.168.201.10/32]
```

Validation runs on the control machine, before anything connects. It refuses
an interface name that is not a valid `IFNAMSIZ` name, a present interface
without an address carrying a prefix, a port or a key, two interfaces on one
port, and two peers on one key. Each interface's merged obfuscation profile may
only hold the keys `src/config.c` parses - `J1`-`J3` and `Itime` are not among
them. The AmneziaWG 3.1 rules are checked too:

- `H1`-`H4` come all four or not at all, each a number or an `a-b` range above 4,
  and the four do not overlap;
- the timers and `ContentPaddingAddition` are a number or an `a-b` range within
  uint16, and `RandomTrailers`/`DisableCookies` are `on` or `off`;
- `S1 + 56` differs from `S2`, and `Jmin` is not above `Jmax`;
- `HeaderProtectionKey` is 32 bytes of base64 and needs `S1`-`S4` of 12 and more;
- `I1`-`I5` carry no `<c>` tag, which amneziawg-go refuses.

`ensure: absent` stops and disables the unit and removes the file.

### Peers owned by awg-keeper

`peers_external: true` hands an interface's peers to the awg-keeper agent, and
`peers` must then stay empty. The agent's `persist()` writes `awg showconf` over
`<iface>.conf` after every peer change. `Address` and `MTU` are awg-quick keys
that never reach the device, so the rewritten file has neither. For such an
interface the module:

- writes `<iface>.conf` only when it is missing, so the agent's peers survive a
  run. Changing `listen_port` therefore means deleting the file by hand. The
  obfuscation profile here is only the first one: after that the Panel owns it,
  and the agent applies it live and writes it into the file's `[Interface]`;
- writes `awg-quick@<iface>.service.d/override.conf` under `unit_dir`, holding
  `ExecStartPost=-<ip_binary> address replace <address> dev <iface>`, plus
  `link set mtu` when `mtu` is set. `replace` is idempotent and the `-` keeps a
  failure from failing the unit;
- leaves the file digest and the peer list out of the facts and compares the
  drop-in digest instead.

Turning `peers_external` off removes the drop-in again.

## Keys

One private key per gateway, as an `!ENC` value in the node's data. A key shared
between gateways would give up the whole VPN with any one of them, and revoking
it would force every profile to be reissued. Generate one with plain
`wg genkey`: the keys are ordinary Curve25519.

The public half is derived from the private key on the control machine. When the
node also declares `public_key` - the key every issued profile names - a private
key that does not match it fails validation instead of restarting the tunnel
with the wrong identity. The run's own ssh may travel through that tunnel.

A peer carrying the gateway's own key is refused too, whether `public_key` is
declared or not. `awg` accepts such a peer and drops it without a word, and
every symptom downstream points somewhere else.

## Firewall and routing

The `nftables` rules a gateway needs fit in `data/modules/amneziawg.yaml`,
because that layer is merged into the whole node and so travels with the
module. For an interface `awg0` in front of a set `lan`:

| Rule | Chain | Order | What it does |
| ---- | ----- | ----- | ------------ |
| `awg_listen` | input | 140 | udp/51820 from anywhere |
| `awg_no_peer_to_peer` | forward | 195 | `awg0` to `awg0` is dropped |
| `awg_forward_established` | forward | 200 | Replies |
| `awg_to_lan` | forward | 220 | `awg0` into `@lan` |

The peer-to-peer drop sits ahead of the established accept on purpose. When
the VPN range lies inside the network it leads into - `192.168.200.0/22` inside
`192.168.0.0/16` - a profile routing that network routes every other peer into
the tunnel as well.

There is no masquerade. SNAT would hide each peer behind the gateway address,
and a host behind it could no longer tell one source from another. A host on
that network therefore needs a route back to `192.168.200.0/22` via the
gateway, which is routing work and not this module's.

## Facts

Per interface: `config` is the digest of the live file, `public_key` and `peers`
are what the running device reports, and `service` is the unit's running and
enabled state. `packages` reports the version rpm holds for a pinned entry, and
`present` or `absent` for one that names no version; `ip_forward` reads `/proc`. The collector asks `awg show <iface> public-key` and
`awg show <iface> peers`, one field at a time, and never `dump` or `showconf`:
both print the private key.

An interface restarts when its file changed, when a package was missing or at a
version other than its pin before the run - the running daemon is then a binary
rpm has just replaced - or when
the live device reports peers or a key its file does not declare. A device that
is down is only started. `--force` alone restarts nothing.
