#!/usr/bin/env python3
"""Update manifest.json, attach google_home.zip and publish the Github Release.

With TAG set, rebuild google_home.zip for that published release instead.
"""

from importlib.metadata import version as package_version
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from github import Auth, Github, InputGitTreeElement
from github.GitCommit import GitCommit
from github.GitRelease import GitRelease
from github.Repository import Repository

from homeassistant.util.json import JsonObjectType, json_loads_object

INTEGRATION_PATH = "custom_components/google_home"
MANIFEST_PATH = f"{INTEGRATION_PATH}/manifest.json"
ZIP_NAME = "google_home.zip"
# HACS and Home Assistant read hacs.json at the version they install
ZIP_RELEASE: JsonObjectType = {"zip_release": True, "filename": ZIP_NAME}


def main() -> int:
    """Run main function."""
    github_token = os.environ.get("GITHUB_TOKEN")
    assert github_token is not None, "GITHUB_TOKEN is not set"
    github = Github(auth=Auth.Token(github_token))
    repo = github.get_repo("leikoilja/ha-google-home")
    if tag := os.environ.get("TAG"):
        print(f"Attaching {ZIP_NAME} to {tag}...")
        attach_zip(repo.get_release(tag), fetch(f"refs/tags/{tag}"))
        return 0
    print("Fetching draft release...")
    release = repo.get_releases()[0]
    if not release.draft:
        print("The latest release is not a draft!")
        return 1
    version = release.name.split()[-1].lstrip("v")
    release_sha = update_manifests(repo, version)
    attach_zip(release, fetch(release_sha))
    publish_release(release, release_sha)
    return 0


def cleanup_message(version: str) -> str:
    """Return the message of the commit after the release commit."""
    return (
        f"Use the source archive for master again after v{version}\n\n"
        f"The v{version} release commit adds zip_release and filename to "
        f"hacs.json, so HACS and Home Assistant install that release from "
        f"{ZIP_NAME}. Remove them again, so installs of master keep using "
        "the source archive."
    )


def update_manifests(repo: Repository, version: str) -> str:
    """Commit the new version to master and return the release commit to tag.

    The release commit also adds the zip settings to hacs.json, and the commit
    after it removes them. Master moves straight to the second commit.
    """
    head = repo.get_branch("master").commit
    if head.commit.message.strip() == cleanup_message(version):
        print("Reusing the release commit of an earlier run...")
        return head.parents[0].sha

    print("Updating manifest.json...")
    manifest = read_json(repo, MANIFEST_PATH, head.sha)
    manifest["version"] = version
    manifest["requirements"] = [
        f"glocaltokens=={package_version('glocaltokens')}",
    ]

    print("Updating hacs.json...")
    hacs_config = read_json(repo, "hacs.json", head.sha)
    hacs_config["homeassistant"] = package_version("homeassistant")

    release_commit = commit_files(
        repo,
        head.sha,
        f"Release v{version}",
        {MANIFEST_PATH: manifest, "hacs.json": hacs_config | ZIP_RELEASE},
    )
    cleanup_commit = commit_files(
        repo,
        release_commit.sha,
        cleanup_message(version),
        {"hacs.json": hacs_config},
    )
    repo.get_git_ref("heads/master").edit(sha=cleanup_commit.sha)
    return release_commit.sha


def read_json(repo: Repository, path: str, ref: str) -> JsonObjectType:
    """Read a JSON file at a commit."""
    content = repo.get_contents(path, ref=ref)
    assert not isinstance(content, list)
    return json_loads_object(content.decoded_content)


def commit_files(
    repo: Repository, parent: str, message: str, files: dict[str, JsonObjectType]
) -> GitCommit:
    """Commit JSON files on top of a commit, without moving any branch."""
    elements = [
        InputGitTreeElement(
            path=path,
            mode="100644",
            type="blob",
            content=json.dumps(content, indent=2) + "\n",
        )
        for path, content in files.items()
    ]
    tree = repo.create_git_tree(elements, repo.get_git_tree(sha=parent))
    return repo.create_git_commit(message, tree, [repo.get_git_commit(sha=parent)])


def fetch(ref: str) -> str:
    """Fetch a commit or tag from GitHub, and return the name to read it with."""
    subprocess.run(["git", "fetch", "--no-tags", "origin", ref], check=True)
    return "FETCH_HEAD"


def build_zip(ref: str, path: Path) -> None:
    """Zip the integration at a commit, with its files at the root of the zip."""
    subprocess.run(
        [
            "git",
            "archive",
            "--format=zip",
            f"--output={path}",
            f"{ref}:{INTEGRATION_PATH}",
        ],
        check=True,
    )


def check_zip(path: Path, tag: str) -> None:
    """Stop unless the zip installs as the version the tag names."""
    with ZipFile(path) as archive:
        if "manifest.json" not in archive.namelist():
            sys.exit(f"{ZIP_NAME} has no manifest.json at its root")
        version = json_loads_object(archive.read("manifest.json"))["version"]
    if f"v{version}" != tag:
        sys.exit(f"{ZIP_NAME} has version {version}, not {tag}")


def attach_zip(release: GitRelease, ref: str) -> None:
    """Attach google_home.zip built from ref, and check the copy GitHub stores."""
    with TemporaryDirectory() as temp_dir:
        built = Path(temp_dir, ZIP_NAME)
        build_zip(ref, built)
        check_zip(built, release.tag_name)

        # GitHub refuses a second asset with the same name
        for asset in release.get_assets():
            if asset.name == ZIP_NAME:
                print(f"Deleting the old {ZIP_NAME}...")
                asset.delete_asset()
        print(f"Uploading {ZIP_NAME}...")
        release.upload_asset(str(built), content_type="application/zip")

        stored = Path(temp_dir, "stored.zip")
        for asset in release.get_assets():
            if asset.name == ZIP_NAME:
                asset.download_asset(str(stored))
                check_zip(stored, release.tag_name)
                return
        sys.exit(f"{release.tag_name} has no {ZIP_NAME} after uploading it")


def publish_release(release: GitRelease, release_sha: str) -> None:
    """Publish draft release, tagging the release commit."""
    print("Publishing new release...")
    release.update_release(
        name=release.name.split()[-1],
        message=release.body,
        draft=False,
        target_commitish=release_sha,
    )


if __name__ == "__main__":
    sys.exit(main())
