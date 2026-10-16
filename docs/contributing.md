# Contributing

## Ask a question

For help with setup or usage, search [GitHub Discussions](https://github.com/leikoilja/ha-google-home/discussions) and the [issues](https://github.com/leikoilja/ha-google-home/issues?q=is%3Aissue). If nobody has asked yet, start a discussion in [Q&A](https://github.com/leikoilja/ha-google-home/discussions/categories/q-a).

## Report a bug or suggest a feature

[Open an issue](https://github.com/leikoilja/ha-google-home/issues/new/choose). For a bug, include the integration version and [debug logs](troubleshooting.md#collect-debug-logs).

## Translate the integration

The integration's setup screens, options and action descriptions follow your Home Assistant language. Text that isn't translated yet is shown in English.

Translations are files in [`custom_components/google_home/translations`](https://github.com/leikoilja/ha-google-home/tree/master/custom_components/google_home/translations). You can edit them on GitHub in your browser:

- **To fix a translation**, open your language's file, select the pencil icon, and make your changes.
- **To add a language**, open [`en.json`](https://github.com/leikoilja/ha-google-home/blob/master/custom_components/google_home/translations/en.json), copy its contents, then [create a new file](https://github.com/leikoilja/ha-google-home/new/master/custom_components/google_home/translations) and paste them. Name the file after the [BCP 47](https://www.rfc-editor.org/info/bcp47) language tag, such as `de.json` for German or `pt-BR.json` for Brazilian Portuguese, and translate the text.

Translate only the text after each colon. Keep the keys before the colons and anything in curly brackets, such as `{docs_url}`, unchanged. Home Assistant fills those in.

When you save, GitHub creates a copy of the repository under your account and offers to open a pull request.

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
