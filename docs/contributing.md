# Contributing

## Ask a question

For help with setup or usage, search [GitHub Discussions](https://github.com/leikoilja/ha-google-home/discussions) and the [issues](https://github.com/leikoilja/ha-google-home/issues?q=is%3Aissue). If nobody has asked yet, start a discussion in [Q&A](https://github.com/leikoilja/ha-google-home/discussions/categories/q-a).

## Report a bug or suggest a feature

[Open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose). For a bug, include the integration version and [debug logs](troubleshooting.md#collect-debug-logs).

## Translate the integration

The integration's setup screens, options and action descriptions follow your Home Assistant language. Text that isn't translated yet is shown in English.

Translations are files in [`custom_components/google_home/translations`](https://github.com/leikoilja/ha-google-home/tree/master/custom_components/google_home/translations). You can edit them on GitHub in your browser:

- **To fix a translation**, open your language's file, select the pencil icon, and make your changes.
- **To add a language**, open [`en.json`](https://github.com/leikoilja/ha-google-home/blob/master/custom_components/google_home/translations/en.json), copy its contents, then [create a new file](https://github.com/leikoilja/ha-google-home/new/master/custom_components/google_home/translations) and paste them. Name the file using a code from [Home Assistant's language list](https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/generated/languages.py), such as `de.json` for German or `pt-BR.json` for Brazilian Portuguese, and translate the text.

Translate only the text after each colon. Keep the keys before the colons and anything in curly brackets, such as `{docs_url}`, unchanged. Home Assistant fills those in.

When you save, GitHub creates a copy of the repository under your account and offers to open a pull request.

You can submit a partial translation. Remove entries you have not translated: copied English text will not follow later changes to the English source, and the coverage table counts it as translated. To see how many strings your file is missing, open **Details** next to the **Translations** check on your pull request, then select **Summary**. If the check shows as awaiting approval, a maintainer needs to [approve the run](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks) first.

Keep placeholders in their original form: `{docs_url}` is allowed, but `{docs_url!r}` and `{{docs_url}}` are rejected. Added formatting inside the braces is also rejected. Don't use curly brackets except around placeholders. Don't put a Latin letter (A–Z or a–z) or `/` directly after `<`. Quotation marks around a placeholder are fine, such as `“{docs_url}”`, `„{docs_url}“` or `«{docs_url}»`. Use `’` instead of a straight apostrophe before `{`, `}`, `<` or `>`, as in `l’{device}`. Don't double apostrophes: write `L'aide`, not `L''aide`.

## Develop

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). Fork the repository, create a branch from `master`, and install the dependencies:

```shell
uv sync
```

Or open the repository in its [dev container](https://containers.dev/), in Visual Studio Code or GitHub Codespaces, which has uv and the dependencies installed.

### Try your changes

```shell
script/develop
```

This starts Home Assistant at <http://localhost:8123> with the integration loaded and its debug logging turned on. It uses [`config/configuration.yaml`](https://github.com/leikoilja/ha-google-home/blob/master/config/configuration.yaml); everything else Home Assistant writes to `config/` is ignored by git.

### Run the checks

Run the tests:

```shell
uv run pytest
```

Some tests run the integration inside Home Assistant, with fixtures from [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component). Each of its releases requires one exact Home Assistant version, so when you change `homeassistant` in `pyproject.toml`, change `pytest-homeassistant-custom-component` to the release that requires the same version. `uv lock` fails if they don't match.

If you change an entity's name, icon, state, attributes or registry entry on purpose, update the snapshots with `uv run pytest --snapshot-update`, and review the changes under `tests/snapshots/` before you commit.

Every file in `custom_components/google_home` needs 90% or more branch coverage, which counts the lines the tests run and whether they take each way through every `if` statement and loop. To check, run the tests with coverage, then the same check CI runs:

```shell
uv run pytest --cov
script/check_coverage
```

The first command lists each file's coverage and the lines the tests miss; `176->178` means the tests never go from line 176 to line 178, and `283->exit` that they never leave the function from line 283. The second names each file below 90%. CI adds the table to the workflow summary: open **Details** next to the **Pre-commit** check on your pull request, then select **Summary**. If your change adds code that no test reaches, add a test that checks what the code does, not one that only runs it.

If you add or change a feature, update `en.json`; you do not need to translate it into other languages. Missing strings and keys that became obsolete do not block your PR. Newly added translation keys must exist in English. If the **Translations** check reports “Check for a mistyped key”, correct any spelling mistake or remove the entry if its English key was removed. Placeholder-name mismatches block new or edited text. If the exact text already appeared in the same language file at the base revision, a mismatch produces a warning and Home Assistant uses English instead, even if the key moved.

Every translation file must contain valid JSON encoded as UTF-8 without a byte order mark (BOM), with unique keys, non-empty string values and the [placeholder syntax described above](#translate-the-integration). CI rejects errors in these rules even in files your PR does not change; the `check json` hook catches duplicate keys.

To check your branch locally, fetch the project's `master` branch and compare with its common ancestor. This uses the project's repository even when `origin` points to your fork:

```shell
git fetch https://github.com/leikoilja/ha-google-home.git master
uv run python script/check_translations.py --base-ref "$(git merge-base HEAD FETCH_HEAD)"
```

The command reports translation coverage and identifies errors by file and key. Omit `--base-ref` and its value to treat all placeholder-name mismatches and unknown keys as errors.

CI compares its checkout with its first parent: the target used for a PR's merge checkout, or the preceding commit on a push. It adds translation coverage and all diagnostics to the workflow summary. These checks cannot judge the accuracy or naturalness of the wording.

[prek](https://prek.j178.dev/) runs the linters and formatters, including [ruff](https://docs.astral.sh/ruff/) and [dprint](https://dprint.dev/). Run them on all files:

```shell
uvx prek run --all-files
```

To run them on every commit, install the git hook once:

```shell
uvx prek install
```

### Edit the docs

The docs are in `docs/` and built with [Zensical](https://zensical.org/). Preview them at <http://localhost:8000> while you edit:

```shell
uv run --only-group docs zensical serve
```

A pull request that changes the docs gets a preview link in a comment.

## License

The project is under the [MIT License](https://github.com/leikoilja/ha-google-home/blob/master/LICENSE). When you submit a change, it is understood to be under the same license.
