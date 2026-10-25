# suil-modules

Modules for [suil](https://github.com/oberon-systems/droch-shuil), the host
provisioner on top of [pyinfra](https://pyinfra.com). Each module is versioned
on its own, by a `<module>-<version>` tag.

## Use

Declare the modules in the `modules.yaml` of a suil workspace, each pinned
to its version:

```yaml
repos:
  - repo:    https://github.com/oberon-systems/suil-modules/releases/download/modules
    modules:
      <module>: <version>
```

The URL is the release `modules` of this repository: it holds one archive
per module version and `index.yaml`. `suil install` downloads the modules
into `modules/`, and `suil autoupdate` moves each to its newest version.

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

### Publishing

A pushed tag runs `.github/workflows/publish.yml`: the droch-shuil action
`publish` packs the module and adds it to the live `index.yaml`, and
`softprops/action-gh-release` uploads both to the release `modules`.

Without GitHub Actions, by hand or on any other CI, the same release is four
steps on a checkout at the tag:

```bash
pip install "$(grep '^droch-shuil==' requirements.txt)"
suil pack <module>-<version> dist/
suil index dist/ --merge https://github.com/oberon-systems/suil-modules/releases/download/modules
gh release upload modules dist/* --clobber
```

The last step is any upload that adds the archive to the release `modules`
and replaces `index.yaml` there; never run two publishes at once. See
[Publishing](https://oberon-systems.github.io/droch-shuil/05-manifest/#publishing)
in the droch-shuil documentation.

The documentation is the README of the repository and of every module,
published to GitHub Pages on every push to `main` that changes one of them.

## License

[MIT](LICENSE).
