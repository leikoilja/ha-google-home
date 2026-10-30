"""Test the release script."""

from collections.abc import Callable
from importlib.metadata import version as package_version
import io
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from typing import cast
from zipfile import ZipFile

from github.GitCommit import GitCommit
from github.GithubException import UnknownObjectException
from github.Repository import Repository
import pytest

from script import publish_release

INTEGRATION = "custom_components/google_home"
MANIFEST = f"{INTEGRATION}/manifest.json"
HACS_JSON = {"name": "Google Home", "homeassistant": "2026.1.0", "render_readme": True}


def git(*args: str) -> str:
    """Run Git in the checkout."""
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def head_tag() -> str:
    """Return the tag of a release of the committed integration."""
    return f"v{json.loads(git('show', f'HEAD:{MANIFEST}'))['version']}"


def zip_of(files: dict[str, str]) -> bytes:
    """Return a zip holding the files."""
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_zip_holds_integration_files_at_root(tmp_path: Path) -> None:
    """HACS and Home Assistant extract the zip into custom_components/google_home."""
    path = tmp_path / "google_home.zip"
    publish_release.build_zip("HEAD", path)

    with ZipFile(path) as archive:
        files = {name for name in archive.namelist() if not name.endswith("/")}
    tracked = git("ls-tree", "-r", "--name-only", "HEAD", INTEGRATION).splitlines()
    assert files == {name.removeprefix(f"{INTEGRATION}/") for name in tracked}
    assert "manifest.json" in files
    publish_release.check_zip(path, head_tag())


@pytest.mark.parametrize(
    ("files", "error"),
    [
        (
            {"google_home/manifest.json": '{"version": "1.17.0"}'},
            "google_home.zip has no manifest.json at its root",
        ),
        (
            {"manifest.json": '{"version": "1.16.0"}'},
            "google_home.zip has version 1.16.0, not v1.17.0",
        ),
    ],
    ids=["nested", "other version"],
)
def test_check_zip_refuses(tmp_path: Path, files: dict[str, str], error: str) -> None:
    """A nested zip or one of another version would not install as the release."""
    path = tmp_path / "google_home.zip"
    path.write_bytes(zip_of(files))

    with pytest.raises(SystemExit, match=f"^{re.escape(error)}$"):
        publish_release.check_zip(path, "v1.17.0")


class FakeRepo:
    """Master's history, as update_manifests reads and moves it."""

    def __init__(self) -> None:
        """Start master with one commit."""
        self.files: dict[str, dict[str, dict[str, object]]] = {
            "base": {
                MANIFEST: {"domain": "google_home", "version": "1.15.0"},
                "hacs.json": HACS_JSON,
            }
        }
        self.parents: dict[str, str] = {}
        self.messages: dict[str, str] = {"base": "Add a feature (#1)"}
        self.master = "base"

    def get_branch(self, name: str) -> SimpleNamespace:
        """Return the newest commit of master."""
        assert name == "master"
        head = self.master
        return SimpleNamespace(
            commit=SimpleNamespace(
                sha=head,
                commit=SimpleNamespace(message=self.messages[head]),
                parents=[SimpleNamespace(sha=self.parents.get(head))],
            )
        )

    def get_contents(self, path: str, ref: str) -> SimpleNamespace:
        """Return a file at a commit."""
        return SimpleNamespace(decoded_content=json.dumps(self.files[ref][path]))

    def get_git_ref(self, ref: str) -> SimpleNamespace:
        """Return master, which only moves forward."""
        assert ref == "heads/master"
        return SimpleNamespace(edit=self._move_master)

    def _move_master(self, sha: str) -> None:
        ancestor = sha
        while ancestor != self.master:
            ancestor = self.parents[ancestor]
        self.master = sha

    def commit_files(
        self, parent: str, message: str, files: dict[str, dict[str, object]]
    ) -> GitCommit:
        """Stand in for publish_release.commit_files."""
        sha = f"commit{len(self.files)}"
        self.files[sha] = self.files[parent] | files
        self.parents[sha] = parent
        self.messages[sha] = message
        return cast(GitCommit, SimpleNamespace(sha=sha))

    def release(self, version: str) -> str:
        """Run update_manifests, return the commit to tag."""
        return publish_release.update_manifests(cast(Repository, self), version)


