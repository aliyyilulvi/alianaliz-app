# -*- coding: utf-8 -*-
"""
models.py
---------
AliAnaliz uygulamasında kullanılan veri yapılarını (data class) tanımlar.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MatchResult:
    opponent: str
    home: bool
    goals_for: int
    goals_against: int
    date: str = ""

    @property
    def points(self) -> int:
        if self.goals_for > self.goals_against:
            return 3
        if self.goals_for == self.goals_against:
            return 1
        return 0


@dataclass
class TeamStats:
    name: str
    last5_all: List[MatchResult] = field(default_factory=list)
    last3_home_or_away: List[MatchResult] = field(default_factory=list)
    squad_market_value_eur: float = 0.0

    attack_strength: float = 1.0
    defense_strength: float = 1.0

    # v1.1 EKLEME: standings tabanlı (sezon ortalaması) hazır değerler.
    # Doluysa avg_goals_for()/avg_goals_against() bunları döndürür,
    # boşsa (None) eski davranışa (last5_all'dan hesaplama) devam eder.
    season_avg_goals_for: Optional[float] = None
    season_avg_goals_against: Optional[float] = None
    season_form_score: Optional[float] = None

    def form_score(self, matches: Optional[List[MatchResult]] = None) -> float:
        if matches is None and self.season_form_score is not None:
            return self.season_form_score
        m = matches if matches is not None else self.last5_all
        if not m:
            return 0.5
        weights = [1.0, 0.85, 0.7, 0.55, 0.4][:len(m)]
        total_w = sum(weights)
        score = sum(mr.points * w for mr, w in zip(m, weights))
        max_score = 3 * total_w
        return score / max_score if max_score else 0.5

    def avg_goals_for(self, matches: Optional[List[MatchResult]] = None) -> float:
        if matches is None and self.season_avg_goals_for is not None:
            return self.season_avg_goals_for
        m = matches if matches is not None else self.last5_all
        if not m:
            return 1.2
        return sum(x.goals_for for x in m) / len(m)

    def avg_goals_against(self, matches: Optional[List[MatchResult]] = None) -> float:
        if matches is None and self.season_avg_goals_against is not None:
            return self.season_avg_goals_against
        m = matches if matches is not None else self.last5_all
        if not m:
            return 1.2
        return sum(x.goals_against for x in m) / len(m)


@dataclass
class HeadToHead:
    matches: List[dict] = field(default_factory=list)


@dataclass
class WeatherInfo:
    temperature_c: Optional[float] = None
    precipitation_mm: Optional[float] = None
    wind_kmh: Optional[float] = None
    condition: str = "bilinmiyor"

    @property
    def rain_factor(self) -> float:
        if self.precipitation_mm is None:
            return 1.0
        if self.precipitation_mm > 10:
            return 0.90
        if self.precipitation_mm > 2:
            return 0.96
        return 1.0


@dataclass
class Fixture:
    home_team: str
    away_team: str
    league: str = ""
    kickoff: str = ""
    home_stats: Optional[TeamStats] = None
    away_stats: Optional[TeamStats] = None
    h2h: Optional[HeadToHead] = None
    weather: Optional[WeatherInfo] = None


@dataclass
class AnalysisResult:
    fixture: Fixture
    probabilities: dict = field(default_factory=dict)
    top_picks: list = field(default_factory=list)
    surprise_picks: list = field(default_factory=list)
    expected_goals: dict = field(default_factory=dict)
    confidence_note: str = (
        "Bu oranlar geçmiş verilere dayalı istatistiksel bir modeldir; "
        "gelecekteki maç sonucunun garantisi değildir."
    )
