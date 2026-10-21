"""Read this agent's tunnel metadata; never create or enable account tunnels."""

from pathlib import Path
import re
import tomllib

import requests

API = "https://api.playit.gg/v1/agents/rundata"


def agent_tunnels(secret_path, transport=requests):
    path = Path(secret_path)
    if not path.is_file():
        return []
    with path.open("rb") as source:
        raw = source.read(4097)
    if len(raw) > 4096:
        raise ValueError("Invalid Playit configuration")
    secret = tomllib.loads(raw.decode("utf-8-sig")).get("secret_key")
    if not isinstance(secret, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{16,256}", secret):
        raise ValueError("Invalid Playit configuration")
    with transport.post(
        API, json={}, headers={"Authorization": "Agent-Key " + secret},
        timeout=(5, 10), allow_redirects=False,
    ) as response:
        if response.status_code != 200:
            raise RuntimeError("Playit tunnel lookup failed")
        payload = response.json()
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise RuntimeError("Playit tunnel lookup failed")
    data = payload.get("data")
    tunnels = data.get("tunnels") if isinstance(data, dict) else None
    if not isinstance(tunnels, list):
        raise ValueError("Invalid Playit tunnel response")
    return tunnels


def minecraft_tunnel(tunnels):
    """Return (active address, disabled match); ignore other ports and services."""
    disabled = False
    for tunnel in tunnels:
        if not isinstance(tunnel, dict) or tunnel.get("port_type") not in ("tcp", "both"):
            continue
        config = tunnel.get("agent_config")
        if not isinstance(config, dict) or not isinstance(config.get("fields"), list):
            continue
        fields = {item["name"]: item.get("value") for item in config["fields"]
                  if isinstance(item, dict) and isinstance(item.get("name"), str)}
        if fields.get("local_ip") not in ("127.0.0.1", "localhost", "::1"):
            continue
        if str(fields.get("local_port")) != "25565":
            continue
        if tunnel.get("disabled_reason") is not None:
            disabled = True
            continue
        address = tunnel.get("display_address", "")
        if not isinstance(address, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}(?::[0-9]{1,5})?", address):
            continue
        if ":" in address and not 0 < int(address.rsplit(":", 1)[1]) <= 65535:
            continue
        return address, disabled
    return "", disabled
