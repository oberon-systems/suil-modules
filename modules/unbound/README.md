# unbound

Installs the Unbound resolver, writes the whole of `unbound.conf`, and
optionally takes `/etc/resolv.conf` away from NetworkManager so the host asks
its own daemon first.

## Why the module exists

A caching resolver on a host answers an internal zone without a round trip,
and a host that serves other machines is the same module with a wider
`listen_addresses` and a wider `access_control`. There is no separate
"resolver role" — the difference between a client and a server here is two
lists.

## Config

| Key | Default | What it does |
| --- | ------- | ------------ |
| `manage_service` | `true` | Start and enable the daemon |
| `install_packages` | `true` | Install `package` |
| `config_file` | `/etc/unbound/unbound.conf` | Where the rendered file goes |
| `verbosity` | `1` | `verbosity` |
| `listen_addresses` | `127.0.0.1`, `::1` | One `interface:` line each |
| `access_control` | loopback only | `<netblock> <action>` per entry |
| `ip_freebind` | `true` | Bind an address that does not exist yet |
| `chroot` | `""` | `chroot`, empty disables it |
| `msg_cache_size` / `rrset_cache_size` | `2m` / `4m` | Cache sizes |
| `forward_zones` | `[]` | `{name, forward_addr}`; `name: "."` is the global forwarder |
| `local_zones` | `[]` | `{name, type, data}` |
| `host_address` | `""` | This host's address **for other nodes to look up** |
| `manage_resolv_conf` | `false` | Own `/etc/resolv.conf` |
| `resolv_conf` | `/etc/resolv.conf` | Path of that file |
| `resolv_nameservers` | `[]` | Written in order; site data, because a non-empty default would concatenate with it |
| `resolv_options` | `[]` | `options` line, empty writes none |

`package`, `service`, `checkconf_binary`, `config_group` and `nm_dropin` come
from the OS layer, `data/os/<family>/<release>.yaml`.

Validation runs on the control machine, before anything connects: a
`local-zone` type unbound does not know, an `access_control` entry that is not
`<netblock> <action>`, two `local_zones` on the same name — which is a start
failure unbound reports and nothing else would — and `manage_resolv_conf` with
an empty nameserver list, which writes a `resolv.conf` that resolves nothing.

`chroot` is empty **on purpose**: EL builds unbound with a compiled-in chroot,
and a chrooted daemon never reaches the `/run/systemd/notify` its `Type=notify`
unit waits on.

## The zone that assembles itself out of the inventory

`host_address` is the one key this host's own template never reads. It exists so
that *other* nodes can name it, through a `!LOOKUP` in their own data:

```yaml
# data/modules/unbound.yaml
local_zones:
  - name: example.com
    type: transparent
    data:
      - "static.example.com. A 192.0.2.9"       # a literal record
      - !LOOKUP                                  # and every node in one list
        field: unbound.host_address
        format: "{node}. A {value}"
```

A node declaring an address gets an A record; a node without one contributes
nothing. The record name is the node key, which is the FQDN. `!LOOKUP` is a
runner-wide mechanism, not a feature of this module — suil's documentation
describes it.

## Owning /etc/resolv.conf

Writing the file is the smaller half. On EL, NetworkManager owns it and
rewrites it on the next network event, so the module drops a `dns=none` snippet
into `nm_dropin`, reloads NetworkManager — it lets go only once it has reloaded,
which is why the reload is its own operation before the write — removes the file
if it is a symlink, and only then writes it.

The second nameserver covers a **dead** unbound: the resolver moves on after a
timeout, and `resolv_options: ["timeout:1"]` makes that quick. It does **not**
cover a live unbound answering SERVFAIL — that is a valid answer and nothing
falls back from it.

## Facts

`config` is the digest of the live file, `service` its running and enabled
state, `resolv` the digest of `resolv.conf` when the module owns it, and
`checked` is what makes the pair honest:

`unbound-checkconf` ships **in the package this module installs**. A host that
has never had unbound is a clean one: there is nothing to check with, and the
file is written. The collector runs
`unbound-checkconf` against the live file and reports `true`, `false`, or
`null` when the binary is still missing — and `expected()` demands `true`. A
host carrying a configuration that does not check out therefore keeps a diff
open until it does, instead of the check silently never happening.
