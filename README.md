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
make docs
```

`make install` creates `.venv`, installs the tooling from `requirements.txt`
and the pre-commit hooks. Commits go through commitizen: `cz commit`.

## Releases

Every module has its own `modules/<name>/.cz.yaml`, written from
`cz-module.yaml` by `make module MODULE=<name>`, and its own
`CHANGELOG.md`. `cz bump`, run in `modules/<name>`, counts only the commits
under it, writes its changelog and tags `<name>-<version>`; a new module
starts at `0.0.0`, so its first bump is `0.1.0`. A pushed tag is the
release.

The documentation is the README of the repository and of every module,
published to GitHub Pages on every push to `main` that changes one of them.

## License

[MIT](LICENSE).
