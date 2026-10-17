"""Checks protect edited translations without making feature authors translate."""

import json
from pathlib import Path

import pytest

from script import check_translations as translations


def commit(repo: Path, message: str) -> str:
    """Commit a temporary test repository without user hooks or signing."""
    translations.git_output(repo, "add", ".")
    translations.git_output(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        message,
    )
    return translations.git_output(repo, "rev-parse", "HEAD").decode("utf-8").strip()


@pytest.fixture(name="git_repo")
def fixture_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an isolated repository and redirect CLI output into it."""
    directory = tmp_path / translations.TRANSLATIONS
    directory.mkdir(parents=True)
    for language in ("en", "de"):
        (directory / f"{language}.json").write_text(
            '{"help": "See {url}"}', encoding="utf-8"
        )
    translations.git_output(tmp_path, "init", "--initial-branch=main")
    commit(tmp_path, "Initial translations")
    monkeypatch.setattr(translations, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    return tmp_path


@pytest.fixture(name="catalogs")
def fixture_catalogs(tmp_path: Path) -> Path:
    """Provide English strings and a deliberately incomplete German translation."""
    (tmp_path / "en.json").write_text(
        json.dumps({"config": {"title": "Sign in", "help": "See {docs_url}"}}),
        encoding="utf-8",
    )
    (tmp_path / "de.json").write_text(
        json.dumps({"config": {"title": "Anmelden"}}), encoding="utf-8"
    )
    return tmp_path


def test_missing_and_obsolete_strings_do_not_fail(catalogs: Path) -> None:
    """Allow partial and empty locales; warn about obsolete keys without counting them."""
    (catalogs / "de.json").write_text(
        '{"config": {"title": "Anmelden", "old": "Alt"}}', encoding="utf-8"
    )
    (catalogs / "fr.json").write_text("{}", encoding="utf-8")
    baseline: translations.Baseline = {"de.json": {("config", "old"): "Alt"}}
    report = translations.check_translations(catalogs, baseline)
    assert not report.failed
    assert len(report.issues) == 1
    assert report.issues[0].level == "warning"
    assert "config.old" in report.issues[0].message
    assert "| de.json | 1/2 | 1 | 1 | 0 |" in report.markdown()
    assert "| fr.json | 0/2 | 2 | 0 | 0 |" in report.markdown()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"config":', None),
        ('{"config": {},}', None),
        ("\ufeff{}", "Remove the byte order mark (BOM)"),
        ('["text"]', None),
        ('{"config": {"title": 12}}', "config.title: expected a non-empty string"),
        ('{"config": {"title": null}}', "config.title: expected a non-empty string"),
        ('{"config": {"title": []}}', "config.title: expected a non-empty string"),
        ('{"config": {"title": "  "}}', "config.title: expected a non-empty string"),
        ('{"config": {"help": "See {docs_url"}}', "config.help:"),
    ],
)
@pytest.mark.parametrize("language", ["en", "de"])
def test_broken_catalogs_fail(
    catalogs: Path, text: str, message: str | None, language: str
) -> None:
    """Reject malformed source and translated files."""
    (catalogs / f"{language}.json").write_text(text, encoding="utf-8")
    report = translations.check_translations(catalogs)
    assert report.failed
    assert report.issues[0].file.name == f"{language}.json"
    if message is not None:
        assert message in report.issues[0].message
    assert f"| {language}.json | invalid |" in report.markdown()


def test_report_collects_all_invalid_strings(catalogs: Path) -> None:
    """Show all fixable string errors and keep invalid locales in the summary."""
    (catalogs / "de.json").write_text(
        json.dumps({"config": {"title": 12, "help": "See {docs_url!r}", "extra": ""}}),
        encoding="utf-8",
    )
    (catalogs / "fr.json").write_text("{}", encoding="utf-8")
    report = translations.check_translations(catalogs)
    assert report.failed
    assert len(report.issues) == 3
    assert all(issue.level == "error" for issue in report.issues)
    assert [issue.message.split(":", 1)[0] for issue in report.issues] == [
        "config.title",
        "config.help",
        "config.extra",
    ]
    assert "| de.json | invalid |" in report.markdown()
    assert "| fr.json | 0/2 | 2 | 0 | 0 |" in report.markdown()


def test_missing_english_fails(catalogs: Path) -> None:
    """Avoid a successful empty report if the source disappears."""
    (catalogs / "en.json").unlink()
    assert translations.check_translations(catalogs).failed


def test_summary_lists_each_warning_separately(catalogs: Path) -> None:
    """Placeholder warnings and obsolete keys each get a readable summary entry."""
    stale = {"config": {"help": "{old_url}"}, "old1": "A", "old2": "B"}
    (catalogs / "de.json").write_text(json.dumps(stale), encoding="utf-8")
    baseline: translations.Baseline = {
        "de.json": {("config", "help"): "{old_url}", ("old1",): "A", ("old2",): "B"}
    }
    report = translations.check_translations(catalogs, baseline)
    assert not report.failed
    assert len(report.issues) == 3
    assert report.issues[0].message.startswith("config.help: placeholders")
    assert "old1: key" in report.markdown()
    assert "old2: key" in report.markdown()
    assert "Warnings: 3." in report.markdown()
    assert "Unchanged translation" in report.markdown()

    assert (
        sum(line.startswith("- warning:") for line in report.markdown().splitlines())
        == 3
    )


@pytest.mark.parametrize(
    ("invalid", "valid"), [("zh-CN", "zh-Hans"), ("no", "nb"), ("pt_BR", "pt-BR")]
)
def test_locale_filenames_use_home_assistant_codes(
    catalogs: Path, invalid: str, valid: str
) -> None:
    """Reject plausible filenames that Home Assistant will not load."""
    path = catalogs / f"{invalid}.json"
    path.write_bytes((catalogs / "en.json").read_bytes())
    report = translations.check_translations(catalogs)
    assert report.failed
    assert report.issues[0].file == path
    assert f"Invalid translation filename: {invalid}.json" in report.issues[0].message
    path.rename(catalogs / f"{valid}.json")
    report = translations.check_translations(catalogs)
    assert not report.failed
    assert "### Diagnostics" not in report.markdown()


@pytest.mark.parametrize("filename", ["fr", "fr.JSON", "fr/fr.json", "de.json.orig"])
def test_invalid_translation_paths_fail(catalogs: Path, filename: str) -> None:
    """Reject files with the wrong extension and nested translation directories."""
    path = catalogs / filename
    path.parent.mkdir(exist_ok=True)
    path.write_bytes((catalogs / "en.json").read_bytes())
    report = translations.check_translations(catalogs)
    assert report.failed
    assert "Invalid translation filename:" in report.issues[0].message
    assert f"| {Path(filename).parts[0]} | invalid |" in report.markdown()
    assert "| de.json | 1/2 |" in report.markdown()


def test_hidden_editor_files_are_ignored(catalogs: Path) -> None:
    """Local editor and filesystem metadata do not block translation checks."""
    for name in (".DS_Store", ".de.json.swp"):
        (catalogs / name).write_bytes(b"not JSON")
    assert not translations.check_translations(catalogs).failed


@pytest.mark.usefixtures("git_repo")
def test_missing_base_ref_exits() -> None:
    """A mistyped local base ref fails instead of silently changing validation."""
    with pytest.raises(SystemExit, match="Cannot read --base-ref"):
        translations.main(["--base-ref", "missing"])


@pytest.mark.parametrize("value", ["Hilfe", "Siehe {url}", "{docs_url} {extra}"])
def test_placeholder_mismatches_fail(catalogs: Path, value: str) -> None:
    """Detect omitted, renamed and additional placeholders in new translations."""
    (catalogs / "de.json").write_text(
        json.dumps({"config": {"help": value}}), encoding="utf-8"
    )
    report = translations.check_translations(catalogs, baseline={})
    assert report.failed
    assert "config.help: placeholders" in report.issues[0].message
    assert "| de.json | 0/2 | 1 | 0 | 1 |" in report.markdown()


def test_placeholder_order_and_repetition(catalogs: Path) -> None:
    """Allow reordered and repeated plain arguments accepted by both HA parsers."""
    (catalogs / "en.json").write_text('{"help": "{first} {second}"}', encoding="utf-8")
    (catalogs / "de.json").write_text(
        '{"help": "{second} {first} {first}"}', encoding="utf-8"
    )
    assert not translations.check_translations(catalogs).failed


@pytest.mark.parametrize(
    "value",
    [
        "Siehe {docs_url!r}",
        "Siehe {docs_url} {{Beispiel}}",
        "Siehe {docs_url!s}",
        "Siehe {docs_url:}",
        "Siehe {docs_url:>10}",
        "Siehe {docs_url.attr}",
        "Siehe {docs_url[0]}",
        "Siehe {}",
        "Siehe {0}",
        "Siehe {docs_url, number}",
        "Siehe {docs_url, select, other {Hilfe}}",
        "Siehe '{docs_url}'",
        "Siehe ''{docs_url}''",
        "L''aide : {docs_url}",
        "l'{docs_url}",
        "Siehe '''{docs_url}'''",
        "Siehe '<example> {docs_url}",
        "Siehe '> {docs_url}",
        "Siehe <link>{docs_url}</link>",
        "Siehe {docs_url} </>",
        "Siehe {docs_url} </",
    ],
)
@pytest.mark.parametrize("language", ["en", "de"])
def test_unsupported_message_syntax_fails(
    catalogs: Path, value: str, language: str
) -> None:
    """Reject Python-only and ICU-only constructs even in unchanged translations."""
    (catalogs / f"{language}.json").write_text(
        json.dumps({"config": {"help": value}}), encoding="utf-8"
    )
    baseline: translations.Baseline = {"de.json": {("config", "help"): value}}
    report = translations.check_translations(catalogs, baseline)
    assert report.failed
    assert report.issues[0].level == "error"
    assert report.issues[0].file.name == f"{language}.json"
    assert "config.help:" in report.issues[0].message


@pytest.mark.parametrize(
    "value",
    [
        "L'aide est ici : {docs_url}",
        "l’{docs_url}",
        "Siehe ‘{docs_url}’",
        "Siehe `{docs_url}`",
        "Siehe {docs_url} und {docs_url}",
        "1 < 2 > 0: {docs_url}",
    ],
)
def test_plain_placeholders_with_punctuation(catalogs: Path, value: str) -> None:
    """Keep ordinary apostrophes, quotation marks and repeated arguments usable."""
    (catalogs / "de.json").write_text(
        json.dumps({"config": {"help": value}}), encoding="utf-8"
    )
    assert not translations.check_translations(catalogs).failed


@pytest.mark.parametrize("old_key", [("config", "help"), ("old", "help")])
def test_unchanged_stale_string_does_not_block_other_translation_edits(
    catalogs: Path,
    old_key: translations.Key,
) -> None:
    """Changing another string in a locale does not require fixing its stale ones."""
    baseline: translations.Baseline = {
        "de.json": {("config", "title"): "Alt", old_key: "{old_url}"}
    }
    (catalogs / "de.json").write_text(
        '{"config": {"title": "Anmelden", "help": "{old_url}"}}', encoding="utf-8"
    )
    report = translations.check_translations(catalogs, baseline)
    assert not report.failed
    assert report.issues[0].level == "warning"
    assert "Unchanged translation" in report.issues[0].message
    assert "| de.json | 1/2 | 0 | 0 | 1 |" in report.markdown()
    # A strict local audit still finds the stale placeholder.
    assert translations.check_translations(catalogs).failed


def test_edited_stale_string_must_match_english(catalogs: Path) -> None:
    """An existing mismatch is not exempt once its translation is edited."""
    baseline: translations.Baseline = {"de.json": {("config", "help"): "{old_url}"}}
    (catalogs / "de.json").write_text(
        '{"config": {"help": "Siehe {old_url}"}}', encoding="utf-8"
    )
    assert translations.check_translations(catalogs, baseline).failed


def test_cli_allows_english_only_changes_and_writes_summary(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exercise Git comparison, English-only changes and the CI summary together."""
    directory = git_repo / translations.TRANSLATIONS
    (directory / "en.json").write_text(
        '{"help": "See {docs_url}", "new": "New feature"}', encoding="utf-8"
    )
    summary = git_repo / "summary.md"

    assert translations.main(["--base-ref", "HEAD"]) == 0
    assert (
        "::warning file=custom_components/google_home/translations/de.json::"
        in capsys.readouterr().out
    )
    assert "| de.json | 0/2 | 1 | 0 | 1 |" in summary.read_text(encoding="utf-8")
    assert translations.main([]) == 1


