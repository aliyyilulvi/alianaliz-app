# -*- coding: utf-8 -*-
"""
analyzer.py
-----------
AliAnaliz'in istatistiksel analiz motoru. YÖNTEM: Poisson gol dağılımı modeli.

ÖNEMLİ ETİK/METODOLOJİK NOT:
Bu motor "kesin sonuç" ya da "garanti" üretmez. Ürettiği tüm yüzdeler,
geçmiş verilere dayalı İSTATİSTİKSEL OLASILIKLARDIR.
"""

import math
from typing import Dict, List, Tuple, Optional, Set

from models import Fixture, AnalysisResult

MAX_GOALS = 6
LEAGUE_AVG_GOALS = 1.35
FIRST_HALF_GOAL_RATIO = 0.45

Matrix = List[List[float]]


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        lam = 0.01
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def _market_value_factor(home_value: float, away_value: float) -> Tuple[float, float]:
    if home_value <= 0 or away_value <= 0:
        return 1.0, 1.0
    ratio = math.log((home_value + 1) / (away_value + 1))
    clipped = max(-1.0, min(1.0, ratio / 5))
    return 1.0 + clipped * 0.08, 1.0 - clipped * 0.08


def compute_expected_goals(fixture: Fixture) -> Tuple[float, float]:
    hs, aws = fixture.home_stats, fixture.away_stats

    home_attack = hs.avg_goals_for() / LEAGUE_AVG_GOALS
    home_defense = hs.avg_goals_against() / LEAGUE_AVG_GOALS
    away_attack = aws.avg_goals_for() / LEAGUE_AVG_GOALS
    away_defense = aws.avg_goals_against() / LEAGUE_AVG_GOALS

    if hs.last3_home_or_away:
        home_specific_attack = hs.avg_goals_for(hs.last3_home_or_away) / LEAGUE_AVG_GOALS
        home_attack = 0.6 * home_attack + 0.4 * home_specific_attack
    if aws.last3_home_or_away:
        away_specific_attack = aws.avg_goals_for(aws.last3_home_or_away) / LEAGUE_AVG_GOALS
        away_attack = 0.6 * away_attack + 0.4 * away_specific_attack

    home_form_mult = 0.9 + hs.form_score() * 0.2
    away_form_mult = 0.9 + aws.form_score() * 0.2

    hv_mult, av_mult = _market_value_factor(hs.squad_market_value_eur, aws.squad_market_value_eur)

    HOME_ADVANTAGE = 1.12

    lambda_home = LEAGUE_AVG_GOALS * home_attack * away_defense * home_form_mult * hv_mult * HOME_ADVANTAGE
    lambda_away = LEAGUE_AVG_GOALS * away_attack * home_defense * away_form_mult * av_mult

    if fixture.weather:
        rf = fixture.weather.rain_factor
        lambda_home *= rf
        lambda_away *= rf

    lambda_home = max(0.3, min(4.0, lambda_home))
    lambda_away = max(0.3, min(4.0, lambda_away))

    return lambda_home, lambda_away


def build_score_matrix(lambda_home: float, lambda_away: float) -> Matrix:
    home_probs = [_poisson_pmf(i, lambda_home) for i in range(MAX_GOALS + 1)]
    away_probs = [_poisson_pmf(j, lambda_away) for j in range(MAX_GOALS + 1)]

    matrix = [[hp * ap for ap in away_probs] for hp in home_probs]

    total = sum(sum(row) for row in matrix)
    if total > 0:
        matrix = [[cell / total for cell in row] for row in matrix]
    return matrix


def _match_result_probs(matrix: Matrix) -> Dict[str, float]:
    n = len(matrix)
    p_home = sum(matrix[i][j] for i in range(n) for j in range(n) if i > j)
    p_draw = sum(matrix[i][i] for i in range(n))
    p_away = sum(matrix[i][j] for i in range(n) for j in range(n) if j > i)
    return {"MS1": p_home, "MSX": p_draw, "MS2": p_away}


def _btts_probs(matrix: Matrix) -> Dict[str, float]:
    p_btts_yes = sum(matrix[i][j] for i in range(1, len(matrix)) for j in range(1, len(matrix[0])))
    return {"KG_VAR": p_btts_yes, "KG_YOK": 1 - p_btts_yes}


