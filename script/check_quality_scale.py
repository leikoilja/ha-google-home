#!/usr/bin/env python3
"""Check quality_scale.yaml against Home Assistant core's quality scale rules.

Hassfest skips this file for custom integrations, so this script downloads
hassfest's quality scale code from the core release of the installed
homeassistant, which `uv run` keeps at the version pyproject.toml pins. Every
rule must be listed, in core's order, as done or as exempt with a comment, and
the rules marked done must pass core's validators.
"""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import gzip
from http.client import HTTPException
from importlib import import_module, metadata
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import time
from urllib.error import HTTPError
import urllib.request
import zlib

from packaging.requirements import Requirement
import probatio
from probatio.humanize import humanize_error

from homeassistant.const import __version__ as ha_version
from homeassistant.util.yaml import load_yaml_dict

INTEGRATION = Path(__file__).resolve().parents[1] / "custom_components/google_home"
CORE_ARCHIVE = "https://github.com/home-assistant/core/archive/refs/tags/{}.tar.gz"
# The parts of core's source that hassfest's quality scale code needs
CORE_FILES = (
    ".strict-typing",
    "script/__init__.py",
    "script/hassfest/",
    "packages/hassfest/hassfest/",
)
# A package without type hints, which the self-check adds as a requirement
UNTYPED = "untyped-self-check"
type Document = dict[str, object]


def installed(requirement: str) -> str:
    """Return the requirement pinned to its installed version."""
    name = Requirement(requirement).name
    try:
        return f"{name}=={metadata.version(name)}"
    except metadata.PackageNotFoundError:
        sys.exit(
            f"manifest.json requires {name}, which isn't installed: add it to pyproject.toml"
        )


def status_of(value: object) -> object:
    """Return a rule's status, whether given alone or with a comment."""
    return value.get("status") if isinstance(value, dict) else value


class Hassfest:
    """Core's quality scale code, run on the integration."""

    def __init__(self, core: Path) -> None:
        """Import hassfest from core's source and load the integration."""
        sys.path[:0] = [str(core), str(core / "packages/hassfest")]
        # Install UNTYPED there: package metadata only, with no py.typed. Core
        # reads its files from RECORD, which must not be empty.
        dist_info = core / f"{UNTYPED.replace('-', '_')}-1.0.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {UNTYPED}\nVersion: 1.0\n", encoding="utf-8"
        )
        (dist_info / "RECORD").write_text(
            f"{dist_info.name}/METADATA,,\n", encoding="utf-8"
        )
        self.quality_scale = import_module("script.hassfest.quality_scale")
        model = import_module("hassfest.model")
        self.config = model.Config(
            specific_integrations=None,
            root=core,
            action="validate",
            requirements=False,
        )
        self.integration = model.Integration(INTEGRATION, self.config)
        self.integration.load_manifest()
        # The strict-typing validator first looks for the integration on
        # core's .strict-typing list of integrations that mypy checks in
        # strict mode. A custom integration can't be on it, so add it to the
        # downloaded copy: the mypy check in prek runs in strict mode.
        with (core / ".strict-typing").open("a", encoding="utf-8") as file:
            file.write(f"\nhomeassistant.components.{INTEGRATION.name}.*\n")
        # The validator then checks that each requirement ships type hints.
        # It reads only name==version and skips a version that isn't
        # installed, so give it each requirement's installed version.
        self.integration.manifest["requirements"] = [
            installed(requirement) for requirement in self.integration.requirements
        ]
        self.rule_names: list[str] = [
            rule.name for rule in self.quality_scale.ALL_RULES
        ]

    def check(self, document: Document) -> list[str]:
        """Return each way quality_scale.yaml fails core's quality scale."""
        errors: list[str] = []
        try:
            self.quality_scale.SCHEMA(document)
        except probatio.Invalid as err:
            errors.extend(humanize_error(document, err).splitlines())
        rules = document.get("rules")
        if not isinstance(rules, dict):
            return errors

        # Missing and unknown rules are the schema's errors, so compare only
        # the order of the rules both lists have.
        listed = [name for name in rules if name in self.rule_names]
        expected = [name for name in self.rule_names if name in rules]
        wrong = next((i for i, n in enumerate(listed) if n != expected[i]), None)
        if wrong is not None:
            errors.append(
                f"{expected[wrong]} must come before {listed[wrong]}, as in core's"
                " list of rules"
            )

        statuses = {name: status_of(value) for name, value in rules.items()}
        # Core accepts todo, and checks tiers only against a core manifest
        errors.extend(
            f"{name} is todo: do it, or mark it exempt with a comment"
            for name, status in statuses.items()
            if status == "todo"
        )

        done = {name for name, status in statuses.items() if status == "done"}
        for name in self.rule_names:
            validator = self.quality_scale.VALIDATORS.get(name)
            if name not in done or validator is None:
                continue
            found = validator.validate(self.config, self.integration, rules_done=done)
            if found:
                errors.extend(f"{name}: {error}" for error in found)
        return errors

    def self_check(self, document: Document) -> dict[str, bool]:
        """Return whether check() rejects each faulty copy of a passing file.

        Each copy has one change, so the expected error comes from that change.
        """
        rules = document["rules"]
        assert isinstance(rules, dict)  # The schema passed
        first, second, *rest = self.rule_names
        missing = {name: value for name, value in rules.items() if name != first}
        swapped = {name: rules[name] for name in (second, first, *rest)}
        cases = [
            ("a rule marked todo", {**rules, first: "todo"}, f"{first} is todo"),
            (
                "a missing rule",
                missing,
                f"required key not provided at 'rules.{first}'",
            ),
            (
                "two rules out of order",
                swapped,
                f"{first} must come before {second}",
            ),
            (
                "an exemption without a comment",
                {**rules, first: {"status": "exempt"}},
                f"required key not provided at 'rules.{first}.comment'",
            ),
        ]
        documents = [
            (case, {**document, "rules": changed}, error)
            for case, changed, error in cases
        ]
        # Such as a rule that lost its indentation
        documents.append(
            (
                "a key outside rules",
                {**document, first: "done"},
                f"not a valid option at '{first}'",
            )
        )
        rejected = {
            case: any(error in found for found in self.check(changed))
            for case, changed, error in documents
        }

        # Exercise a validator with an explicitly invalid manifest rather
        # than assuming the integration lacks a particular flow method.
        config_flow = self.integration.manifest["config_flow"]
        self.integration.manifest["config_flow"] = False
        try:
            rejected["config-flow done without its manifest flag"] = any(
                "config-flow: Integration does not set config_flow" in found
                for found in self.check(document)
            )
        finally:
            self.integration.manifest["config_flow"] = config_flow

        # Without this case, a check that skipped strict-typing's requirement
        # check would go unnoticed
        requirements = self.integration.manifest["requirements"]
        self.integration.manifest["requirements"] = [
            *requirements,
            installed(f"{UNTYPED}>=1"),
        ]
        try:
            rejected["a requirement without type hints"] = any(
                f"strict-typing: Requirements ['{UNTYPED}==1.0']" in found
                for found in self.check(document)
            )
        finally:
            self.integration.manifest["requirements"] = requirements
        return rejected


