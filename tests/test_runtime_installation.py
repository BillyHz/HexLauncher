"""Failure-injection tests for Java installation and mod synchronization."""

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from src.hexlauncher.core import filesystem, jdk


class Response:
    def __init__(self, body=b"", data=None):
        self.body, self.data = body, data
        self.text = body.decode(errors="replace")
        self.url = "https://example.org/java.zip"
        self.headers = {"content-length": str(len(body))}

    def raise_for_status(self):
        pass

    def json(self):
        return self.data

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def java_zip(extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("temurin-runtime/bin/java.exe", b"MZverified java")
        archive.writestr("temurin-runtime/release", "JAVA_VERSION=21")
        for name, body in (extra or {}).items():
            archive.writestr(name, body)
    return stream.getvalue()


class JavaTransport:
    def __init__(self, body, checksum=None):
        self.body = body
        self.checksum = checksum or hashlib.sha256(body).hexdigest()

    def get(self, url, **kwargs):
        if url == jdk.ASSETS_URL:
            return Response(
                data=[
                    {
                        "binary": {
                            "package": {"link": "https://example.org/java.zip", "checksum": self.checksum}
                        }
                    }
                ]
            )
        return Response(body=self.body)


def test_java_staging_ignores_unrelated_old_directory(tmp_path):
    old = tmp_path / "jdk-21-old"
    old.mkdir()
    (old / "sentinel").write_text("keep")
    java = tmp_path / "HexJDK"
    java.mkdir()
    (java / "partial").write_text("incomplete")
    result = jdk.install_jdk(java, transport=JavaTransport(java_zip()))
    assert Path(result).read_bytes() == b"MZverified java"
    assert not (java / "partial").exists()
    assert (old / "sentinel").read_text() == "keep"
    assert not list(tmp_path.glob(".hex-java-*"))


def test_java_hash_failure_preserves_previous_runtime(tmp_path):
    java = tmp_path / "HexJDK"
    java.mkdir()
    marker = java / "original"
    marker.write_text("keep")
    with pytest.raises(RuntimeError, match="SHA-256"):
        jdk.install_jdk(java, transport=JavaTransport(java_zip(), "0" * 64))
    assert marker.read_text() == "keep"
    assert not list(tmp_path.glob(".hex-java-*"))


def test_java_traversal_never_published(tmp_path):
    java = tmp_path / "HexJDK"
    with pytest.raises(RuntimeError):
        jdk.install_jdk(java, transport=JavaTransport(java_zip({"../escape.txt": "evil"})))
    assert not java.exists()
    assert not (tmp_path / "escape.txt").exists()


def test_java_zip_requires_real_runtime_root(tmp_path):
    with pytest.raises(RuntimeError):
        jdk.install_jdk(tmp_path / "HexJDK", transport=JavaTransport(b"not a zip"))


def test_existing_java_needs_no_network(tmp_path):
    executable = tmp_path / "HexJDK/bin/java.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    assert jdk.install_jdk(executable.parent.parent, transport=object()) == str(executable)


def test_sync_preserves_non_jars_and_mirrors_library(tmp_path):
    source, destination = tmp_path / "library", tmp_path / "mods"
    source.mkdir()
    destination.mkdir()
    (source / "NEW.JAR").write_bytes(b"new")
    (destination / "old.jar").write_bytes(b"old")
    (destination / "config.txt").write_text("keep")
    assert filesystem.sync_mods(source, destination) == 1
    assert (destination / "NEW.JAR").read_bytes() == b"new"
    assert not (destination / "old.jar").exists()
    assert (destination / "config.txt").read_text() == "keep"


def test_sync_copy_failure_does_not_remove_originals(tmp_path, monkeypatch):
    source, destination = tmp_path / "library", tmp_path / "mods"
    source.mkdir()
    destination.mkdir()
    (source / "new.jar").write_bytes(b"new")
    (destination / "old.jar").write_bytes(b"old")
    monkeypatch.setattr(
        filesystem.shutil, "copy2", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full"))
    )
    with pytest.raises(RuntimeError, match="sincronizar"):
        filesystem.sync_mods(source, destination)
    assert (destination / "old.jar").read_bytes() == b"old"
    assert not (destination / "new.jar").exists()


def test_directory_publish_failure_rolls_back(tmp_path, monkeypatch):
    staged, destination = tmp_path / "staged", tmp_path / "mods"
    staged.mkdir()
    destination.mkdir()
    (staged / "new.jar").write_bytes(b"new")
    (destination / "old.jar").write_bytes(b"old")
    original = filesystem.os.replace

    def replace(source, target):
        if Path(source) == staged:
            raise OSError("locked")
        return original(source, target)

    monkeypatch.setattr(filesystem.os, "replace", replace)
    with pytest.raises(RuntimeError, match="publicar"):
        filesystem.replace_directory(staged, destination)
    assert (destination / "old.jar").read_bytes() == b"old"
    assert not (destination / "new.jar").exists()


def test_directory_staging_inside_destination_rejected(tmp_path):
    destination = tmp_path / "mods"
    staged = destination / "staged"
    staged.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="Rutas"):
        filesystem.replace_directory(staged, destination)
    assert staged.exists()
