# hostname

Sets the host's fully qualified domain name and stops cloud-init from putting
the provider's name back.

## Why the module exists

The node key in `data/nodes/` is the host's FQDN, and it is what the runner
hands ssh when nothing sets `ssh_host`. The name a cloud image boots with is
not usable there: OpenStack Nova keeps `instance.hostname` as a single DNS
label and `sanitize_hostname` replaces every dot with a dash, so an instance
named `host-01.example.com` boots as `host-01-example-com`, which dnsmasq and
every other resolver refuse.

`manage: false` turns the module into a no-op for a host that has no FQDN.

## Config

| Key | Default | What it does |
| --- | ------- | ------------ |
| `manage` | `true` | Set the name at all |
| `fqdn` | the node key | The name to set |
| `manage_cloud_init` | `true` | Write the `preserve_hostname` drop-in |
| `cloud_init_file` | `/etc/cloud/cloud.cfg.d/99-hostname.cfg` | Where that drop-in goes |

Validation refuses a single-label `fqdn` **on purpose**: accepting one would
make the module a no-op on exactly the hosts that need it. It runs on the
control machine, before anything connects.

The drop-in is written only when `/etc/cloud/cloud.cfg.d` exists, so a host
installed without cloud-init gets the name and nothing else.

## Facts

`fqdn` as the host resolves it, and `preserve_hostname`. A host with no
cloud-init reports `preserve_hostname: true` — there is nothing to pin, and
saying otherwise would open a diff that can never be closed.
