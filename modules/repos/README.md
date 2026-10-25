# repos

Declares the package repositories a host installs from, delivers the gpg keys
they are signed with, and serves a private S3-compatible bucket to `dnf` over a
loopback port.

## Why the module exists

Without it a host installs from whatever the distribution shipped: no EPEL, and
no way at all to reach a repository published into a **private**
S3-compatible bucket. It runs before `packages` —
`modules/packages/requires.yaml` names it — because the package set is
installed out of the repositories it writes.

## Config

| Key | Default | What it does |
| --- | ------- | ------------ |
| `manage` | `true` | Do anything at all |
| `purge` | `false` | Remove `.repo` files no layer declares |
| `purge_keep` | `[]` | Globs a purge leaves alone; the stock list is an OS fact |
| `keys` | `{}` | gpg public keys written into `gpg_dir` |
| `list` | `{}` | The repositories themselves |
| `stores` | `{}` | S3-compatible buckets, one loopback front each |
| `store_user` | none | The account the fronts run as; needed once a store is declared |
| `unit_format` | none | The fronts' unit name, `{store}` is the store's name; needed unless every store sets `unit` |
| `store_config_dir` | `/etc/rclone` | Where their credentials live |

`repos_dir`, `gpg_dir`, `rclone_package` and `rclone_binary` come from the OS
layer, `data/os/<family>/<release>.yaml`.

A repository takes **exactly one** source:

```yaml
repos:
  list:
    epel:
      metalink: https://mirrors.fedoraproject.org/metalink?repo=epel-$releasever&arch=$basearch
      gpgkey:   https://dl.fedoraproject.org/pub/epel/RPM-GPG-KEY-EPEL-$releasever

    rocky-mirror:
      mirrorlist: https://mirrors.example.net/rocky?arch=$basearch

    local:
      baseurl:  file:///srv/repo/x86_64
      gpgcheck: false

    docker-ce:
      file: {url: https://download.docker.com/linux/centos/docker-ce.repo}

    example:
      store:  repo            # baseurl is built from the store below
      path:   rpm/rocky/10/x86_64
      gpgkey: file:///etc/pki/rpm-gpg/RPM-GPG-KEY-example
```

`file:` is the ready-made `.repo` — `url:` fetches one, `src:` takes one out of
`modules/repos/files/`, `content:` carries it inline. A file fetched by URL is
downloaded **once**, because that is all `files.download` promises; the facts
carry its digest, so a file somebody changed is at least visible.

Modelled keys are `description` (written as `name=`), `baseurl`, `mirrorlist`,
`metalink`, `enabled`, `gpgcheck`, `repo_gpgcheck`, `gpgkey`, `priority`,
`module_hotfixes`, `exclude`, `includepkgs`, `skip_if_unavailable`,
`sslverify`, `cost`, `username` and `password`. Anything else `dnf.conf(5)`
knows goes through `options:` as it stands. `$releasever` and `$basearch` are
dnf's own variables; nothing here expands them.

`baseurl`, `gpgkey`, `exclude` and `includepkgs` take a list or a single
string.

Validation happens on the control machine, before anything connects: a
repository with no source or two, a repoid dnf would not accept, a `store:`
nothing declares, `gpgcheck` with no `gpgkey` — which fails the first install
on an unknown key — and a `gpgkey` pointing into `gpg_dir` at a file no `keys:`
entry writes, which is the same dangling-reference class caught in data rather
than by dnf.

`pyinfra`'s own `dnf.repo` is deliberately not used: it knows `baseurl` and
nothing else — no mirrorlist, no metalink, no priority, no list of keys.

## Reading a private S3 bucket

`dnf5` cannot sign a request, and there is no s3 plugin for it. So the bucket is
not reached by dnf at all: a `rclone serve http --read-only` unit holds the
credentials, listens on a loopback port, and the repository's `baseurl` points
at that port.

```yaml
repos:
  store_user:  repo-front
  unit_format: repo-{store}-front

  stores:
    repo:
      provider:          Cloudflare
      endpoint:          https://<account>.r2.cloudflarestorage.com
      bucket:            repo
      region:            auto
      access_key_id:     !ENC[...]
      secret_access_key: !ENC[...]
      listen:            127.0.0.1:8083
```

The front is idle until dnf asks for something: it neither polls nor mirrors,
and a `suil` run never touches the bucket either — it writes files and checks
the unit. Nothing is copied to disk, so the repository does not grow on the
host.

The unit is `unit_format` with the store's name, or the store's own `unit`.
It runs as `store_user` rather than root, because the credentials sit in the
memory of a daemon that is up around the clock, and carries
`ProtectSystem=strict`. `rclone` keeps its cache under `$HOME`, which that
leaves nowhere to write, so `CacheDirectory=` is what opens one path and
`--cache-dir` is what points rclone at it.

## The order inside deploy is load-bearing

1. the gpg keys;
2. every repository **without** a store — because `rclone` is installed out of
   EPEL, and EPEL is one of them;
3. the stores: package, account, credentials, unit, service;
4. every repository **with** a store.

Writing step 4 before step 3 breaks step 3: `dnf install rclone` would go to a
loopback port nothing is listening on yet and fail the transaction. The second
layer of the same guard is `skip_if_unavailable`, which defaults to `1` on a
store-backed repository and to dnf's own default everywhere else.

## Owning /etc/yum.repos.d

The module writes `<repoid>.repo` for what it declares, removes what it
declares `ensure: absent`, and touches nothing else. `purge: true` widens that
to the whole directory: every `.repo` no layer declares and no `purge_keep`
glob protects is removed. On Rocky the OS layer keeps `rocky*.repo`, so a purge
does not take the distribution's own repositories with it — anything else the
host is meant to keep has to be declared or listed.

## Facts

Per key and per repository, the digest of the live file and whether it is
there; per store, the digests of the credentials and of the unit, its running
and enabled state, and `listening` — a TCP connect to the front's own address,
which proves the daemon is answering without a single request to the bucket.
`unmanaged` lists the `.repo` files a purge would remove, and is `null` when
`purge` is off.

A repository delivered as a verbatim file reports no digest: the control
machine cannot predict what a URL will hand over, and a fact nothing can be
compared against would make the module run on every pass.
