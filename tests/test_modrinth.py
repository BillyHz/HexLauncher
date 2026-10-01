"""Offline regression tests for API filters, dependency graphs and safe installation."""

import hashlib
import json
import stat
import zipfile

import pytest
import requests

from src.hexlauncher.core.modrinth import API_BASE, ModrinthClient, ModrinthError, safe_path


class Response:
    def __init__(self, data=None, body=b"mod contents", status=200, chunks=None):
        self.data, self.body, self.status_code = data, body, status
        self.headers = {"content-length": str(len(body))}
        self.url = "https://cdn.modrinth.com/file.jar"
        self.chunks = chunks
        self.closed = False

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)

    def iter_content(self, chunk_size):
        for chunk in self.chunks if self.chunks is not None else [self.body]:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Transport:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.response(url, kwargs) if callable(self.response) else self.response
        if isinstance(response, Exception):
            raise response
        return response


def hashes(body):
    return {"sha512": hashlib.sha512(body).hexdigest(), "sha1": hashlib.sha1(body).hexdigest()}


def version(vid, dependencies=(), project=None):
    return {
        "id": vid,
        "project_id": project or vid,
        "loaders": ["fabric"],
        "game_versions": ["1.21"],
        "dependencies": list(dependencies),
        "date_published": "2026-01-01",
        "files": [
            {
                "filename": f"{vid}.jar",
                "url": f"https://cdn.modrinth.com/{vid}.jar",
                "primary": True,
                "hashes": hashes(b"mod contents"),
                "size": len(b"mod contents"),
            }
        ],
    }


def test_search_filters_pagination_and_user_agent():
    response = Response({"hits": [{"title": "Sodium"}]})
    transport = Transport(response)
    client = ModrinthClient(transport=transport)
    assert client.search_mods("sodium", "Fabric", "1.21", limit=10, offset=20)
    url, request = transport.calls[0]
    assert url == f"{API_BASE}/search"
    assert json.loads(request["params"]["facets"]) == [
        ["project_type:mod"],
        ["categories:fabric"],
        ["versions:1.21"],
    ]
    assert request["params"]["offset"] == 20
    assert "HexLauncher" in request["headers"]["User-Agent"]
    assert request["timeout"] == (10, 60)
    assert response.closed
    client.search_mods("pack", "Forge", "1.20.1", project_type="modpack")
    assert ["project_type:modpack"] in json.loads(transport.calls[-1][1]["params"]["facets"])


@pytest.mark.parametrize(
    "response",
    [
        requests.Timeout("timeout"),
        requests.ConnectionError("offline"),
        Response(status=404),
        Response(status=429),
        Response(ValueError()),
    ],
)
def test_network_and_json_errors(response):
    with pytest.raises(ModrinthError):
        ModrinthClient(transport=Transport(response)).search_mods("x", "fabric", "1.21")


def test_project_versions_filters_and_primary_jar():
    root = version("root")
    root["files"].insert(0, {"filename": "root-sources.jar", "file_type": "sources-jar"})
    transport = Transport(Response([root]))
    client = ModrinthClient(transport=transport)
    versions = client.get_project_versions("project", "Fabric", "1.21")
    assert json.loads(transport.calls[0][1]["params"]["loaders"]) == ["fabric"]
    assert client.primary_file(versions[0])["filename"] == "root.jar"


def dependency(vid=None, pid=None, kind="required"):
    return {"version_id": vid, "project_id": pid, "dependency_type": kind}


def graph_client(graph):
    def respond(url, kwargs):
        if "/project/" in url:
            return Response([graph["project-dependency"]])
        return Response(graph[url.rsplit("/", 1)[-1]])

    return ModrinthClient(transport=Transport(respond))


