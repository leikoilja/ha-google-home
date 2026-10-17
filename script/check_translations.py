#!/usr/bin/env python3
"""Check translation files without requiring every language to be complete."""

import argparse
from dataclasses import dataclass, field
from itertools import groupby
from operator import attrgetter
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Literal

from homeassistant.generated.languages import LANGUAGES
from homeassistant.util.json import json_loads_object

type Key = tuple[str, ...]
type Catalog = dict[Key, str]
type Baseline = dict[str, Catalog]

REPO_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS = Path("custom_components/google_home/translations")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class CatalogError(ValueError):
    """All invalid string values found in an otherwise readable JSON file."""

    def __init__(self, messages: list[str]) -> None:
        """Keep individual diagnostics for annotations."""
        super().__init__("\n".join(messages))
        self.messages = messages


@dataclass
class Issue:
    """A diagnostic attached to a translation file."""

    level: Literal["error", "warning"]
    file: Path
    message: str


@dataclass
class Report:
    """Validation diagnostics and an informational coverage summary."""

    issues: list[Issue] = field(default_factory=list)
    rows: list[str] = field(default_factory=list)

    def invalid_catalog(self, path: Path, error: Exception) -> None:
        """Report every available diagnostic and retain an invalid locale's row."""
        messages = error.messages if isinstance(error, CatalogError) else [str(error)]
        self.issues.extend(Issue("error", path, message) for message in messages)
        self.rows.append(f"| {path.name} | invalid | — | — | — |")

    @property
    def failed(self) -> bool:
        """Return whether the check found a blocking error."""
        return any(issue.level == "error" for issue in self.issues)

    def markdown(self) -> str:
        """Render coverage without imposing a minimum percentage."""
        return "\n".join(
            [
                "## Translation coverage",
                "",
                "Missing translations are allowed; Home Assistant uses English instead.",
                "Coverage counts strings with matching placeholders, not translation quality.",
                "",
                "| File | Valid strings | Missing | Obsolete | Placeholder mismatches |",
                "| --- | ---: | ---: | ---: | ---: |",
                *self.rows,
                "",
                (
                    f"Errors: {sum(i.level == 'error' for i in self.issues)}. "
                    f"Warnings: {sum(i.level == 'warning' for i in self.issues)}."
                ),
                "",
                *(["### Diagnostics", ""] if self.issues else []),
                *[
                    f"- {issue.level}: `{issue.file.name}`: `{issue.message}`"
                    for issue in self.issues
                ],
                "",
            ]
        )


def placeholders(value: str) -> frozenset[str]:
    """Accept the plain named arguments shared by HA's backend and frontend.

    Python's Formatter accepts conversions and doubled braces that the frontend's
    IntlMessageFormat rejects. This integration only uses {name} arguments; do
    not interpret Python formatting or ICU's richer message syntax here.
    """
    remainder = PLACEHOLDER.sub("", value)
    if "{" in remainder or "}" in remainder:
        raise ValueError(
            "Use plain {name} placeholders; other brace syntax is unsupported"
        )
    if re.search(r"'[{}<>]|''", value):
        raise ValueError(
            "Use ’ instead of a straight apostrophe before {, }, < or >, "
            "and don't double apostrophes"
        )
    if re.search(r"<(?:[A-Za-z]|/)", value):
        raise ValueError("ICU rich-text tags are unsupported; use plain text instead")
    return frozenset(PLACEHOLDER.findall(value))


def parse_catalog(content: bytes) -> Catalog:
    """Load nested objects containing non-empty strings with valid braces."""
    if content.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Remove the byte order mark (BOM) at the start of the file")
    data = json_loads_object(content)
    result: Catalog = {}
    errors: list[str] = []

    def visit(value: object, key: Key) -> None:
        if isinstance(value, dict):
            for name, child in value.items():
                visit(child, (*key, name))
        elif isinstance(value, str) and value.strip():
            try:
                placeholders(value)
            except ValueError as err:
                errors.append(f"{'.'.join(key)}: {err}")
            else:
                result[key] = value
        else:
            errors.append(f"{'.'.join(key)}: expected a non-empty string or object")

    visit(data, ())
    if errors:
        raise CatalogError(errors)
    return result