@pytest.fixture(name="repo")
def fixture_repo(monkeypatch: pytest.MonkeyPatch) -> FakeRepo:
    """Return a repository whose commits stay in memory."""
    monkeypatch.setattr(publish_release, "commit_files", FakeRepo.commit_files)
    return FakeRepo()


def test_release_commit_has_zip_settings_and_master_does_not(repo: FakeRepo) -> None:
    """Installs of the tag use the zip, installs of master the source archive."""
    tagged = repo.release("1.17.0")

    assert repo.parents[tagged] == "base"
    assert repo.parents[repo.master] == tagged
    hacs_json = HACS_JSON | {"homeassistant": package_version("homeassistant")}
    assert repo.files[tagged]["hacs.json"] == hacs_json | {
        "zip_release": True,
        "filename": "google_home.zip",
    }
    assert repo.files[repo.master]["hacs.json"] == hacs_json
    for sha in (tagged, repo.master):
        assert repo.files[sha][MANIFEST]["version"] == "1.17.0"


def test_rerun_reuses_release_commit(repo: FakeRepo) -> None:
    """A rerun tags the same commit; the next release makes new ones."""
    tagged = repo.release("1.17.0")
    master = repo.master

    assert repo.release("1.17.0") == tagged
    assert repo.master == master

    next_tagged = repo.release("1.17.1")
    assert repo.parents[next_tagged] == master
    assert repo.files[next_tagged][MANIFEST]["version"] == "1.17.1"


class FakeAsset:
    """An asset as GitHub stores it."""

    def __init__(self, release: FakeRelease, name: str, content: bytes) -> None:
        """Store the asset."""
        self.release = release
        self.name = name
        self.content = content

    def delete_asset(self) -> None:
        """Delete the asset."""
        self.release.assets.remove(self)

    def download_asset(self, path: str) -> None:
        """Download the asset."""
        Path(path).write_bytes(self.content)


class FakeRelease:
    """A release that stores what store returns for each upload."""

    def __init__(
        self, tag: str, store: Callable[[bytes], bytes | None] = lambda data: data
    ) -> None:
        """Create a draft release."""
        self.tag_name = tag
        self.name = f"RELEASE WITH GITHUB ACTIONS! {tag}"
        self.body = "Release notes"
        self.draft = True
        self.assets: list[FakeAsset] = []
        self.store = store
        self.published: dict[str, object] | None = None

    def get_assets(self) -> list[FakeAsset]:
        """Return the assets."""
        return list(self.assets)

    def upload_asset(self, path: str, content_type: str) -> None:
        """Upload an asset."""
        assert content_type == "application/zip"
        if (content := self.store(Path(path).read_bytes())) is not None:
            self.assets.append(FakeAsset(self, Path(path).name, content))

    def update_release(self, **kwargs: object) -> None:
        """Publish the release."""
        self.published = kwargs


