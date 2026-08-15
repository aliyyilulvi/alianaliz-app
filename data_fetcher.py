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

v2.1 - LİG FİLTRESİ:
Bülten artık SADECE majör ligler ve o ülkelerin 1./2. ligleri ile
sınırlı (ALLOWED_LEAGUE_IDS). Bilinmeyen/küçük/amatör ligler bültende
görünmez.
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
# 0) İZİN VERİLEN LİGLER - Majör ligler + o ülkelerin 1./2. ligleri
# ----------------------------------------------------------------------
# API-Football lig ID'leri. Bilinmeyen/küçük ligleri (3. lig, amatör,
# gençlik vb.) dışarıda bırakmak için bültende SADECE bu listedeki
# ligler gösterilir. Yeni bir lig eklemek/çıkarmak istersen bu
# sözlüğü düzenlemen yeterli (ID: "isim" şeklinde).
ALLOWED_LEAGUE_IDS = {
    # --- Türkiye ---
    203: "Süper Lig",
    204: "1. Lig",

    # --- İngiltere ---
    39: "Premier League",
    40: "Championship",

    # --- İspanya ---
    140: "La Liga",
    141: "La Liga 2 (Segunda División)",

    # --- İtalya ---
    135: "Serie A",
    136: "Serie B",

    # --- Almanya ---
    78: "Bundesliga",
    79: "2. Bundesliga",

    # --- Fransa ---
    61: "Ligue 1",
    62: "Ligue 2",

    # --- Portekiz / Hollanda / Belçika ---
    94: "Primeira Liga",
    88: "Eredivisie",
    144: "Jupiler Pro League",

    # --- Avrupa kupaları ---
    2: "UEFA Champions League",
    3: "UEFA Europa League",
    848: "UEFA Europa Conference League",

    # --- Milli takım turnuvaları ---
    1: "Dünya Kupası",
    4: "Avrupa Şampiyonası (Euro)",

    # --- Diğer büyük ligler ---
    253: "MLS (ABD)",
}


def _is_allowed_league(league_id: Optional[int]) -> bool:
    return league_id in ALLOWED_LEAGUE_IDS


# ----------------------------------------------------------------------
# 1) FİKSTÜR (Bülten) ÇEKME - TEK İSTEKLE TÜM LİGLER, SONRA FİLTRELEME
# ----------------------------------------------------------------------
def fetch_upcoming_fixtures(competition_code: str = "", limit: int = 100,
                             date_from: Optional[str] = None, date_to: Optional[str] = None) -> List[dict]:
    """
    Belirtilen tarihteki maçları TÜM liglerden TEK istekle çeker
    (API-Football'ın /fixtures?date=X uç noktası zaten global taramadır),
    sonra sadece ALLOWED_LEAGUE_IDS içindeki (majör + 1./2. lig) maçları
    döner. Bilinmeyen/küçük ligler bültende görünmez.
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

        league_id = league_info.get("id")
        if not _is_allowed_league(league_id):
            continue

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
            "league_id": league_id,
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
    v2.2: Sadece yüzdeler değil, sezon istatistikleri (galibiyet/beraberlik/
    maglubiyet, gol averaji), son 5 maç formu ve H2H (iki takımın önceki
    karşılaşmaları) da dahil edildi - ekran artık çok daha detaylı.

    Eksik/boş gelen alanlar None yerine "Veri yok" ile doldurulur.
    """
    resp = _get(f"{API_BASE}/predictions", params={"fixture": fixture_id})
    if resp.status_code != 200:
        raise RuntimeError(f"Tahmin alinamadi: HTTP {resp.status_code} - {resp.text[:200]}")

    payload = resp.json()
    response_list = payload.get("response", [])
    if not response_list:
        raise RuntimeError("Bu mac icin tahmin verisi bulunamadi (yeterli gecmis veri olmayabilir).")

    item = response_list[0]
    pred = item.get("predictions", {}) or {}
    comparison = item.get("comparison", {}) or {}
    teams = item.get("teams", {}) or {}
    h2h_raw = item.get("h2h", []) or []

    percent = pred.get("percent", {}) or {}

    def _pct(val):
        try:
            return float(str(val).replace("%", ""))
        except (TypeError, ValueError):
            return 0.0

    def _s(val, default="Veri yok"):
        """Bos/None degerleri temiz bir Turkce metinle degistirir."""
        if val is None or val == "" or val == "?":
            return default
        return str(val)

    winner = pred.get("winner") or {}
    goals = pred.get("goals", {}) or {}

    def _team_season_stats(team_key: str) -> dict:
        t = teams.get(team_key, {}) or {}
        league_info = t.get("league", {}) or {}
        fixtures_info = league_info.get("fixtures", {}) or {}
        goals_info = league_info.get("goals", {}) or {}

        played = (fixtures_info.get("played", {}) or {}).get("total")
        wins = (fixtures_info.get("wins", {}) or {}).get("total")
        draws = (fixtures_info.get("draws", {}) or {}).get("total")
        loses = (fixtures_info.get("loses", {}) or {}).get("total")
        goals_for = (goals_info.get("for", {}) or {}).get("total", {}).get("total") \
            if isinstance(goals_info.get("for", {}), dict) else None
        goals_against = (goals_info.get("against", {}) or {}).get("total", {}).get("total") \
            if isinstance(goals_info.get("against", {}), dict) else None

        return {
            "form": _s(league_info.get("form"), "?"),
            "played": played if played is not None else "?",
            "wins": wins if wins is not None else "?",
            "draws": draws if draws is not None else "?",
            "loses": loses if loses is not None else "?",
            "goals_for": goals_for if goals_for is not None else "?",
            "goals_against": goals_against if goals_against is not None else "?",
        }

    def _format_h2h(matches: list, home_name: str, away_name: str) -> list:
        """Son 5 h2h maci 'TakimA 2-1 TakimB' formatinda ozetler."""
        formatted = []
        # En yeniler ustte olacak sekilde ters cevir (API genelde eskiden yeniye verir)
        for m in list(reversed(matches))[:5]:
            fx = m.get("fixture", {}) or {}
            tm = m.get("teams", {}) or {}
            gl = m.get("goals", {}) or {}
            h_name = (tm.get("home") or {}).get("name", "?")
            a_name = (tm.get("away") or {}).get("name", "?")
            h_goals = gl.get("home")
            a_goals = gl.get("away")
            date_str = (fx.get("date") or "")[:10]
            if h_goals is None or a_goals is None:
                continue
            formatted.append(f"{h_name} {h_goals}-{a_goals} {a_name}  ({date_str})")
        return formatted

    home_name = (teams.get("home") or {}).get("name", "Ev Sahibi")
    away_name = (teams.get("away") or {}).get("name", "Deplasman")

    return {
        "home_pct": _pct(percent.get("home", "0")),
        "draw_pct": _pct(percent.get("draw", "0")),
        "away_pct": _pct(percent.get("away", "0")),
        "winner_name": winner.get("name"),
        "winner_comment": _s(winner.get("comment"), ""),
        "advice": _s(pred.get("advice"), "Yeterli veri yok"),
        "under_over": _s(pred.get("under_over"), "Belirtilmemis"),
        "goals_home": _s(goals.get("home")),
        "goals_away": _s(goals.get("away")),
        "form_home": _s((comparison.get("form", {}) or {}).get("home")),
        "form_away": _s((comparison.get("form", {}) or {}).get("away")),
        "att_home": _s((comparison.get("att", {}) or {}).get("home")),
        "att_away": _s((comparison.get("att", {}) or {}).get("away")),
        "def_home": _s((comparison.get("def", {}) or {}).get("home")),
        "def_away": _s((comparison.get("def", {}) or {}).get("away")),
        "poisson_home": _s((comparison.get("poisson_distribution", {}) or {}).get("home")),
        "poisson_away": _s((comparison.get("poisson_distribution", {}) or {}).get("away")),
        "h2h_pct": _s((comparison.get("h2h", {}) or {}).get("home")),
        "win_or_draw": pred.get("win_or_draw", False),
        "home_season": _team_season_stats("home"),
        "away_season": _team_season_stats("away"),
        "h2h_matches": _format_h2h(h2h_raw, home_name, away_name),
    }


