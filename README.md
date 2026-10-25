# suil-modules

Modules for [suil](https://github.com/oberon-systems/droch-shuil), the host
provisioner on top of [pyinfra](https://pyinfra.com). Each module is versioned
on its own, by a `<module>-<version>` tag.

## Use

Declare the modules in the `modules.yaml` of a suil workspace, pinned to a tag:

```yaml
repos:
  - repo:    https://github.com/oberon-systems/suil-modules
    version: <module>-<version>
    modules:
      - <module>
```

Then `suil install` clones them, and `suil autoupdate` moves `version` to the
newest tag.

## Development

```bash
make install
make shell
make lint
```

`make install` creates `.venv`, installs the tooling from `requirements.txt`
and the pre-commit hooks. Commits go through commitizen: `cz commit`.

## License

[MIT](LICENSE).
