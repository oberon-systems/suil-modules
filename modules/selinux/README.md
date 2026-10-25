# selinux

Writes `/etc/selinux/config` and moves the running kernel towards the same
mode, so the host does not wait for a reboot to stop denying.

## Config

| Key | Default | What it does |
| --- | ------- | ------------ |
| `manage` | `true` | Manage SELinux at all; `false` makes the module a no-op |
| `mode` | `enforcing` | `enforcing`, `permissive` or `disabled` |
| `policy` | `targeted` | `SELINUXTYPE` in the file |
| `config_file` | `/etc/selinux/config` | The file written |
| `enforce_file` | `/sys/fs/selinux/enforce` | Where the collector reads the live mode |

The default is what the distribution ships, so a host that leaves `mode`
alone sees no change. A host that runs nothing written against a policy sets
it in its own data:

```yaml
selinux:
  mode: disabled
```

## The live mode

The file decides the next boot. For the running kernel the module calls
`setenforce`: `1` for `enforcing`, `0` for `permissive` and `disabled`. A
kernel cannot drop to disabled without a reboot, so `permissive` is accepted
as converged for `disabled`, and a kernel already booted disabled is left
alone.

## Facts

`mode`, the live mode: `enforcing` or `permissive` from `enforce_file`, and
`disabled` when there is no selinuxfs at all. The digest of `config_file` is
recorded by the runner from `files()`.