@pytest.mark.parametrize("content", [b'{"help":', b"\xef\xbb\xbf{}", b"\xff"])
def test_broken_base_can_be_repaired(git_repo: Path, content: bytes) -> None:
    """An unreadable base file is treated as empty when checking its replacement."""
    path = git_repo / translations.TRANSLATIONS / "de.json"
    path.write_bytes(content)
    base = commit(git_repo, "Broken JSON")
    path.write_text('{"help": "Siehe {url}"}', encoding="utf-8")
    assert translations.main(["--base-ref", base]) == 0
    path.write_text('{"help": "Siehe {wrong_url}"}', encoding="utf-8")
    assert translations.main(["--base-ref", base]) == 1
    path.write_text('{"help": "Siehe {wrong_url!r}"}', encoding="utf-8")
    assert translations.main(["--base-ref", base]) == 1


def test_cli_groups_annotations_by_file_and_level(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Group log annotations while preserving individual summary diagnostics."""
    directory = git_repo / translations.TRANSLATIONS
    (directory / "de.json").write_text(
        '{"help": "{old_url}", "old": "Text"}', encoding="utf-8"
    )
    base = commit(git_repo, "Stale translations")
    (directory / "de.json").write_text(
        '{"help": "{old_url}", "old": "Text", "unknown": "Text"}', encoding="utf-8"
    )
    (directory / "fr.json").write_text('{"help": "{wrong_url}"}', encoding="utf-8")
    assert translations.main(["--base-ref", base]) == 1
    output = capsys.readouterr().out
    annotations = [line for line in output.splitlines() if line.startswith("::")]
    assert len(annotations) == 3
    assert (
        "::error file=custom_components/google_home/translations/de.json::"
        in annotations[0]
    )
    assert (
        "::warning file=custom_components/google_home/translations/de.json::"
        in annotations[1]
    )
    assert "%0Aold: key does not exist in en.json." in annotations[1]
    assert (
        "::error file=custom_components/google_home/translations/fr.json::"
        in annotations[2]
    )
    summary = (git_repo / "summary.md").read_text(encoding="utf-8")
    assert "Errors: 2. Warnings: 2." in summary
    assert len([line for line in summary.splitlines() if line.startswith("- ")]) == 4


def test_annotations_escape_workflow_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A malformed key cannot create a second workflow command in the log."""
    translations.emit_issue(
        translations.Issue("warning", Path("bad,name.json"), "bad%\n::error::injected")
    )
    assert capsys.readouterr().out == (
        "::warning file=bad%2Cname.json::bad%25%0A::error::injected\n"
    )


def test_new_unknown_keys_fail(catalogs: Path) -> None:
    """Catch new misspelled keys in an existing locale."""
    baseline: translations.Baseline = {"de.json": {("config", "title"): "Alt"}}
    (catalogs / "de.json").write_text(
        '{"config": {"title_typo": "Anmelden"}}', encoding="utf-8"
    )
    report = translations.check_translations(catalogs, baseline)
    assert report.failed
    assert "config.title_typo: key does not exist" in report.issues[0].message
    assert (
        "Check for a mistyped key, or remove it if en.json no longer has it."
        in report.issues[0].message
    )


def test_removing_an_english_key_only_warns(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """English-only feature changes do not require cleaning up every locale."""
    directory = git_repo / translations.TRANSLATIONS
    (directory / "en.json").write_text('{"new": "Text"}', encoding="utf-8")
    assert translations.main(["--base-ref", "HEAD"]) == 0
    assert (
        "::warning file=custom_components/google_home/translations/de.json::"
        "help: key does not exist in en.json."
    ) in capsys.readouterr().out
