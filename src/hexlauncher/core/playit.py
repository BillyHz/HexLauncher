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


def resolve_minecraft_srv_port(domain: str) -> int | None:
    """Resolve SRV port for _minecraft._tcp.<domain> on Windows or via nslookup."""
    if not domain or not isinstance(domain, str) or ":" in domain:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DNS_SRV_DATA(ctypes.Structure):
            _fields_ = [
                ("pNameTarget", wintypes.LPWSTR),
                ("wPriority", wintypes.WORD),
                ("wWeight", wintypes.WORD),
                ("wPort", wintypes.WORD),
                ("Pad", wintypes.WORD),
            ]

        class DNS_RECORD(ctypes.Structure):
            pass

        DNS_RECORD._fields_ = [
            ("pNext", ctypes.POINTER(DNS_RECORD)),
            ("pName", wintypes.LPWSTR),
            ("wType", wintypes.WORD),
            ("wDataLength", wintypes.WORD),
            ("Flags", wintypes.DWORD),
            ("dwTtl", wintypes.DWORD),
            ("dwReserved", wintypes.DWORD),
            ("Data", DNS_SRV_DATA),
        ]

        dnsapi = ctypes.WinDLL("dnsapi.dll")
        record = ctypes.POINTER(DNS_RECORD)()
        query = f"_minecraft._tcp.{domain}"
        status = dnsapi.DnsQuery_W(query, 0x0021, 0, None, ctypes.byref(record), None)
        if status == 0 and record:
            try:
                curr = record.contents
                while curr:
                    if curr.wType == 0x0021:
                        port = int(curr.Data.wPort)
                        if 0 < port <= 65535:
                            return port
                    if not curr.pNext:
                        break
                    curr = curr.pNext.contents
            finally:
                dnsapi.DnsRecordListFree(record, 1)
    except Exception:
        pass

    try:
        import subprocess
        proc = subprocess.run(
            ["nslookup", "-type=SRV", f"_minecraft._tcp.{domain}"],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        match = re.search(r"port\s*=\s*(\d{1,5})", proc.stdout, re.IGNORECASE)
        if match:
            port = int(match.group(1))
            if 0 < port <= 65535:
                return port
    except Exception:
        pass

    return None