@pytest.fixture(name="fetched")
def fixture_fetched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Return the refs main fetches, and build from HEAD instead.

    The release commit main tags is called "release".
    """
    refs: list[str] = []

    def fetch(ref: str) -> str:
        refs.append(ref)
        return "HEAD"

    monkeypatch.setattr(publish_release, "fetch", fetch)
    monkeypatch.setattr(
        publish_release, "update_manifests", lambda repo, version: "release"
    )
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.delenv("TAG", raising=False)
    return refs


def run_main(
    monkeypatch: pytest.MonkeyPatch,
    release: FakeRelease,
    draft: FakeRelease | None = None,
    tagged: str | None = None,
) -> int:
    """Run the script against a repository with this release, and this draft.

    The release's tag points at the commit tagged, or doesn't exist yet.
    """

    def get_git_ref(ref: str) -> SimpleNamespace:
        assert ref == f"tags/{release.tag_name}"
        if tagged is None:
            raise UnknownObjectException(404)
        return SimpleNamespace(object=SimpleNamespace(sha=tagged))

    repository = SimpleNamespace(
        get_releases=lambda: [draft or release],
        get_release=lambda tag: release if tag == release.tag_name else None,
        get_git_ref=get_git_ref,
    )
    monkeypatch.setattr(
        publish_release,
        "Github",
        lambda auth: SimpleNamespace(get_repo=lambda name: repository),
    )
    return publish_release.main()


@pytest.mark.parametrize("tagged", [None, "release"], ids=["new tag", "rerun"])
def test_publishes_after_attaching_zip(
    monkeypatch: pytest.MonkeyPatch, fetched: list[str], tagged: str | None
) -> None:
    """The draft is published on the release commit, with the zip attached."""
    release = FakeRelease(head_tag())

    assert run_main(monkeypatch, release, tagged=tagged) == 0

    assert fetched == ["release"]
    assert [asset.name for asset in release.assets] == ["google_home.zip"]
    assert release.published == {
        "name": head_tag(),
        "message": "Release notes",
        "draft": False,
        "target_commitish": "release",
    }


@pytest.mark.parametrize(
    ("store", "error"),
    [
        (lambda data: None, "{tag} has no google_home.zip after uploading it"),
        (
            lambda data: zip_of({"manifest.json": '{"version": "0.0.1"}'}),
            "google_home.zip has version 0.0.1, not {tag}",
        ),
    ],
    ids=["missing", "other version"],
)
@pytest.mark.usefixtures("fetched")
def test_does_not_publish_unless_stored_zip_matches(
    monkeypatch: pytest.MonkeyPatch,
    store: Callable[[bytes], bytes | None],
    error: str,
) -> None:
    """HACS and Home Assistant would fail to install a release without it."""
    release = FakeRelease(head_tag(), store)

    with pytest.raises(
        SystemExit, match=f"^{re.escape(error.format(tag=head_tag()))}$"
    ):
        run_main(monkeypatch, release)

    assert release.published is None


@pytest.mark.usefixtures("fetched")
def test_does_not_upload_zip_of_another_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A release named after another version keeps its draft and assets."""
    release = FakeRelease("v0.0.1")
    old = FakeAsset(release, "google_home.zip", b"old")
    release.assets.append(old)

    with pytest.raises(SystemExit, match="not v0.0.1$"):
        run_main(monkeypatch, release)

    assert release.assets == [old]
    assert release.published is None


def test_does_not_publish_on_tag_of_another_commit(
    monkeypatch: pytest.MonkeyPatch, fetched: list[str]
) -> None:
    """GitHub would keep the tag, so installs would get the other commit's code."""
    release = FakeRelease(head_tag())
    old = FakeAsset(release, "google_home.zip", b"old")
    release.assets.append(old)

    with pytest.raises(
        SystemExit,
        match=f"^{re.escape(head_tag())} already points at old, not the release commit",
    ):
        run_main(monkeypatch, release, tagged="old")

    assert not fetched
    assert release.assets == [old]
    assert release.published is None


def test_tag_replaces_zip_of_published_release(
    monkeypatch: pytest.MonkeyPatch, fetched: list[str], tmp_path: Path
) -> None:
    """With TAG set, only the zip of that release changes."""
    release = FakeRelease(head_tag())
    release.draft = False
    release.assets.append(FakeAsset(release, "google_home.zip", b"old"))
    monkeypatch.setenv("TAG", head_tag())
    monkeypatch.setattr(
        publish_release,
        "update_manifests",
        lambda repo, version: pytest.fail("master changed"),
    )

    draft = FakeRelease("v9.9.9")

    assert run_main(monkeypatch, release, draft) == 0

    assert fetched == [f"refs/tags/{head_tag()}"]
    assert not draft.assets
    assert draft.published is None
    assert [asset.name for asset in release.assets] == ["google_home.zip"]
    path = tmp_path / "google_home.zip"
    release.assets[0].download_asset(str(path))
    publish_release.check_zip(path, head_tag())
    assert release.published is None
