# -*- coding: utf-8 -*-
"""
data_fetcher.py
----------------
AliAnaliz uygulamasının veri toplama katmanı.
Veri kaynağı: API-Football (api-football.com) - ücretsiz plan.

v2.0 - MİMARİ DEĞİŞİKLİĞİ:
Artık kendi Poisson modelimizi BESLEMEK için ham istatistik toplamıyoruz.
API-Football'ın KENDİ hazır "/predictions" motoru kullanılıyor - bu,
6 farklı algoritma ile hesaplanmış kazanan/beraberlik/deplasman yüzdeleri,
alt/üst tahmini, hücum/savunma gücü karşılaştırması ve H2H veriyor.
1200+ lig kapsıyor (MLS dahil).

ÖNEMLİ: Ücretsiz planda GÜNDE SADECE 100 İSTEK var (dakika değil, gün).
Bu yüzden:
  - Bülten yüklerken TEK bir istek atılır (/fixtures?date=X, tüm ligler).
  - Analiz sadece kullanıcı "Analiz Et"e bastığında (1 istek) yapılır.
"""

import os
import socket
import struct
import random
import time
from datetime import datetime
from typing import List, Optional

import requests
import urllib3.util.connection as _urllib3_cn

_original_getaddrinfo = socket.getaddrinfo


def _allowed_gai_family():
    return socket.AF_INET


_urllib3_cn.allowed_gai_family = _allowed_gai_family

_last_dns_debug = []


def _resolve_via_android(hostname: str) -> list:
    try:
        from jnius import autoclass
        InetAddress = autoclass("java.net.InetAddress")
        addresses = InetAddress.getAllByName(hostname)
        return [a.getHostAddress() for a in addresses]
    except Exception as e:
        _last_dns_debug.append(f"android: {type(e).__name__}: {e}")
        return []


def _build_dns_query(hostname: str) -> bytes:
    transaction_id = random.randint(0, 65535)
    header = struct.pack(">HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
    parts = hostname.split(".")
    question = b"".join(struct.pack("B", len(p)) + p.encode() for p in parts) + b"\x00"
    question += struct.pack(">HH", 1, 1)
    return header + question


def _parse_dns_response(data: bytes) -> list:
    ancount = struct.unpack(">H", data[6:8])[0]
    idx = 12
    while data[idx] != 0:
        idx += data[idx] + 1
    idx += 5
    ips = []
    for _ in range(ancount):
        if data[idx] & 0xC0 == 0xC0:
            idx += 2
        else:
            while data[idx] != 0:
                idx += data[idx] + 1
            idx += 1
        rtype, rclass, ttl, rdlength = struct.unpack(">HHIH", data[idx:idx + 10])
        idx += 10
        if rtype == 1 and rdlength == 4:
            ip = ".".join(str(b) for b in data[idx:idx + 4])
            ips.append(ip)
        idx += rdlength
    return ips


def _resolve_via_dns_tcp(hostname: str, dns_server: str = "8.8.8.8", port: int = 53, timeout: float = 6.0) -> list:
    try:
        query = _build_dns_query(hostname)
        tcp_query = struct.pack(">H", len(query)) + query
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((dns_server, port))
            sock.sendall(tcp_query)
            length_bytes = sock.recv(2)
            if len(length_bytes) < 2:
                return []
            resp_length = struct.unpack(">H", length_bytes)[0]
            resp_data = b""
            while len(resp_data) < resp_length:
                chunk = sock.recv(resp_length - len(resp_data))
                if not chunk:
                    break
                resp_data += chunk
        finally:
            sock.close()
        return _parse_dns_response(resp_data)
    except Exception as e:
        _last_dns_debug.append(f"dns_tcp: {type(e).__name__}: {e}")
        return []


def _resolve_via_doh(hostname: str, timeout: float = 6.0) -> list:
    try:
        resp = requests.get(
            "https://1.1.1.1/dns-query",
            params={"name": hostname, "type": "A"},
            headers={"accept": "application/dns-json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        answers = data.get("Answer", [])
        return [a["data"] for a in answers if a.get("type") == 1]
    except Exception as e:
        _last_dns_debug.append(f"doh: {type(e).__name__}: {e}")
        return []


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _original_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror as e:
        _last_dns_debug.append(f"original: {e}")

    ips = _resolve_via_android(host)
    if not ips:
        ips = _resolve_via_dns_tcp(host)
    if not ips:
        ips = _resolve_via_doh(host)

    if not ips:
        debug_info = " | ".join(_last_dns_debug[-4:])
        raise socket.gaierror(f"'{host}' çözümlenemedi -> [{debug_info}]")

    return [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))
        for ip in ips
    ]


socket.getaddrinfo = _patched_getaddrinfo

API_BASE = "https://v3.football.api-sports.io"
_HARDCODED_API_KEY = "b7e3704ff369331fc8d57a5d6036a067"


def _headers() -> dict:
    return {"x-apisports-key": _HARDCODED_API_KEY}


def _get(url: str, params: dict = None, timeout: float = 15):
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=timeout)
        return resp
    except Exception as e:
        raise RuntimeError(f"Baglanti hatasi: {type(e).__name__}: {e}")


