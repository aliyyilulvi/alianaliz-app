# -*- coding: utf-8 -*-
"""
market_labels.py
-----------------
analyzer.py'nin ürettiği kısaltılmış pazar kodlarını Türkçe açıklamalara çevirir.
"""

import re

_FIXED_LABELS = {
    "MS1": "Maç Sonucu: Ev Sahibi Kazanır",
    "MSX": "Maç Sonucu: Beraberlik",
    "MS2": "Maç Sonucu: Deplasman Kazanır",
    "KG_VAR": "Karşılıklı Gol: Var",
    "KG_YOK": "Karşılıklı Gol: Yok",
    "1_YARI_COK_GOLLU": "Daha Çok Gol İlk Yarıda Olur",
    "2_YARI_COK_GOLLU": "Daha Çok Gol İkinci Yarıda Olur",
    "IY_SADECE_1": "İlk Yarı Sonucu: Ev Sahibi Önde",
    "IY_SADECE_X": "İlk Yarı Sonucu: Berabere",
    "IY_SADECE_2": "İlk Yarı Sonucu: Deplasman Önde",
    "2Y_SADECE_1": "İkinci Yarı Sonucu: Ev Sahibi Önde",
    "2Y_SADECE_X": "İkinci Yarı Sonucu: Berabere",
    "2Y_SADECE_2": "İkinci Yarı Sonucu: Deplasman Önde",
    "EV_GALIBIYET_KG_VAR": "Ev Sahibi Kazanır + Karşılıklı Gol Var",
    "EV_GALIBIYET_KG_YOK": "Ev Sahibi Kazanır + Karşılıklı Gol Yok",
    "DEP_GALIBIYET_KG_VAR": "Deplasman Kazanır + Karşılıklı Gol Var",
    "DEP_GALIBIYET_KG_YOK": "Deplasman Kazanır + Karşılıklı Gol Yok",
}

_HALF_RESULT_TR = {"1": "Ev Sahibi", "X": "Beraberlik", "2": "Deplasman"}

_OU_PREFIX_TR = {
    "": "Toplam Gol",
    "EV_GOL_": "Ev Sahibi Gol",
    "DEP_GOL_": "Deplasman Gol",
}


def market_label(code: str) -> str:
    if code in _FIXED_LABELS:
        return _FIXED_LABELS[code]

    m = re.match(r"^IY([12X])/MS([12X])$", code)
    if m:
        iy, ms = m.group(1), m.group(2)
        return f"İY: {_HALF_RESULT_TR[iy]} / MS: {_HALF_RESULT_TR[ms]}"

    m = re.match(r"^(EV_GOL_|DEP_GOL_)?(ALT|UST)_(\d+(?:\.\d+)?)$", code)
    if m:
        prefix, direction, line = m.group(1) or "", m.group(2), m.group(3)
        subject = _OU_PREFIX_TR.get(prefix, "Gol")
        yon = "Altı" if direction == "ALT" else "Üstü"
        return f"{subject} {line} {yon}"

    return code.replace("_", " ").title()
