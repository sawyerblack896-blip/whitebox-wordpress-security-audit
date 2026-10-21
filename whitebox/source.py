"""Official source acquisition and immutable, bounded snapshots."""

from __future__ import annotations

import hashlib
import fcntl
import io
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from .util import digest_file, now, tree_digest, write_json


MAX_DOWNLOAD = 100 * 1024 * 1024
MAX_FILES = 20000
MAX_EXPANDED = 700 * 1024 * 1024
MAX_GIT_DOWNLOAD = 512 * 1024 * 1024
MAX_GIT_FILES = 120000
MAX_GIT_EXPANDED = 5 * 1024 * 1024 * 1024
ALLOWED_GIT_HOSTS = {"github.com", "gitlab.com", "codeberg.org"}
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{1,99}\Z")
COMMIT = re.compile(r"[0-9a-fA-F]{40}\Z")


class SourceError(ValueError):
    pass


def fetch_https(url: str, maximum: int = MAX_DOWNLOAD, allowed_hosts: set[str] | None = None) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SourceError("source URL must be credential-free HTTPS")
    if allowed_hosts and parsed.hostname not in allowed_hosts:
        raise SourceError(f"unapproved source host: {parsed.hostname}")
    request = urllib.request.Request(url, headers={"User-Agent": "whitebox-harness/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or (allowed_hosts and final.hostname not in allowed_hosts):
            raise SourceError("source redirected outside approved HTTPS hosts")
        length = response.headers.get("Content-Length")
        if length and int(length) > maximum:
            raise SourceError("source exceeds size limit")
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise SourceError("source exceeds size limit")
    return data


def extract_zip_safe(archive: bytes, dest: Path, *, max_files: int = MAX_FILES,
                     max_expanded: int = MAX_EXPANDED,
                     max_single: int = MAX_DOWNLOAD) -> None:
    total = 0
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        infos = bundle.infolist()
        if len(infos) > max_files:
            raise SourceError("too many files in archive")
        seen: set[str] = set()
        links: list[tuple[Path, str]] = []
        for entry in infos:
            name = entry.filename
            rel = PurePosixPath(name)
            parts = rel.parts
            if (not parts or rel.is_absolute() or any(p in {".", "..", ""} for p in parts)
                    or "\\" in name or "\x00" in name or ":" in parts[0]):
                raise SourceError(f"unsafe archive path: {name}")
            if name in seen:
                raise SourceError(f"duplicate archive path: {name}")
            seen.add(name)
            mode = (entry.external_attr >> 16) & 0o170000
            if mode not in {0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK}:
                raise SourceError(f"special file in archive: {name}")
            total += entry.file_size
            if total > max_expanded or entry.file_size > max_single:
                raise SourceError("archive expansion exceeds limit")
            target = dest.joinpath(*parts)
            if mode == stat.S_IFLNK:
                raw = bundle.read(entry)
                try:
                    link = raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise SourceError(f"invalid symlink target: {name}") from exc
                if (not link or link.startswith("/") or "\\" in link or "\x00" in link
                        or posixpath.normpath(posixpath.join(str(rel.parent), link))
                        in {".", ".."}
                        or posixpath.normpath(posixpath.join(str(rel.parent), link)).startswith("../")):
                    raise SourceError(f"symlink escapes source tree: {name}")
                links.append((target, link))
            elif entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                os.chmod(target, 0o444)
        for target, link in links:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise SourceError(f"symlink path collides with archive content: {target}")
            target.symlink_to(link)
        root = dest.resolve()
        for target, _ in links:
            if not target.resolve(strict=False).is_relative_to(root):
                raise SourceError(f"symlink resolves outside source tree: {target}")
    for directory in dest.rglob("*"):
        if not directory.is_symlink() and directory.is_dir():
            os.chmod(directory, 0o555)


def wporg_package(slug: str) -> tuple[bytes, dict]:
    if not SLUG.fullmatch(slug):
        raise SourceError("invalid WordPress.org plugin slug")
    query = urllib.parse.urlencode({
        "action": "plugin_information", "request[slug]": slug,
        "request[fields][sections]": "0", "request[fields][versions]": "0"})
    api_url = f"https://api.wordpress.org/plugins/info/1.2/?{query}"
    raw = fetch_https(api_url, 4 * 1024 * 1024, {"api.wordpress.org"})
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceError("WordPress.org returned invalid plugin metadata") from exc
    if not isinstance(info, dict) or info.get("slug") != slug or not info.get("version"):
        raise SourceError("WordPress.org did not confirm this slug/version")
    version = str(info["version"])
    package_url = str(info.get("download_link", ""))
    if not package_url:
        raise SourceError("WordPress.org did not provide an official download")
    archive = fetch_https(package_url, MAX_DOWNLOAD, {"downloads.wordpress.org"})
    return archive, {
        "kind": "wporg", "slug": slug, "revision": version,
        "metadata_url": api_url, "package_url": package_url,
        "active_installs": info.get("active_installs"), "last_updated": info.get("last_updated"),
        "requires_plugins": info.get("requires_plugins") if isinstance(info.get("requires_plugins"), list) else [],
        "fetched_at": now(), "metadata_sha256": hashlib.sha256(raw).hexdigest(),
    }


def git_package(url: str, revision: str | None = None) -> tuple[bytes, dict]:
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_GIT_HOSTS
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise SourceError("Git source must be a credential-free HTTPS URL on an approved host")
    if revision is not None and not COMMIT.fullmatch(revision):
        raise SourceError("Git revision must be a 40-character commit SHA")
    if revision is not None and parsed.hostname == "github.com":
        parts = parsed.path.strip("/").removesuffix(".git").split("/")
        if (len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part)
                                      for part in parts)):
            raise SourceError("GitHub source must name one owner and repository")
        archive_url = f"https://codeload.github.com/{parts[0]}/{parts[1]}/zip/{revision.lower()}"
        data = fetch_https(archive_url, MAX_GIT_DOWNLOAD, {"codeload.github.com"})
        return data, {"kind": "git", "url": url, "revision": revision.lower(),
                      "requested_revision": revision.lower(), "archive_url": archive_url,
                      "archive_strip_root": True, "fetched_at": now()}
    with tempfile.TemporaryDirectory(prefix="whitebox-git-") as temp:
        clone = Path(temp) / "repo"
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
        base = ["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=",
                "-c", "protocol.file.allow=never"]
        try:
            subprocess.run(base + ["clone", "--quiet", "--no-checkout", "--filter=blob:none",
                                   "--", url, str(clone)], env=env, timeout=180,
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            resolved = subprocess.check_output(base + ["-C", str(clone), "rev-parse", "HEAD^{commit}"],
                                               env=env, timeout=15, text=True).strip()
            if revision is not None and resolved.lower() != revision.lower():
                # An explicitly requested older commit must exist in the fetched object store.
                resolved = subprocess.check_output(base + ["-C", str(clone), "rev-parse",
                                                       revision + "^{commit}"], env=env,
                                                    timeout=15, text=True).strip()
            if revision is not None and resolved.lower() != revision.lower():
                raise SourceError("Git revision did not resolve to requested commit")
            data = subprocess.check_output(base + ["-C", str(clone), "archive", "--format=zip",
                                                   resolved], env=env, timeout=120)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise SourceError(f"Git fetch/archive failed: {type(exc).__name__}") from exc
    if len(data) > MAX_GIT_DOWNLOAD:
        raise SourceError("Git archive exceeds size limit")
    return data, {"kind": "git", "url": url, "revision": resolved.lower(),
                  "requested_revision": revision.lower() if revision else None, "fetched_at": now()}


def create_snapshot(root: Path, source_input: str, revision: str | None = None) -> tuple[Path, Path, Path, dict]:
    if source_input.startswith("wporg:"):
        if revision:
            raise SourceError("wporg source resolves its own current stable version")
        archive, manifest = wporg_package(source_input.split(":", 1)[1])
    else:
        archive, manifest = git_package(source_input, revision)
    package_sha = hashlib.sha256(archive).hexdigest()
    place = root / "source" / package_sha
    with (root / "source" / f".{package_sha}.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if place.exists():
            existing = json.loads((place / "manifest.json").read_text())
            if existing.get("package_sha256") != package_sha or digest_file(place / "package.zip") != package_sha:
                raise SourceError("cached source package integrity mismatch")
            return place / "tree", place / "package.zip", place / "manifest.json", existing
        temp = Path(tempfile.mkdtemp(prefix=".source-", dir=root / "source"))
        try:
            tree = temp / "tree"
            tree.mkdir()
            if manifest["kind"] == "git":
                extract_zip_safe(archive, tree, max_files=MAX_GIT_FILES,
                                 max_expanded=MAX_GIT_EXPANDED, max_single=MAX_GIT_DOWNLOAD)
                if manifest.get("archive_strip_root"):
                    roots = list(tree.iterdir())
                    if len(roots) != 1 or not roots[0].is_dir() or roots[0].is_symlink():
                        raise SourceError("Git archive did not contain one source root")
                    top = roots[0]
                    for child in top.iterdir():
                        child.rename(tree / child.name)
                    top.rmdir()
            else:
                extract_zip_safe(archive, tree)
            (temp / "package.zip").write_bytes(archive)
            manifest.update({"package_sha256": package_sha, "tree_sha256": tree_digest(tree),
                             "package_size": len(archive)})
            write_json(temp / "manifest.json", manifest)
            os.chmod(temp / "package.zip", 0o444)
            os.chmod(temp / "manifest.json", 0o444)
            os.replace(temp, place)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise
        return place / "tree", place / "package.zip", place / "manifest.json", manifest