def _over_under_probs(matrix: Matrix, line: float) -> Dict[str, float]:
    n = len(matrix)
    over = sum(matrix[i][j] for i in range(n) for j in range(n) if (i + j) > line)
    under = 1 - over
    return {f"UST_{line}": over, f"ALT_{line}": under}


def _row_sums(matrix: Matrix) -> List[float]:
    return [sum(row) for row in matrix]


def _col_sums(matrix: Matrix) -> List[float]:
    n_cols = len(matrix[0]) if matrix else 0
    return [sum(row[j] for row in matrix) for j in range(n_cols)]


def _team_goals_over_under(probs_1d: List[float], line: float) -> Dict[str, float]:
    over = sum(p for k, p in enumerate(probs_1d) if k > line)
    return {"UST": over, "ALT": 1 - over}


def _half_matrices(lambda_home: float, lambda_away: float) -> Tuple[Matrix, Matrix]:
    lh1, la1 = lambda_home * FIRST_HALF_GOAL_RATIO, lambda_away * FIRST_HALF_GOAL_RATIO
    lh2, la2 = lambda_home * (1 - FIRST_HALF_GOAL_RATIO), lambda_away * (1 - FIRST_HALF_GOAL_RATIO)
    return build_score_matrix(lh1, la1), build_score_matrix(lh2, la2)


def _iy_ms_combinations(first_half_matrix: Matrix, full_match_matrix: Matrix) -> Dict[str, float]:
    iy = _match_result_probs(first_half_matrix)
    ms = _match_result_probs(full_match_matrix)
    combos = {}
    for iy_key, iy_label in [("MS1", "1"), ("MSX", "X"), ("MS2", "2")]:
        for ms_key, ms_label in [("MS1", "1"), ("MSX", "X"), ("MS2", "2")]:
            combos[f"IY{iy_label}/MS{ms_label}"] = iy[iy_key] * ms[ms_key]
    return combos


def analyze_fixture(fixture: Fixture) -> AnalysisResult:
    lambda_home, lambda_away = compute_expected_goals(fixture)
    matrix = build_score_matrix(lambda_home, lambda_away)
    fh_matrix, sh_matrix = _half_matrices(lambda_home, lambda_away)

    home_marginal = _row_sums(matrix)
    away_marginal = _col_sums(matrix)

    probabilities: Dict[str, float] = {}
    probabilities.update(_match_result_probs(matrix))
    probabilities.update(_btts_probs(matrix))
    for line in (1.5, 2.5, 3.5):
        probabilities.update(_over_under_probs(matrix, line))

    fh_expected = lambda_home * FIRST_HALF_GOAL_RATIO + lambda_away * FIRST_HALF_GOAL_RATIO
    sh_expected = (lambda_home + lambda_away) - fh_expected
    total_half = fh_expected + sh_expected
    probabilities["1_YARI_COK_GOLLU"] = fh_expected / total_half if total_half else 0.5
    probabilities["2_YARI_COK_GOLLU"] = sh_expected / total_half if total_half else 0.5

    probabilities.update(_iy_ms_combinations(fh_matrix, matrix))

    fh_result = _match_result_probs(fh_matrix)
    sh_result = _match_result_probs(sh_matrix)
    probabilities["IY_SADECE_1"] = fh_result["MS1"]
    probabilities["IY_SADECE_X"] = fh_result["MSX"]
    probabilities["IY_SADECE_2"] = fh_result["MS2"]
    probabilities["2Y_SADECE_1"] = sh_result["MS1"]
    probabilities["2Y_SADECE_X"] = sh_result["MSX"]
    probabilities["2Y_SADECE_2"] = sh_result["MS2"]

    home_ou = _team_goals_over_under(home_marginal, 1.5)
    away_ou = _team_goals_over_under(away_marginal, 1.5)
    probabilities["EV_GOL_UST_1.5"] = home_ou["UST"]
    probabilities["EV_GOL_ALT_1.5"] = home_ou["ALT"]
    probabilities["DEP_GOL_UST_1.5"] = away_ou["UST"]
    probabilities["DEP_GOL_ALT_1.5"] = away_ou["ALT"]

    n = len(matrix)
    p_home_win_btts_yes = sum(
        matrix[i][j] for i in range(1, n) for j in range(1, n) if i > j
    )
    p_away_win_btts_yes = sum(
        matrix[i][j] for i in range(1, n) for j in range(1, n) if j > i
    )
    probabilities["EV_GALIBIYET_KG_VAR"] = p_home_win_btts_yes
    probabilities["EV_GALIBIYET_KG_YOK"] = probabilities["MS1"] - p_home_win_btts_yes
    probabilities["DEP_GALIBIYET_KG_VAR"] = p_away_win_btts_yes
    probabilities["DEP_GALIBIYET_KG_YOK"] = probabilities["MS2"] - p_away_win_btts_yes

    sorted_probs = sorted(probabilities.items(), key=lambda x: x[1], reverse=True)

    top_picks = [
        {"market": k, "probability": round(float(v) * 100, 1)}
        for k, v in sorted_probs[:3]
    ]

    surprise_candidates = [
        (k, v) for k, v in sorted_probs if 0.10 <= v <= 0.30
    ]
    surprise_picks = [
        {"market": k, "probability": round(float(v) * 100, 1)}
        for k, v in surprise_candidates[:3]
    ]

    result = AnalysisResult(
        fixture=fixture,
        probabilities={k: round(float(v) * 100, 1) for k, v in probabilities.items()},
        top_picks=top_picks,
        surprise_picks=surprise_picks,
        expected_goals={"home": round(float(lambda_home), 2), "away": round(float(lambda_away), 2)},
    )
    return result