def test_recursive_dependencies_deduplicate_and_ignore_optional():
    graph = {
        "root": version("root", [dependency("a"), dependency("b"), dependency("optional", kind="optional")]),
        "a": version("a", [dependency("common")]),
        "b": version("b", [dependency("common")]),
        "common": version("common"),
    }
    result = graph_client(graph).resolve_dependencies("root", loader="fabric", game_version="1.21")
    assert [v["id"] for v in result] == ["common", "a", "b"]


def test_project_only_dependency_uses_parent_compatibility():
    graph = {
        "root": version("root", [dependency(pid="project")]),
        "project-dependency": version("project-dependency"),
    }
    client = graph_client(graph)
    assert client.resolve_dependencies("root")[0]["id"] == "project-dependency"
    request = client.transport.calls[1][1]["params"]
    assert json.loads(request["game_versions"]) == ["1.21"]


def test_dependency_cycle_fails():
    graph = {"root": version("root", [dependency("a")]), "a": version("a", [dependency("root")])}
    with pytest.raises(ModrinthError, match="circulares"):
        graph_client(graph).resolve_dependencies("root")


def test_dependency_incompatible_fails():
    graph = {"root": version("root", [dependency("a")]), "a": version("a")}
    graph["a"]["loaders"] = ["forge"]
    with pytest.raises(ModrinthError, match="incompatible"):
        graph_client(graph).resolve_dependencies("root")


def test_dependency_conflict_fails():
    graph = {
        "root": version("root", [dependency("a"), dependency("b")]),
        "a": version("a", project="same"),
        "b": version("b", project="same"),
    }
    with pytest.raises(ModrinthError, match="conflicto"):
        graph_client(graph).resolve_dependencies("root")


def test_verified_download_atomic_and_progress(tmp_path):
    body = b"verified mod"
    dest = tmp_path / "mod.jar"
    dest.write_bytes(b"old mod")
    calls = []
    client = ModrinthClient(transport=Transport(Response(body=body)))
    client.download_file(
        "https://cdn.modrinth.com/mod.jar",
        dest,
        hashes(body)["sha512"],
        lambda done, total: calls.append((done, total)),
        expected_hash_sha1=hashes(body)["sha1"],
    )
    assert dest.read_bytes() == body
    assert calls[-1] == (len(body), len(body))
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("failure", ["hash", "timeout", "truncated"])
def test_bad_download_preserves_existing_file(tmp_path, failure):
    dest = tmp_path / "mod.jar"
    dest.write_bytes(b"old")
    chunks = [b"partial", requests.Timeout("interrupted")] if failure == "timeout" else [b"bad"]
    client = ModrinthClient(transport=Transport(Response(body=b"bad", chunks=chunks)))
    with pytest.raises(ModrinthError):
        client.download_file(
            "https://cdn.modrinth.com/mod.jar",
            dest,
            hashes(b"expected")["sha512"] if failure == "hash" else None,
            expected_size=99 if failure == "truncated" else None,
        )
    assert dest.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [dest]


def test_sha1_fallback(tmp_path):
    body = b"mod contents"
    client = ModrinthClient(transport=Transport(Response(body=body)))
    client.download_file(
        "https://cdn.modrinth.com/mod.jar", tmp_path / "mod.jar", expected_hash_sha1=hashes(body)["sha1"]
    )


def pack_index():
    return {
        "formatVersion": 1,
        "game": "minecraft",
        "name": "Test pack",
        "versionId": "v1",
        "dependencies": {"minecraft": "1.21", "fabric-loader": "0.16.0"},
        "files": [],
    }


