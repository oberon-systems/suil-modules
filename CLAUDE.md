# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The public modules of suil. suil itself is `droch-shuil` on PyPI, source in
`oberon-systems/droch-shuil`. This repository holds modules only; each one is
released by a `<module>-<version>` tag.

## Commands

```shell
make install    # .venv, requirements.txt, pre-commit hooks
make shell      # subshell with the venv active and PRE_COMMIT_HOME set
make test       # pytest modules -q
make lint       # pre-commit run --all-files
make docs       # mkdocs serve on 127.0.0.1:8005; docs-build builds site/
make module MODULE=<name>   # modules/<name>/.cz.yaml from cz-module.yaml
```

A module is released by `cz bump` run in `modules/<name>`: its own
`.cz.yaml`, its own `CHANGELOG.md` from its commits only, tag
`<name>-<version>`. Its pre-bump hook runs `suil index <tag>`, which records
the release and its sha256 in the committed `index.yaml`.

A pushed tag runs `.github/workflows/publish.yml`: the droch-shuil action
`publish` runs `suil pack <tag>`, which packs the module into `dist/` beside
`index.yaml` and refuses a module that changed after its bump, and both are
uploaded to the release `modules`, the source workspaces install from. A
change to `index.yaml` on `main` uploads it alone. By hand or on another CI:
`suil pack <tag>`, then upload `dist/`; see `docs/05-manifest.md` in
droch-shuil.

A module is `modules/<name>/`, exactly as in a suil workspace; this
repository is one, with every module in a `repo: local` entry of its
`modules.yaml`.

## Committing - STRICT

1. Commit only through commitizen: `cz commit`. Never `git commit` and never a
   hand-written message.
2. Never write `Co-Authored-By`, generated-by or any other trailer.
3. Never `--no-verify` or `SKIP=` past a hook.

`cz check` enforces the `wyld_cz` schema `^\[(fix|feat|build|docs|refactor)\]\[[^\]]+\]: .+`.

## Conventions

- No real hosts, addresses, users or private repository names anywhere. Use
  placeholders: alpha, beta, example.com, 192.0.2.x.
- YAML in `data/` uses the aligned-colon layout (`key:     value`).