def evaluate_actual_result(home_goals: int, away_goals: int,
                            ht_home_goals: Optional[int] = None,
                            ht_away_goals: Optional[int] = None) -> Set[str]:
    hit: Set[str] = set()
    total = home_goals + away_goals

    if home_goals > away_goals:
        hit.add("MS1")
    elif home_goals == away_goals:
        hit.add("MSX")
    else:
        hit.add("MS2")

    if home_goals > 0 and away_goals > 0:
        hit.add("KG_VAR")
    else:
        hit.add("KG_YOK")

    for line in (1.5, 2.5, 3.5):
        if total > line:
            hit.add(f"UST_{line}")
        else:
            hit.add(f"ALT_{line}")

    if home_goals > 1.5:
        hit.add("EV_GOL_UST_1.5")
    else:
        hit.add("EV_GOL_ALT_1.5")
    if away_goals > 1.5:
        hit.add("DEP_GOL_UST_1.5")
    else:
        hit.add("DEP_GOL_ALT_1.5")

    if home_goals > away_goals:
        hit.add("EV_GALIBIYET_KG_VAR" if (home_goals > 0 and away_goals > 0) else "EV_GALIBIYET_KG_YOK")
    if away_goals > home_goals:
        hit.add("DEP_GALIBIYET_KG_VAR" if (home_goals > 0 and away_goals > 0) else "DEP_GALIBIYET_KG_YOK")

    if ht_home_goals is not None and ht_away_goals is not None:
        if ht_home_goals > ht_away_goals:
            iy = "1"
        elif ht_home_goals == ht_away_goals:
            iy = "X"
        else:
            iy = "2"

        if home_goals > away_goals:
            ms = "1"
        elif home_goals == away_goals:
            ms = "X"
        else:
            ms = "2"

        hit.add(f"IY{iy}/MS{ms}")

        if ht_home_goals > ht_away_goals:
            hit.add("IY_SADECE_1")
        elif ht_home_goals == ht_away_goals:
            hit.add("IY_SADECE_X")
        else:
            hit.add("IY_SADECE_2")

        sh_home = home_goals - ht_home_goals
        sh_away = away_goals - ht_away_goals
        if sh_home > sh_away:
            hit.add("2Y_SADECE_1")
        elif sh_home == sh_away:
            hit.add("2Y_SADECE_X")
        else:
            hit.add("2Y_SADECE_2")

        fh_total = ht_home_goals + ht_away_goals
        sh_total = sh_home + sh_away
        if fh_total > sh_total:
            hit.add("1_YARI_COK_GOLLU")
        elif sh_total > fh_total:
            hit.add("2_YARI_COK_GOLLU")

    return hit
