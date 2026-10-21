"""Resource packs use Minecraft compatibility, verified ZIPs and isolated destinations."""

import io
import json
import zipfile

import pytest

from src.hexlauncher.core.modrinth import ModrinthClient, ModrinthError
from src.hexlauncher.core.resource_packs import install_resource_pack
from tests.test_modrinth import Response, Transport, hashes


def pack_bytes():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": 34, "description": "Test"}}))
    return output.getvalue()


def pack_version(body):
    return {
        "id": "pack-v1", "game_versions": ["1.21.1"], "version_type": "release",
        "date_published": "2026-01-01",
        "files": [{
            "filename": "textures.zip", "primary": True, "hashes": hashes(body),
            "size": len(body), "url": "https://cdn.modrinth.com/textures.zip",
        }],
    }


def make_client(version, body):
    transport = Transport(lambda url, kwargs: Response([version]) if url.endswith("/version") else Response(body=body))
    return ModrinthClient(transport=transport), transport


def test_resource_search_ignores_fabric_filter():
    transport = Transport(Response({"hits": [{"title": "Textures"}]}))
    ModrinthClient(transport=transport).search_mods("textures", "Fabric", "1.21.1", project_type="resourcepack")
    facets = json.loads(transport.calls[0][1]["params"]["facets"])
    assert facets == [["project_type:resourcepack"], ["versions:1.21.1"]]


def test_verified_download_publishes_zip_in_selected_instance(tmp_path):
    body = pack_bytes()
    client, transport = make_client(pack_version(body), body)
    game = tmp_path / "selected-instance"
    installed = install_resource_pack(client, "project", "1.21.1", game)
    assert installed == game / "resourcepacks" / "textures.zip"
    assert installed.read_bytes() == body
    assert not (game / "pack.mcmeta").exists()
    params = transport.calls[0][1]["params"]
    assert "loaders" not in params
    assert json.loads(params["game_versions"]) == ["1.21.1"]
    second = install_resource_pack(client, "project", "1.21.1", game)
    assert second.name == "textures (1).zip"
    assert installed.read_bytes() == body


@pytest.mark.parametrize("failure", ["hash", "no-hash", "incompatible", "invalid-zip", "oversized", "traversal"])
def test_failed_download_or_validation_does_not_publish(tmp_path, failure):
    body = pack_bytes()
    if failure == "invalid-zip":
        body = b"not a resource pack"
    version = pack_version(body)
    file = version["files"][0]
    if failure == "hash":
        file["hashes"]["sha512"] = "0" * 128
    elif failure == "no-hash":
        file["hashes"] = {}
    elif failure == "incompatible":
        version["game_versions"] = ["1.20"]
    elif failure == "oversized":
        file["size"] = 513 * 1024**2
    elif failure == "traversal":
        file["filename"] = "../textures.zip"
    client, _ = make_client(version, body)
    game = tmp_path / "game"
    with pytest.raises((ModrinthError, ValueError)):
        install_resource_pack(client, "project", "1.21.1", game)
    assert not list(game.rglob("*.zip"))


def test_download_limit_also_applies_without_content_length(tmp_path):
    response = Response(body=b"too much data")
    response.headers = {}
    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"keep")
    with pytest.raises(ModrinthError, match="límite"):
        ModrinthClient(transport=Transport(response)).download_file(
            "https://cdn.modrinth.com/file.zip", destination, max_size=4,
        )
    assert destination.read_bytes() == b"keep"
    assert list(tmp_path.iterdir()) == [destination]