# ----------------------------------------------------------------------
# 1) FİKSTÜR (Bülten) ÇEKME - TEK İSTEKLE TÜM LİGLER
# ----------------------------------------------------------------------
def fetch_upcoming_fixtures(competition_code: str = "", limit: int = 100,
                             date_from: Optional[str] = None, date_to: Optional[str] = None) -> List[dict]:
    """
    Belirtilen tarihteki maçları TÜM liglerden TEK istekle çeker
    (API-Football'ın /fixtures?date=X uç noktası zaten global taramadır).
    """
    date_str = date_from or date_to or datetime.utcnow().strftime("%Y-%m-%d")

    resp = _get(f"{API_BASE}/fixtures", params={"date": date_str})
    if resp.status_code != 200:
        raise RuntimeError(f"Fikstur alinamadi: HTTP {resp.status_code} - {resp.text[:200]}")

    payload = resp.json()
    matches = payload.get("response", [])

    fixtures = []
    for m in matches:
        fixture_info = m.get("fixture", {})
        league_info = m.get("league", {})
        teams = m.get("teams", {})
        goals = m.get("goals", {})

        status_short = (fixture_info.get("status") or {}).get("short", "NS")
        is_finished = status_short in ("FT", "AET", "PEN")
        status = "FINISHED" if is_finished else "SCHEDULED"

        fixtures.append({
            "fixture_id": fixture_info.get("id"),
            "home": (teams.get("home") or {}).get("name", "?"),
            "away": (teams.get("away") or {}).get("name", "?"),
            "home_id": (teams.get("home") or {}).get("id"),
            "away_id": (teams.get("away") or {}).get("id"),
            "utc_date": fixture_info.get("date", ""),
            "league": league_info.get("name", ""),
            "status": status,
            "home_goals": goals.get("home"),
            "away_goals": goals.get("away"),
            "ht_home_goals": None,
            "ht_away_goals": None,
        })

    fixtures.sort(key=lambda fx: fx.get("utc_date", ""))
    return fixtures[:limit]


# ----------------------------------------------------------------------
# 2) TAHMİN - API-Football'un kendi hazır motoru
# ----------------------------------------------------------------------
def fetch_prediction(fixture_id: int) -> dict:
    """
    Belirli bir maç için API-Football'un hazır tahminini döner.
    Dönüş: {
        "home_pct": float, "draw_pct": float, "away_pct": float,
        "winner_name": str veya None, "advice": str,
        "under_over": str veya None,
        "goals_home": str, "goals_away": str,
        "form_home": str, "form_away": str,
        "att_home": str, "att_away": str,
        "def_home": str, "def_away": str,
    }
    """
    resp = _get(f"{API_BASE}/predictions", params={"fixture": fixture_id})
    if resp.status_code != 200:
        raise RuntimeError(f"Tahmin alinamadi: HTTP {resp.status_code} - {resp.text[:200]}")

    payload = resp.json()
    response_list = payload.get("response", [])
    if not response_list:
        raise RuntimeError("Bu mac icin tahmin verisi bulunamadi (yeterli gecmis veri olmayabilir).")

    item = response_list[0]
    pred = item.get("predictions", {})
    comparison = item.get("comparison", {})
    teams = item.get("teams", {})

    percent = pred.get("percent", {}) or {}

    def _pct(val):
        try:
            return float(str(val).replace("%", ""))
        except (TypeError, ValueError):
            return 0.0

    winner = pred.get("winner") or {}
    goals = pred.get("goals", {}) or {}

    return {
        "home_pct": _pct(percent.get("home", "0")),
        "draw_pct": _pct(percent.get("draw", "0")),
        "away_pct": _pct(percent.get("away", "0")),
        "winner_name": winner.get("name"),
        "winner_comment": winner.get("comment", ""),
        "advice": pred.get("advice", ""),
        "under_over": pred.get("under_over"),
        "goals_home": goals.get("home", "?"),
        "goals_away": goals.get("away", "?"),
        "form_home": (comparison.get("form", {}) or {}).get("home", "?"),
        "form_away": (comparison.get("form", {}) or {}).get("away", "?"),
        "att_home": (comparison.get("att", {}) or {}).get("home", "?"),
        "att_away": (comparison.get("att", {}) or {}).get("away", "?"),
        "def_home": (comparison.get("def", {}) or {}).get("home", "?"),
        "def_away": (comparison.get("def", {}) or {}).get("away", "?"),
    }