# ----------------------------------------------------------------------
# 3) TOPLU ANALİZ - Tüm bültendeki maçları analiz edip yüzdeye göre sırala
# ----------------------------------------------------------------------
def fetch_all_predictions(fixtures: List[dict], max_requests: int = 90,
                           progress_callback=None) -> "tuple[List[dict], List[dict]]":
    """
    Verilen fikstür listesindeki HER maç için API-Football'un tahminini
    çeker ve en yüksek olasılıklı sonuca (ev/beraberlik/deplasman
    yüzdelerinin en büyüğü) göre BÜYÜKTEN KÜÇÜĞE sıralanmış halde döner.

    Dönüş: (analyzed, skipped)
      - analyzed: [{"fixture":..., "prediction":..., "best_pct":..., "best_side":...}, ...]
        best_side "home" / "draw" / "away" değerlerinden biridir.
        En yüksek olasılıklı maç listenin başındadır.
      - skipped: analiz edilemeyen (istek limiti dolduğu için atlanan ya da
        API hata verdiği için başarısız olan) fikstürlerin ham listesi.

    ÖNEMLİ: Ücretsiz API planında GÜNDE SADECE 100 istek var. Bülten
    çekmek zaten 1 istek harcadığı için, güvenlik payı bırakmak amacıyla
    varsayılan olarak en fazla max_requests (90) maç analiz edilir.
    Zaten bitmiş (FINISHED) maçlar analiz edilmez, otomatik atlanır.
    """
    analyzed: List[dict] = []
    skipped: List[dict] = []

    active_fixtures = [fx for fx in fixtures if fx.get("status") != "FINISHED"]

    for i, fx in enumerate(active_fixtures):
        if i >= max_requests:
            skipped.append(fx)
            continue

        if progress_callback:
            try:
                progress_callback(i + 1, min(len(active_fixtures), max_requests))
            except Exception:
                pass

        try:
            pred = fetch_prediction(fx["fixture_id"])
        except Exception:
            skipped.append(fx)
            continue

        best_pct = max(pred["home_pct"], pred["draw_pct"], pred["away_pct"])
        if best_pct == pred["home_pct"]:
            best_side = "home"
        elif best_pct == pred["away_pct"]:
            best_side = "away"
        else:
            best_side = "draw"

        analyzed.append({
            "fixture": fx,
            "prediction": pred,
            "best_pct": best_pct,
            "best_side": best_side,
        })

    analyzed.sort(key=lambda a: a["best_pct"], reverse=True)
    return analyzed, skipped
