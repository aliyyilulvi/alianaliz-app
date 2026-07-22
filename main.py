# -*- coding: utf-8 -*-
"""
main.py
-------
AliAnaliz uygulamasının Kivy giriş noktası.
"""

import threading
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.graphics import Color, RoundedRectangle
from kivy.properties import StringProperty, BooleanProperty
from kivy.clock import mainthread
from kivy.metrics import dp
from datetime import datetime, timedelta, date

import data_fetcher
from analyzer import analyze_fixture, evaluate_actual_result
from market_labels import market_label

KV_FILE = "alianaliz.kv"

_TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
              "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
_TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def _format_date_tr(d: date) -> str:
    return f"{d.day} {_TR_MONTHS[d.month - 1]} {d.year}  ({_TR_DAYS[d.weekday()]})"


class MatchRow(BoxLayout):
    home_team = StringProperty("")
    away_team = StringProperty("")
    league = StringProperty("")
    kickoff = StringProperty("")
    raw_fixture = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(78)
        self.padding = dp(10)
        self.spacing = dp(8)

        with self.canvas.before:
            Color(0.216, 0.086, 0.325, 1)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[10])
        self.bind(pos=self._update_bg, size=self._update_bg)

        text_box = BoxLayout(orientation="vertical")

        self._title_label = Label(
            text=self.home_team + " vs " + self.away_team,
            color=(0.969, 0.949, 0.980, 1), bold=True,
            halign="left", valign="middle",
            shorten=True, shorten_from="right", max_lines=2,
            font_size="15sp",
        )
        self._title_label.bind(size=self._sync_title_text_size)
        text_box.add_widget(self._title_label)

        self._sub_label = Label(
            text=self.league + "  |  " + self.kickoff,
            color=(0.949, 0.600, 0.290, 0.9), font_size="11sp",
            halign="left", valign="middle",
            shorten=True, shorten_from="right",
        )
        self._sub_label.bind(size=self._sync_sub_text_size)
        text_box.add_widget(self._sub_label)

        self.add_widget(text_box)

        self.select_btn = Button(
            text="Analiz Et", size_hint_x=None, width=dp(100),
            background_normal="", background_color=(0.949, 0.600, 0.290, 1),
            color=(0.141, 0.098, 0.204, 1), bold=True, font_size="12sp",
        )
        self.add_widget(self.select_btn)

        self.bind(
            home_team=self._refresh_title, away_team=self._refresh_title,
            league=self._refresh_sub, kickoff=self._refresh_sub,
        )

    def _update_bg(self, *args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _sync_title_text_size(self, instance, value):
        instance.text_size = (value[0], None)

    def _sync_sub_text_size(self, instance, value):
        instance.text_size = (value[0], None)

    def _refresh_title(self, *args):
        self._title_label.text = self.home_team + " vs " + self.away_team

    def _refresh_sub(self, *args):
        self._sub_label.text = self.league + "  |  " + self.kickoff


class BultenScreen(Screen):
    loading = BooleanProperty(False)
    status_text = StringProperty("Bülten yüklemek için 'Yenile' butonuna basın.")
    date_display = StringProperty("")

    def on_kv_post(self, base_widget):
        self.selected_date = datetime.utcnow().date()
        self.date_display = _format_date_tr(self.selected_date)
        self._all_fixtures = []

    def shift_date(self, delta_days: int):
        self.selected_date += timedelta(days=delta_days)
        self.date_display = _format_date_tr(self.selected_date)
        self.refresh_fixtures()

    def refresh_fixtures(self):
        self.loading = True
        self.status_text = "Bülten yükleniyor..."
        self.ids.match_list.clear_widgets()
        date_str = self.selected_date.isoformat()
        threading.Thread(
            target=self._fetch_worker,
            args=(date_str, date_str),
            daemon=True,
        ).start()

    def _fetch_worker(self, date_from, date_to):
        try:
            fixtures = data_fetcher.fetch_upcoming_fixtures(
                "", limit=80, date_from=date_from, date_to=date_to
            )
            self._on_fixtures_loaded(fixtures)
        except Exception as e:
            import traceback
            from kivy.logger import Logger
            Logger.error("ALIANALIZ: TAM HATA:\n" + traceback.format_exc())
            self._on_error(str(e))

    @mainthread
    def _on_fixtures_loaded(self, fixtures):
        self.loading = False
        self._all_fixtures = fixtures
        if not fixtures:
            self.status_text = f"{self.date_display} tarihinde maç bulunamadı."
        else:
            self.status_text = f"{len(fixtures)} maç bulundu ({self.date_display})."
        self._render_fixtures(fixtures)

    def _render_fixtures(self, fixtures):
        self.ids.match_list.clear_widgets()
        for fx in fixtures:
            is_finished = fx.get("status") == "FINISHED"
            if is_finished and fx.get("home_goals") is not None:
                second_line = f"{fx.get('league','')}  |  Sonuc: {fx['home_goals']}-{fx['away_goals']} (Bitti)"
            else:
                second_line = f"{fx.get('league','')}  |  {fx.get('utc_date','')[:16].replace('T',' ')}"

            row = MatchRow(
                home_team=fx["home"], away_team=fx["away"],
                league=second_line, kickoff=""
            )
            row.raw_fixture = fx
            row.select_btn.text = "Sonucu Gor" if is_finished else "Analiz Et"
            row.select_btn.bind(on_release=lambda inst, f=fx: self.go_to_analysis(f))
            self.ids.match_list.add_widget(row)

    @mainthread
    def _on_error(self, message: str):
        self.loading = False
        self.status_text = f"Hata: {message}"

    def go_to_analysis(self, raw_fixture: dict):
        app = App.get_running_app()
        app.root.get_screen("analiz").load_fixture(raw_fixture)
        app.root.current = "analiz"


class AnalizScreen(Screen):
    loading = BooleanProperty(False)
    status_text = StringProperty("")
    home_team = StringProperty("")
    away_team = StringProperty("")

    def load_fixture(self, raw_fixture: dict):
        self.home_team = raw_fixture["home"]
        self.away_team = raw_fixture["away"]
        self.loading = True
        self.status_text = "Takım formu ve hava durumu verileri toplanıyor..."
        self.ids.results_box.clear_widgets()
        threading.Thread(target=self._analyze_worker, args=(raw_fixture,), daemon=True).start()

    def _analyze_worker(self, raw_fixture: dict):
        try:
            fixture = data_fetcher.build_fixture(raw_fixture)
            result = analyze_fixture(fixture)
            self._on_analysis_done(result, raw_fixture)
        except Exception as e:
            import traceback
            from kivy.logger import Logger
            Logger.error("ALIANALIZ: TAM HATA:\n" + traceback.format_exc())
            self._on_error(str(e))

    @mainthread
    def _on_analysis_done(self, result, raw_fixture):
        self.loading = False
        self.status_text = ""
        box = self.ids.results_box

        is_finished = raw_fixture.get("status") == "FINISHED" and raw_fixture.get("home_goals") is not None
        hit_markets = set()
        if is_finished:
            hit_markets = evaluate_actual_result(
                raw_fixture["home_goals"], raw_fixture["away_goals"],
                raw_fixture.get("ht_home_goals"), raw_fixture.get("ht_away_goals"),
            )
            score_lbl = Label(
                text=f"GERCEKLESEN SONUC: {self.home_team} {raw_fixture['home_goals']} - {raw_fixture['away_goals']} {self.away_team}",
                bold=True, size_hint_y=None, height=dp(40),
                color=(0.20, 0.85, 0.45, 1), halign="center", valign="middle"
            )
            score_lbl.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
            box.add_widget(score_lbl)
            hint_lbl = Label(
                text="Yesil + isaretli satirlar gercekte TUTAN tahminlerdir.",
                size_hint_y=None, height=dp(24), font_size="11sp",
                color=(0.949, 0.600, 0.290, 0.8), halign="center", valign="middle"
            )
            hint_lbl.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
            box.add_widget(hint_lbl)

        eg = result.expected_goals
        box.add_widget(self._section_title(
            f"Beklenen Gol (xG benzeri): {self.home_team} {eg['home']}  -  {eg['away']} {self.away_team}"
        ))

        box.add_widget(self._section_title("İSTATİSTİKSEL OLARAK ÖNE ÇIKAN SEÇİMLER"))
        for pick in result.top_picks:
            box.add_widget(self._pick_row(pick["market"], pick["probability"], pick["market"] in hit_markets))

        box.add_widget(self._section_title("DÜŞÜK OLASILIKLI SÜRPRİZ SENARYOLAR"))
        if result.surprise_picks:
            for pick in result.surprise_picks:
                box.add_widget(self._pick_row(pick["market"], pick["probability"], pick["market"] in hit_markets))
        else:
            lbl = Label(text="Bu maç için belirgin bir sürpriz senaryo bulunamadı.",
                        size_hint_y=None, height=dp(30), halign="center")
            lbl.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
            box.add_widget(lbl)

        box.add_widget(self._section_title("TÜM PAZARLAR (Detaylı Olasılık Tablosu)"))
        for market, prob in sorted(result.probabilities.items()):
            box.add_widget(self._pick_row(market, prob, market in hit_markets, small=True))

        note_label = Label(
            text=result.confidence_note,
            size_hint_y=None, height=dp(60), color=(0.949, 0.600, 0.290, 1),
            italic=True, halign="center", valign="middle"
        )
        note_label.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
        box.add_widget(note_label)

    @mainthread
    def _on_error(self, message: str):
        self.loading = False
        self.status_text = f"Hata: {message}"

    def _section_title(self, text):
        lbl = Label(text=text, bold=True, size_hint_y=None, height=dp(44),
                     color=(0.949, 0.600, 0.290, 1), halign="center", valign="middle")
        lbl.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
        return lbl

    def _pick_row(self, market_code, prob, hit=False, small=False):
        row = BoxLayout(size_hint_y=None, height=dp(30 if small else 40),
                         padding=[dp(4), 0])
        label_text = market_label(market_code)
        if hit:
            label_text = "✓ " + label_text
        market_color = (0.20, 0.85, 0.45, 1) if hit else (0.9, 0.88, 0.92, 1)
        market_lbl = Label(text=label_text, halign="left", valign="middle",
                            color=market_color, bold=hit,
                            font_size="11sp" if small else "13sp",
                            size_hint_x=0.68)
        market_lbl.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
        row.add_widget(market_lbl)

        prob_color = (0.20, 0.85, 0.45, 1) if hit else (0.949, 0.600, 0.290, 1)
        row.add_widget(Label(text=f"%{prob}", halign="right", bold=(not small) or hit,
                              color=prob_color, size_hint_x=0.32))
        return row


class AliAnalizScreenManager(ScreenManager):
    pass


class AliAnalizApp(App):
    title = "AliAnaliz"

    def build(self):
        Builder.load_file(KV_FILE)
        sm = AliAnalizScreenManager()
        sm.add_widget(BultenScreen(name="bulten"))
        sm.add_widget(AnalizScreen(name="analiz"))
        return sm


if __name__ == "__main__":
    AliAnalizApp().run()
