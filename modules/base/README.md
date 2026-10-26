# base

The whole of the base configuration, as one name a role can ask for.

`base` has no code, no data and no facts. It is a `requires.yaml` and nothing
else, which is what lets `data/roles/<role>.yaml` say `modules: [base]` without
giving up per-module facts: the runner expands the list, and each of the seven
modules records its own `facts/<node>/<module>.yaml`.

## The order is load-bearing

The runner walks `requires` depth-first in list order, so this file *is* the
run order:

| Module | Why here |
| ------ | -------- |
| `hostname` | Everything downstream renders the host's own name |
| `selinux` | Before the packages it would otherwise label under a policy |
| `repos` | `packages` and every later module install from the repositories it declares |
| `packages` | Declares `requires: [repos]`, so the dependency is real and not only positional |
| `accounts` | `ssh` refuses to lock out an account that does not exist yet |
| `ssh` | Declares `requires: [accounts]`, so it runs after `accounts` although the list names it first |
| `nftables` | **Last.** `nftables-apply.sh` snapshots the whole live ruleset and diffs against that snapshot, so anything that programs tables of its own or creates an interface the ruleset names has to exist first |

A new module that touches the network goes *before* `nftables`, never after it.
