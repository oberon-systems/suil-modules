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
make lint       # pre-commit run --all-files
make docs       # mkdocs serve on 127.0.0.1:8005; docs-build builds site/
make module MODULE=<name>   # modules/<name>/.cz.yaml from cz-module.yaml
make bump MODULE=<name>     # cz bump for one module: changelog and <name>-<version> tag
```

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
