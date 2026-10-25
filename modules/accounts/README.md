# accounts

Users, their `authorized_keys`, and per-user `sudoers.d` drop-ins.

## Config

```yaml
accounts:
  users:
    deploy:
      groups:   [wheel, sudo]
      auth_key: "ssh-ed25519 AAAA... deploy"
      sudo:     "deploy ALL=(ALL) NOPASSWD: ALL"
    cloud-user:
      ensure: absent
```

| Key | Default | What it does |
| --- | ------- | ------------ |
| `users` | `{}` | The account list, keyed by name |
| `groups_append` | `true` | Add to the listed groups instead of making the list authoritative |
| `manage_sudo` | `true` | Write `/etc/sudoers.d/<name>` for entries carrying `sudo` |
| `keys_exclusive` | `false` | Make this module's key the only key on the account |
| `visudo` | `/usr/sbin/visudo` | Path used to check a drop-in before it lands |

Per account: `ensure`, `shell`, `system`, `groups`, `append`, `password`,
`auth_key`, `keys_exclusive`, `sudo`.

A group the distribution does not have is **skipped, not an error** — `wheel`
exists on EL and `sudo` on Debian, and one site list has to work on both.

## Validation happens on the control machine

`ensure` is checked to be `present` or `absent`, `extra='forbid'` rejects a key
the model does not know, and that is all. Neither the password nor the
authorized key has a shape rule, and there is no lockout guard: the first run
against a cloud image connects **as** one of the vendor logins it is there to
remove, so a guard on the connecting account would refuse exactly the run that
matters.

A sudoers drop-in is staged on the target and put through `visudo -cf` **before**
it is declared into place. A rejected drop-in fails the run and never reaches
`/etc/sudoers.d/`.

## The account the run connects as is never removed

An `ensure: absent` whose name equals `suil.ssh_user` is skipped, with a warning
naming it, and left out of `expected()` so it is not reported as drift either.
`userdel` refuses an account that owns a session and the run is that session, so
queuing the removal only ever fails the whole deployment.

This is the normal shape of a first run against a cloud image: connect as
`cloud-user`, let the run create `deploy`, point `ssh_user` at `deploy`, and the
next run removes `cloud-user` from outside.

## What removal does not do

`ensure: absent` is a plain `userdel`. Two things the ansible role did are
deliberately not reproduced here:

* **No `pkill -KILL -u`.** `userdel` refuses while the account still owns a
  process, and a vendor login left over from a cloud image is exactly the one
  still holding a session. Such an account survives the run, and the next run
  tries again.
* **No `userdel -r`.** The home directory and the mail spool stay.

Both would need a shell command of this module's own, and they are left out
on purpose. Reproducing them is a decision to take deliberately, not by
accident. The facts report the account as `present`, so the gap is
visible rather than silent.

## Facts

Per managed name: `ensure`, `shell`, `groups`, and `sha256:` digests of the
authorized key and of the sudoers drop-in. No secret is written — the digest is
enough to notice a change and not enough to leak one.