def git_output(repo: Path, *args: str) -> bytes:
    """Run Git in the requested repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    ).stdout


def load_baseline(repo: Path, directory: Path, ref: str) -> Baseline:
    """Read old translations so unchanged strings cannot block English edits."""
    paths = (
        git_output(
            repo, "ls-tree", "-r", "--name-only", "-z", ref, "--", directory.as_posix()
        )
        .decode("utf-8")
        .split("\0")
    )
    result: Baseline = {}
    for name in paths:
        path = Path(name)
        if path.parent != directory or path.suffix != ".json" or path.stem == "en":
            continue
        try:
            result[path.name] = parse_catalog(
                git_output(repo, "show", f"{ref}:./{name}")
            )
        except ValueError:
            # A PR can repair a broken file in its base revision.
            result[path.name] = {}
    return result


def check_translations(
    directory: Path,
    baseline: Baseline | None = None,
) -> Report:
    """Reject broken files and edited placeholders; report gaps and stale keys."""
    report = Report()
    source = directory / "en.json"
    try:
        english = parse_catalog(source.read_bytes())
    except (OSError, ValueError) as err:
        report.invalid_catalog(source, err)
        return report

    for path in sorted(directory.iterdir()):
        if path == source or path.name.startswith("."):
            continue
        if path.suffix != ".json" or path.stem not in LANGUAGES:
            report.invalid_catalog(
                path,
                ValueError(
                    f"Invalid translation filename: {path.name}; "
                    "expected a Home Assistant language code followed by .json"
                ),
            )
            continue
        try:
            translated = parse_catalog(path.read_bytes())
        except (OSError, ValueError) as err:
            report.invalid_catalog(path, err)
            continue

        compare_catalog(
            report,
            path,
            english,
            translated,
            (baseline or {}).get(path.name, {}),
        )
    return report


def compare_catalog(
    report: Report,
    path: Path,
    english: Catalog,
    translated: Catalog,
    baseline: Catalog,
) -> None:
    """Compare one readable locale and record each diagnostic separately."""
    missing = english.keys() - translated.keys()
    obsolete = translated.keys() - english.keys()
    mismatches = 0
    for key in sorted(english.keys() & translated.keys()):
        expected = placeholders(english[key])
        actual = placeholders(translated[key])
        if actual == expected:
            continue
        mismatches += 1
        unchanged = translated[key] in baseline.values()
        message = (
            f"{'.'.join(key)}: placeholders {sorted(actual)} do not match "
            f"English {sorted(expected)}."
        )
        if unchanged:
            message += " Unchanged translation; Home Assistant falls back to English."
        report.issues.append(Issue("warning" if unchanged else "error", path, message))
    for key in sorted(obsolete):
        message = f"{'.'.join(key)}: key does not exist in en.json."
        if key in baseline:
            report.issues.append(Issue("warning", path, message))
        else:
            message += (
                " Check for a mistyped key, or remove it if en.json no longer has it."
            )
            report.issues.append(Issue("error", path, message))
    valid = len(english) - len(missing) - mismatches
    report.rows.append(
        f"| {path.name} | {valid}/{len(english)} | {len(missing)} | "
        f"{len(obsolete)} | {mismatches} |"
    )


def emit_issue(issue: Issue) -> None:
    """Print an escaped GitHub annotation, also readable in a local terminal."""

    def escaped(value: str) -> str:
        return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    filename = escaped(str(issue.file)).replace(":", "%3A").replace(",", "%2C")
    print(f"::{issue.level} file={filename}::{escaped(issue.message)}")


def main(argv: list[str] | None = None) -> int:
    """Run checks and write a GitHub Actions summary when available."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        help="Git revision whose existing obsolete keys and unchanged placeholder "
        "mismatches are reported as warnings; "
        "without it, all placeholder mismatches and unknown keys fail",
    )
    args = parser.parse_args(argv)
    baseline = None
    if args.base_ref is not None:
        try:
            baseline = load_baseline(REPO_ROOT, TRANSLATIONS, args.base_ref)
        except subprocess.CalledProcessError as err:
            sys.exit(f"Cannot read --base-ref: {err.stderr.decode('utf-8').strip()}")
    report = check_translations(REPO_ROOT / TRANSLATIONS, baseline)
    summary = report.markdown()
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        key = attrgetter("file", "level")
        for (file, level), group in groupby(sorted(report.issues, key=key), key=key):
            emit_issue(
                Issue(
                    level,
                    file.relative_to(REPO_ROOT),
                    "\n".join(i.message for i in group),
                )
            )
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(summary)
    print(summary)
    return int(report.failed)


if __name__ == "__main__":
    sys.exit(main())
