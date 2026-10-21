"""Use the agent-scoped API without exposing secrets or unrelated tunnels."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.hexlauncher.core.playit import API, agent_tunnels, minecraft_tunnel
from src.hexlauncher.core.server_manager import MinecraftServerManager


def tunnel(**values):
    return {"display_address": "friends.tun.ply.gg", "port_type": "tcp", "disabled_reason": None,
            "agent_config": {"fields": [{"name": "local_ip", "value": "127.0.0.1"},
                                        {"name": "local_port", "value": "25565"}]}, **values}


def test_address_comes_from_real_agent_fields_and_accepts_custom_domains():
    assert minecraft_tunnel([tunnel()]) == ("friends.tun.ply.gg", False)
    assert minecraft_tunnel([tunnel(display_address="minecraft.example.org:25570")]) == ("minecraft.example.org:25570", False)


@pytest.mark.parametrize("change", ["disabled", "udp", "other-port", "other-host", "invalid-address", "invalid-port"])
def test_only_this_servers_enabled_tcp_tunnel_is_published(change):
    value = deepcopy(tunnel())
    if change == "disabled":
        value["disabled_reason"] = "disabled by user"
    elif change == "udp":
        value["port_type"] = "udp"
    elif change == "other-port":
        value["agent_config"]["fields"][1]["value"] = "25566"
    elif change == "other-host":
        value["agent_config"]["fields"][0]["value"] = "192.168.1.5"
    elif change == "invalid-port":
        value["display_address"] = "friends.tun.ply.gg:99999"
    else:
        value["display_address"] = "https://example.org/"
    assert minecraft_tunnel([value]) == ("", change == "disabled")


class Response:
    status_code = 200

    def json(self):
        return {"status": "success", "data": {"tunnels": [tunnel()]}}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_lookup_uses_only_official_origin_with_no_redirects(tmp_path):
    path = tmp_path / "playit.toml"
    path.write_text('secret_key = "' + "a" * 64 + '"')
    calls = []
    transport = SimpleNamespace(post=lambda *args, **kwargs: (calls.append((args, kwargs)), Response())[1])
    assert agent_tunnels(path, transport) == [tunnel()]
    args, options = calls[0]
    assert args == (API,)
    assert options["allow_redirects"] is False
    assert options["timeout"] == (5, 10)
    assert options["headers"] == {"Authorization": "Agent-Key " + "a" * 64}
    assert options["json"] == {}


def test_redirect_is_rejected_without_returning_headers_or_secret(tmp_path):
    path = tmp_path / "playit.toml"
    secret = "b" * 64
    path.write_text(f'secret_key = "{secret}"')
    response = Response()
    response.status_code = 302
    with pytest.raises(RuntimeError) as error:
        agent_tunnels(path, SimpleNamespace(post=lambda *args, **kwargs: response))
    assert secret not in str(error.value)


def test_late_lookup_cannot_republish_address_after_stop(tmp_path, monkeypatch):
    from src.hexlauncher.core import server_manager
    manager = MinecraftServerManager(tmp_path)
    messages = []
    manager._on_status = lambda *args: messages.append(args)
    generation = manager._generation

    def finish_after_stop(*args):
        manager.stop_server()
        return [tunnel()]

    monkeypatch.setattr(server_manager, "agent_tunnels", finish_after_stop)
    manager._refresh_playit_address(generation)
    assert not any(kind == "address" for kind, value in messages)


def test_lookup_reports_disabled_tunnel_and_throttles_repeated_logs(tmp_path, monkeypatch):
    from src.hexlauncher.core import server_manager
    manager = MinecraftServerManager(tmp_path)
    messages, calls = [], []
    manager._on_status = lambda *args: messages.append(args)
    monkeypatch.setattr(server_manager, "agent_tunnels", lambda *args: (
        calls.append(True), [tunnel(disabled_reason="disabled by user")]
    )[1])
    manager._refresh_playit_address(manager._generation)
    manager._refresh_playit_address(manager._generation)
    assert len(calls) == 1
    assert len(messages) == 1 and messages[0][0] == "status"
    assert "desactivado" in messages[0][1]