def retry_delay(header: str | None, backoff: int) -> float:
    """Return the server's requested delay or the fallback backoff."""
    if header is None:
        return backoff
    header = header.strip()
    if header.isascii() and header.isdigit():
        return float(header)
    try:
        retry_at = parsedate_to_datetime(header)
    except ValueError:
        return backoff
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0, (retry_at - datetime.now(UTC)).total_seconds())


def download_core(version: str, destination: Path) -> None:
    """Download core's archive with at most two retries and ten seconds of waiting."""
    url = CORE_ARCHIVE.format(version)
    remaining_wait = 10.0
    try:
        for backoff in (1, 2, None):
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    destination.write_bytes(response.read())
            except HTTPError as err:
                with err:
                    if backoff is None or err.code not in {429, 500, 502, 503, 504}:
                        raise
                    delay = retry_delay(err.headers.get("Retry-After"), backoff)
                    if delay > remaining_wait:
                        raise
                time.sleep(delay)
                remaining_wait -= delay
            else:
                return
    except (OSError, HTTPException) as err:
        sys.exit(f"Cannot download Home Assistant {version}'s source from {url}: {err}")


def extract_archive(path: Path, version: str, destination: Path) -> None:
    """Check the archive and extract only the source files hassfest needs."""
    root = f"core-{version}"
    try:
        with (
            gzip.open(path, "rb") as source,
            tarfile.open(fileobj=source, mode="r|") as archive,
        ):
            for member in archive:
                if member.name == root:
                    continue
                prefix, _, member.name = member.name.partition("/")
                if prefix != root:
                    raise tarfile.ReadError(f"expected all paths under {root}/")
                if member.isfile() and member.name.startswith(CORE_FILES):
                    archive.extract(member, destination, filter="data")
            # Tar iteration can end before gzip verifies the checksum and trailer.
            while source.read(1024 * 1024):
                pass
    except (OSError, EOFError, tarfile.TarError, zlib.error) as err:
        sys.exit(f"Cannot extract Home Assistant {version}'s source from {path}: {err}")


def extract_core(version: str, destination: Path, cache_dir: Path | None) -> None:
    """Extract the exact core release, downloading it if absent from the cache."""
    filename = f"core-{version}.tar.gz"
    cached = cache_dir / filename if cache_dir is not None else None
    if cached is not None and cached.is_file():
        extract_archive(cached, version, destination)
        return

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache_dir) as staging:
        path = Path(staging) / filename
        download_core(version, path)
        extract_archive(path, version, destination)
        if cached is not None:
            path.replace(cached)


def main() -> int:
    """Check the file and that the check rejects faulty copies of it."""
    path = INTEGRATION / "quality_scale.yaml"
    document = load_yaml_dict(str(path))
    cache_dir = os.environ.get("HA_QUALITY_SCALE_CACHE_DIR")
    with tempfile.TemporaryDirectory() as core:
        extract_core(ha_version, Path(core), Path(cache_dir) if cache_dir else None)
        try:
            hassfest = Hassfest(Path(core))
            errors = hassfest.check(document)
            rejected = {} if errors else hassfest.self_check(document)
        except Exception as err:
            err.add_note(
                f"Home Assistant {ha_version}'s hassfest may have changed:"
                f" update {Path(__file__).name} to match"
            )
            raise
    for error in errors:
        print(f"{path.name}: {error}", file=sys.stderr)
    if errors:
        return 1
    if missed := [case for case, caught in rejected.items() if not caught]:
        print(f"Self-check: the check accepted {', '.join(missed)}", file=sys.stderr)
        return 1
    statuses = [status_of(value) for value in document["rules"].values()]
    print(
        f"{path.name} meets Home Assistant {ha_version}'s quality scale:"
        f" {statuses.count('done')} rules done, {statuses.count('exempt')} exempt"
    )
    print(f"Self-check: the check rejected {', '.join(rejected)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
