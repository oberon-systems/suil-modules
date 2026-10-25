# suil-modules

Base modules for [suil](https://github.com/oberon-systems/droch-shuil), the
host provisioner on top of [pyinfra](https://pyinfra.com). Each module is
versioned on its own and documented in its own README.

## Install

Declare the modules in the `modules.yaml` of a suil workspace, each pinned to
its version:

```yaml
repos:
  - repo:    https://github.com/oberon-systems/suil-modules/releases/download/modules
    modules:
      <module>: <version>
```

Then lay them into `modules/` of the workspace:

```bash
suil install
```

`suil autoupdate` moves every module to its newest version; run
`suil install` after it.

## Remove

Drop the module from `modules.yaml`, delete its directory, and check the
workspace:

```bash
rm -r modules/<module>
suil validate
```

`suil validate` fails while a role or another module still requires it.

## License

[MIT](LICENSE).
