"""MkDocs hooks: the README is the home page, and every module's README is a page."""

import re
from pathlib import Path

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.files import File, Files

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\]\((?!https?://|#)([^)]+)\)")


def page(config: MkDocsConfig, uri: str, readme: Path, title: str) -> File:
    """A README served at uri, its relative links pointed at the file on GitHub."""
    where = readme.parent.relative_to(ROOT).as_posix()
    blob = config.repo_url.rstrip("/") + "/blob/main/" + ("" if where == "." else f"{where}/")
    text = LINK.sub(lambda match: f"]({blob}{match.group(1)})", readme.read_text(encoding="utf-8"))
    file = File.generated(config, uri, content=f"---\ntitle: {title}\n---\n\n{text}")
    # edit_uri is relative to docs/, and "Edit on GitHub" has to open the README.
    file.edit_uri = "../" + readme.relative_to(ROOT).as_posix()
    return file


def on_config(config: MkDocsConfig) -> MkDocsConfig:
    # A flat nav, as droch-shuil's: a modules/ section would render as a caption.
    names = [readme.parent.name for readme in sorted(ROOT.glob("modules/*/README.md"))]
    config["nav"] = [{"Home": "index.md"}] + [{name: f"modules/{name}.md"} for name in names]
    return config


def on_files(files: Files, config: MkDocsConfig) -> Files:
    files.append(page(config, "index.md", ROOT / "README.md", "Home"))

    for readme in sorted(ROOT.glob("modules/*/README.md")):
        files.append(page(config, f"modules/{readme.parent.name}.md", readme, readme.parent.name))

    return files
