#!/usr/bin/env python3
"""Update manifest.json and create new Github Release."""
from __future__ import annotations

from importlib.metadata import version as package_version
import json
import os
import sys

from github import Auth, Github, InputGitTreeElement
from github.ContentFile import ContentFile
from github.GitRelease import GitRelease
from github.Repository import Repository


def main() -> int:
    """Main function"""
    github_token = os.environ.get("GITHUB_TOKEN")
    assert github_token is not None, "GITHUB_TOKEN is not set"
    print("Fetching draft release...")
    github = Github(auth=Auth.Token(github_token))
    repo = github.get_repo("leikoilja/ha-google-home")
    release = repo.get_releases()[0]
    if not release.draft:
        print("The latest release is not a draft!")
        return 1
    version = release.title.split()[-1].lstrip("v")
    update_manifests(repo, version)
    publish_release(release)
    return 0


def update_manifests(repo: Repository, version: str) -> None:
    """Update manifest.json and hacs.json"""
    print("Updating manifest.json...")
    manifest = repo.get_contents("custom_components/google_home/manifest.json")
    assert isinstance(manifest, ContentFile)
    manifest_json = json.loads(manifest.decoded_content)
    manifest_json["version"] = version
    manifest_json["requirements"] = [
        f"glocaltokens=={package_version('glocaltokens')}",
    ]
    updated_manifest = json.dumps(manifest_json, indent=2) + "\n"

    print("Updating hacs.json...")
    hacs_config = repo.get_contents("hacs.json")
    assert isinstance(hacs_config, ContentFile)
    hacs_json = json.loads(hacs_config.decoded_content)
    hacs_json["homeassistant"] = package_version("homeassistant")
    updated_hacs_config = json.dumps(hacs_json, indent=2) + "\n"

    branch = repo.get_branch("master")

    # Disable branch protection before commit
    branch.remove_admin_enforcement()

    # Create commit
    elements = []
    for file_path, content in [
        (manifest.path, updated_manifest),
        (hacs_config.path, updated_hacs_config),
    ]:
        blob = repo.create_git_blob(content, "utf-8")
        element = InputGitTreeElement(
            path=file_path, mode="100644", type="blob", sha=blob.sha
        )
        elements.append(element)
    head_sha = branch.commit.sha
    base_tree = repo.get_git_tree(sha=head_sha)
    tree = repo.create_git_tree(elements, base_tree)
    parent = repo.get_git_commit(sha=head_sha)
    commit = repo.create_git_commit(f"Release v{version}", tree, [parent])
    master_ref = repo.get_git_ref(f"heads/{branch.name}")
    master_ref.edit(sha=commit.sha)

    # Re-enable branch protection
    branch.set_admin_enforcement()


def publish_release(release: GitRelease) -> None:
    """Publish draft release"""
    print("Publishing new release...")
    release.update_release(
        name=release.title.split()[-1],
        message=release.body,
        draft=False,
    )


if __name__ == "__main__":
    sys.exit(main())
