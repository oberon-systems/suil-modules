# nginx

Installs [nginx](https://nginx.org/) from the nginx.org stable repository, writes
the whole of `nginx.conf`, always delivers a static default server with a
throwaway certificate, and writes one `conf.d` file per declared server.

- [Why the module exists](#why-the-module-exists)
- [Config](#config)
- [SSL is ready in every server](#ssl-is-ready-in-every-server)
- [The default server](#the-default-server)
- [Validation and facts](#validation-and-facts)

## Why the module exists

A host that fronts a web service needs nginx with a complete, checked
config. The module is a port of the puppet `nginx` module (`nginx::config`,
`nginx::default`) without its site-specific branches: no fpm status, no ELB
health checks, no certbot. Certificates for named servers come later; until
then a server brings its own paths.

## Config

```yaml
nginx:
  ensure: 1.30.4

  settings:
    sendfile: 'on'
    gzip_types: [text/css, application/json]

  servers:
    me.example.com: |
      server {
          listen 443 ssl;
          server_name me.example.com;
          ...
      }
```

| Key | Default | What it does |
| --- | ------- | ------------ |
| `ensure` | `present` | `present`, `absent`, or a version; a version pins `nginx-<version>`, any release |
| `manage_service` | `true` | Start and enable nginx, reload it on a changed file |
| `purge` | `true` | Remove every `conf.d/*.conf` no layer declares |
| `worker_connections` | `1024` | `events { worker_connections }` |
| `ssl_key_length` | `2048` | RSA bits of the default server key: 2048, 3072 or 4096 |
| `set_default` | `yes` | Deliver the default server and its certificate |
| `resolver` | `127.0.0.1` | The `resolver` directive's arguments, for OCSP stapling |
| `settings` | `{}` | `http {}` directives, sorted; a list repeats the directive once per item |
| `servers` | `{}` | `<name>: <text>` becomes `conf.d/<name>.conf` verbatim; an empty value removes the file |

`package`, `service`, `binary`, `user`, `config_dir`, `confd_dir`, `cert_dir`,
`log_dir`, `pid_file` and `ca_bundle` come from the OS layer,
`data/os/<family>/<release>.yaml`.

`settings` refuses any directive `nginx.conf` already renders (`user`,
`log_format`, the ssl block and the rest of `FIXED` in `code/config.py`): a
second copy in the same context is a start failure. A server name of `default`,
or one that is not a plain file name, is refused too.

## SSL is ready in every server

The ssl block sits in `http {}` and is not data, so every server inherits it
and only decides whether it speaks TLS: `listen ... ssl` plus its own
`ssl_certificate` and `ssl_certificate_key`.

```text
ssl_protocols TLSv1.3;
ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;
ssl_prefer_server_ciphers off;
ssl_stapling on;
ssl_stapling_verify on;
ssl_trusted_certificate <ca_bundle>;
resolver <resolver>;
```

`ssl_trusted_certificate` points at the system CA bundle, because a path to a
missing file fails `nginx -t` and there are no real chains yet. `resolver`
defaults to a caching resolver on loopback, such as the `unbound` module; a
host without one sets its own. On the self-signed default certificate
stapling only logs that it found no issuer.

## The default server

`files/default.conf` is a static file, copied verbatim to `conf.d/default.conf`.
It always listens on `80` and `443` as `default_server` and answers every name
no server claims: plain http gets `302 https://$host$request_uri`, https gets an
empty `200`. It carries `/etc/nginx/cert` and `/var/log/nginx` as literals, so
moving `cert_dir` or `log_dir` in the OS layer means editing the file too - a
test fails otherwise.

`set_default: no` drops it: no `default.conf`, no throwaway certificate, and the
file is removed from a host that had one. Every listen then lives in the server
texts, which is what a host sharing `:443` with another daemon needs.

Its key and certificate replace the puppet `make_junk_key`/`make_junk_cert`
execs. The module cannot run `openssl` on the host, so `code/certificate.py`
generates them on the control machine: RSA of `ssl_key_length` bits,
self-signed for 3650 days, a random subject ending in `.example.com`, the port
of `generate_certificate_info`. They are put only when either file is missing or
the collector reports a different key size, so a run does not rotate them.
Neither ever enters the config or the facts.

## Validation and facts

Before anything is written, the module renders a candidate `nginx.conf` with
`default.conf` and every server inlined in place of the `conf.d` include, and
lets the host judge it with `nginx -t -q -c`. A host without the binary or the
default certificate is a clean one: there is nothing to check with, and the
files are written.

The collector reports the installed version, the digests of
`nginx.conf`, `default.conf` and each declared server, the undeclared files in
`conf.d`, the key size and the certificate's presence, and `checked`: `nginx -t`
against the live tree, `null` without a binary. `expected()` demands `true`, so
a configuration that does not check out keeps a diff open until it does.

A changed file reloads nginx, and a package that was missing or off its pin
restarts it.
