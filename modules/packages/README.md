# packages

The base package set, installed in one transaction.

## Config

```yaml
packages:
  list:
    tmux:
      ensure: present
    telnet:
      ensure: absent
    net-tools:
      ensure: 2.10-8.el10
```

`ensure` is `present`, `absent`, or a version, which is appended to the name as
`<name>-<version>` for dnf. An entry with nothing to say may be written
`tmux:` — YAML reads that as null, and the model treats it as `present`.

The two lists are handed to `dnf.packages` **whole**, one call each way. One
call per entry would cost one dnf transaction per package.

## There is no per-distribution name override

The old ansible role carried `vim: {rocky: vim-enhanced}`, because one site
list had to name a package on two distributions. It is not needed here: the
site list lives in `data/os/<family>/<release>.yaml`, which is already the
layer that knows what the OS calls things. On EL that list simply says
`vim-enhanced`.

## Facts

The state of exactly the managed names, in config shape, so the diff compares
like with like. A pinned entry reports its installed version, so a drifted pin
shows up; an unpinned one reports `present` or `absent`.