def write_pack(path, index, overrides=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("modrinth.index.json", json.dumps(index))
        for name, data in (overrides or {}).items():
            archive.writestr(name, data)
    return path


def test_mrpack_hashes_overrides_client_environment_and_metadata(tmp_path):
    index = pack_index()
    body = b"pack mod"
    file = {
        "path": "mods/mod.jar",
        "hashes": hashes(body),
        "fileSize": len(body),
        "downloads": ["https://cdn.modrinth.com/mod.jar"],
    }
    index["files"] = [file, {**file, "path": "mods/server.jar", "env": {"client": "unsupported"}}]
    pack = write_pack(
        tmp_path / "pack.mrpack",
        index,
        {
            "overrides/config/example.txt": "base",
            "client-overrides/config/example.txt": "client",
            "server-overrides/server.txt": "server",
        },
    )
    client = ModrinthClient(transport=Transport(Response(body=body)))
    progress = []
    destination = tmp_path / "instance"
    assert client.install_mrpack(pack, destination, lambda d, t: progress.append((d, t))) == index
    assert (destination / "mods/mod.jar").read_bytes() == body
    assert not (destination / "mods/server.jar").exists()
    assert (destination / "config/example.txt").read_text() == "client"
    assert not (destination / "server.txt").exists()
    assert json.loads((destination / ".hexpack.json").read_text())["dependencies"] == index["dependencies"]
    assert progress[-1] == (3, 3)


@pytest.mark.parametrize(
    "path",
    [
        "../escape.jar",
        "/escape.jar",
        "C:/escape.jar",
        "mods/../../escape.jar",
        "mods\\escape.jar",
        "mods/CON.jar",
        "mods/mod.jar:stream",
    ],
)
def test_mrpack_rejects_unsafe_paths(tmp_path, path):
    index = pack_index()
    index["files"] = [{"path": path}]
    pack = write_pack(tmp_path / "pack.mrpack", index)
    with pytest.raises(ModrinthError):
        ModrinthClient().install_mrpack(pack, tmp_path / "instance")
    assert not (tmp_path / "instance").exists()


def test_mrpack_corrupt_download_not_published(tmp_path):
    index = pack_index()
    index["files"] = [
        {
            "path": "mods/mod.jar",
            "hashes": hashes(b"expected"),
            "fileSize": 3,
            "downloads": ["https://cdn.modrinth.com/mod.jar"],
        }
    ]
    pack = write_pack(tmp_path / "pack.mrpack", index)
    with pytest.raises(ModrinthError):
        ModrinthClient(transport=Transport(Response(body=b"bad"))).install_mrpack(pack, tmp_path / "instance")
    assert not (tmp_path / "instance").exists()
    assert not list(tmp_path.glob(".hex-pack-*"))


def test_mrpack_rejects_symlink_override(tmp_path):
    pack = write_pack(tmp_path / "pack.mrpack", pack_index())
    with zipfile.ZipFile(pack, "a") as archive:
        info = zipfile.ZipInfo("overrides/config/link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../../escape")
    with pytest.raises(ModrinthError, match="simbólicos"):
        ModrinthClient().install_mrpack(pack, tmp_path / "instance")


def test_mrpack_refuses_existing_instance(tmp_path):
    instance = tmp_path / "instance"
    instance.mkdir()
    sentinel = instance / "options.txt"
    sentinel.write_text("keep")
    with pytest.raises(ModrinthError, match="ya existe"):
        ModrinthClient().install_mrpack("unused.mrpack", instance)
    assert sentinel.read_text() == "keep"


def test_mrpack_mirror_fallback(tmp_path):
    body = b"mod"
    index = pack_index()
    index["files"] = [
        {
            "path": "mods/mod.jar",
            "hashes": hashes(body),
            "fileSize": len(body),
            "downloads": ["https://mirror.invalid/mod.jar", "https://cdn.modrinth.com/mod.jar"],
        }
    ]
    transport = Transport(lambda url, _: requests.Timeout() if "mirror" in url else Response(body=body))
    pack = write_pack(tmp_path / "pack.mrpack", index)
    ModrinthClient(transport=transport).install_mrpack(pack, tmp_path / "instance")
    assert len(transport.calls) == 2


def test_mod_dependency_download_failure_preserves_library(tmp_path):
    root, dep = version("root", [dependency("dep")]), version("dep")

    def respond(url, _):
        if "/project/" in url:
            return Response([root])
        if url.endswith("/version/root"):
            return Response(root)
        if url.endswith("/version/dep"):
            return Response(dep)
        return Response(body=b"mod contents" if url.endswith("dep.jar") else b"bad")

    library = tmp_path / "mods"
    library.mkdir()
    (library / "dep.jar").write_bytes(b"original")
    with pytest.raises(ModrinthError):
        ModrinthClient(transport=Transport(respond)).install_mod("project", "fabric", "1.21", library)
    assert (library / "dep.jar").read_bytes() == b"original"
    assert not (library / "root.jar").exists()


def test_safe_path_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(ModrinthError):
        safe_path(root, "link/escape.jar")


def install_client(root, graph=None):
    graph = {root["id"]: root, **(graph or {})}

    def respond(url, _):
        if "/project/" in url:
            return Response([root])
        if "/version/" in url:
            return Response(graph[url.rsplit("/", 1)[-1]])
        return Response(body=b"mod contents")

    return ModrinthClient(transport=Transport(respond))


def test_mod_update_replaces_previous_jar_and_preserves_manual(tmp_path):
    (tmp_path / "manual.jar").write_bytes(b"manual")
    install_client(version("old", project="project")).install_mod("project", "fabric", "1.21", tmp_path)
    client = install_client(version("new", project="project"))
    client.install_mod("project", "fabric", "1.21", tmp_path)
    assert not (tmp_path / "old.jar").exists()
    assert (tmp_path / "new.jar").exists()
    assert (tmp_path / "manual.jar").read_bytes() == b"manual"
    assert client.read_installed_mods(tmp_path)["project"]["version_id"] == "new"


def test_mod_commit_failure_rolls_back_jars_and_registry(tmp_path, monkeypatch):
    import os

    client = install_client(version("old", project="project"))
    client.install_mod("project", "fabric", "1.21", tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    original = os.replace

    def fail_commit(source, target):
        if str(target).endswith(".hexmods.json"):
            raise OSError("simulated registry failure")
        return original(source, target)

    monkeypatch.setattr(os, "replace", fail_commit)
    with pytest.raises(ModrinthError, match="restauraron"):
        install_client(version("new", project="project")).install_mod("project", "fabric", "1.21", tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_install_does_not_overwrite_manual_jar(tmp_path):
    (tmp_path / "root.jar").write_bytes(b"manual")
    with pytest.raises(ModrinthError, match="manual"):
        install_client(version("root")).install_mod("root", "fabric", "1.21", tmp_path)
    assert (tmp_path / "root.jar").read_bytes() == b"manual"


def test_installed_exact_dependency_blocks_update_and_uninstall(tmp_path):
    dep = version("dep-v1", project="dep")
    root = version("root", [dependency("dep-v1")])
    client = install_client(root, {"dep-v1": dep})
    client.install_mod("root", "fabric", "1.21", tmp_path)
    with pytest.raises(ModrinthError, match="conflicto"):
        install_client(version("dep-v2", project="dep")).install_mod("dep", "fabric", "1.21", tmp_path)
    with pytest.raises(ModrinthError, match="requiere"):
        client.uninstall_mod(tmp_path, "dep-v1.jar")
    client.uninstall_mod(tmp_path, "root.jar")
    client.uninstall_mod(tmp_path, "dep-v1.jar")
    assert client.read_installed_mods(tmp_path) == {}


def test_installed_incompatible_dependency_blocks_future_install(tmp_path):
    root = version("root", [dependency(pid="blocked", kind="incompatible")])
    install_client(root).install_mod("root", "fabric", "1.21", tmp_path)
    with pytest.raises(ModrinthError, match="incompatibles"):
        install_client(version("blocked-v1", project="blocked")).install_mod(
            "blocked", "fabric", "1.21", tmp_path
        )
    assert not (tmp_path / "blocked-v1.jar").exists()
