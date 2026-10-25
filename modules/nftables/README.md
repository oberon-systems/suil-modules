# nftables

Renders the whole firewall ruleset, checks it with `nft -c`, and hands it to a
unit of its own.

## The data model

Ported from the puppet module of the same name: a table skeleton with an order
window per table, and rules that render inside that window. `order` is relative
to the table's `min_order`, so a rule keeps its place whatever table it moves
to.

| Key | What it holds |
| --- | ------------- |
| `tables` | The skeleton: family, order window and base chains per table |
| `baseline` | The rules no layer may drop, see below |
| `sets` | `name -> {elems, table, set_type, flags, order}` |
| `chains` | Extra chains: `[{name, table}]` |
| `rules` | `name -> {source, proto, port, chain, order, comment}` |
| `nat` | `name -> {nat_type, from, to, proto, port, interface, order, comment}` |
| `direct` | `name -> {rule_string, table, chain, order}` — the escape hatch |

`source` is an address, a CIDR, the name of a set, **or a DNS name**. A DNS
name becomes a set of its own, rendered empty, carrying the name as its nft
comment; `nftables-resolve.sh` reads that comment back on the host and fills
the set from a timer, so a changed record takes effect without a run of this
module. The `add set ... comment "<name>"` line is therefore a wire format —
changing how it is written breaks the resolver.

Without `chain`, a `direct` entry is emitted verbatim.

## The baseline is checked, not protected

In the ansible role the baseline lived in `vars/`, which host data could not
reach. Here it is the module's `data/`, the bottom layer, which anything can
override. The compensation is in `code/config.py`: the model refuses a config
in which `established`, `loopback`, `icmpv6`, `input_drop` or `forward_drop`
has gone missing or changed chain or order. Losing the trailing drops is losing
the firewall, and it fails on the control machine rather than on the host.

## Everything else the model rejects

The `fail()` cases of the puppet module, as validation that runs before
anything connects: a rule naming a table that does not exist, an order outside
its table's window, a protocol this module cannot build a rule for, a port
without `tcp` or `udp`, a `chain` other than `input` or `forward`, a `nat_type`
other than `SNAT`/`DNAT`, a `to` that is not a literal address, and two DNS
sources that collapse to the same nft set name.

The rendered ruleset is then staged on the target and put through
`nft -c -f`, which parses it against the running kernel without committing. A
rejected ruleset fails the run and never reaches `rules_file`
(`/etc/nftables/suil.nft` by default).

## Units

Three, all rendered from `templates/`:

* `nftables-suil.service` — oneshot, `RemainAfterExit`, `Before=network-pre.target`.
  `ExecStart` is `nftables-apply.sh`, which snapshots the live ruleset, commits,
  and rolls back if the commit is rejected after passing the check.
* `nftables-suil-resolve.service` and `.timer` — the DNS set refresh.

`nftables.unit` and `nftables.rules_file` rename them through data; the
templates keep their default names and render whatever unit is configured.

The distribution's own `nftables.service` is **disabled but never stopped**: its
`ExecStop` is `nft flush ruleset`, which would wipe the live firewall mid-run.
Conflicting firewalls (`firewalld`, `iptables`, `ip6tables`) are stopped,
disabled, and masked — masking is a symlink to `/dev/null`, which is what
`systemctl mask` writes, because `systemd.service` has no flag for it.

## There is no lockout guard

A host that is off the VPN loses access on the first run. That was true of the
ansible role and is true here: site policy allows ssh from `vpn_mgmt` only.
`nft -c` catches a malformed ruleset, not a correct ruleset that cuts off the
session running it. Keep a second session open.

## Where the ruleset is built

`code/ruleset.py`, in python. The ansible role assembled it in jinja with
`regex_replace` and `combine`, which plain jinja2 does not have and which was
never really template logic. `suil/tests` asserts on the output.

## Facts

`sha256` of the installed ruleset, and whether the unit is running and enabled.
