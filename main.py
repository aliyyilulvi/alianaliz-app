# -*- coding: utf-8 -*-
"""
main.py
-------
AliAnaliz uygulamasının Kivy giriş noktası.
Veri/analiz kaynağı: API-Football'ın hazır tahmin motoru.
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
            args=(date_str,),
            daemon=True,
        ).start()

    def _fetch_worker(self, date_str):
        try:
            fixtures = data_fetcher.fetch_upcoming_fixtures(
                "", limit=100, date_from=date_str, date_to=date_str
            )
            self._on_fixtures_loaded(fixtures)
        except Exception as e:
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
        self.status_text = "API-Football tahmin motoru sorgulanıyor..."
        self.ids.results_box.clear_widgets()
        self._raw_fixture = raw_fixture
        threading.Thread(target=self._analyze_worker, args=(raw_fixture,), daemon=True).start()

    def _analyze_worker(self, raw_fixture: dict):
        try:
            prediction = data_fetcher.fetch_prediction(raw_fixture["fixture_id"])
            self._on_analysis_done(prediction, raw_fixture)
        except Exception as e:
            self._on_error(str(e))

    @mainthread
    def _on_analysis_done(self, prediction, raw_fixture):
        self.loading = False
        self.status_text = ""
        box = self.ids.results_box

        is_finished = raw_fixture.get("status") == "FINISHED" and raw_fixture.get("home_goals") is not None

        if is_finished:
            hg, ag = raw_fixture["home_goals"], raw_fixture["away_goals"]
            actual_winner = self.home_team if hg > ag else (self.away_team if ag > hg else None)
            predicted_winner = prediction.get("winner_name")
            hit = (actual_winner == predicted_winner) or (actual_winner is None and predicted_winner is None)

            score_lbl = Label(
                text=f"GERCEKLESEN SONUC: {self.home_team} {hg} - {ag} {self.away_team}",
                bold=True, size_hint_y=None, height=dp(40),
                color=(0.20, 0.85, 0.45, 1), halign="center", valign="middle"
            )
            self._bind_ts(score_lbl, box)
            box.add_widget(score_lbl)

            hit_lbl = Label(
                text=("✓ Tahmin edilen kazanan DOGRU CIKTI!" if hit else "✗ Tahmin edilen kazanan tutmadi."),
                bold=True, size_hint_y=None, height=dp(30),
                color=(0.20, 0.85, 0.45, 1) if hit else (0.85, 0.35, 0.35, 1),
                halign="center", valign="middle"
            )
            self._bind_ts(hit_lbl, box)
            box.add_widget(hit_lbl)

        box.add_widget(self._section_title("API-FOOTBALL TAHMİNİ (6 algoritma ortalaması)"))

        pct_row = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(6))
        pct_row.add_widget(self._pct_box(f"{self.home_team}\n%{prediction['home_pct']:.0f}"))
        pct_row.add_widget(self._pct_box(f"Berabere\n%{prediction['draw_pct']:.0f}"))
        pct_row.add_widget(self._pct_box(f"{self.away_team}\n%{prediction['away_pct']:.0f}"))
        box.add_widget(pct_row)

        if prediction.get("winner_name"):
            box.add_widget(self._info_row("Tahmin Edilen Kazanan", prediction["winner_name"]))
        if prediction.get("under_over"):
            box.add_widget(self._info_row("Alt/Üst Tahmini", str(prediction["under_over"])))
        box.add_widget(self._info_row("Beklenen Gol Araligi (Ev)", str(prediction.get("goals_home", "?"))))
        box.add_widget(self._info_row("Beklenen Gol Araligi (Dep)", str(prediction.get("goals_away", "?"))))

        if prediction.get("advice"):
            advice_lbl = Label(
                text=f"Tavsiye: {prediction['advice']}",
                size_hint_y=None, height=dp(50), italic=True,
                color=(0.949, 0.600, 0.290, 1), halign="center", valign="middle"
            )
            self._bind_ts(advice_lbl, box)
            box.add_widget(advice_lbl)

        box.add_widget(self._section_title("TAKIM KARŞILAŞTIRMASI"))
        box.add_widget(self._compare_row("Form", prediction.get("form_home"), prediction.get("form_away")))
        box.add_widget(self._compare_row("Hücum Gücü", prediction.get("att_home"), prediction.get("att_away")))
        box.add_widget(self._compare_row("Savunma Gücü", prediction.get("def_home"), prediction.get("def_away")))

        note_label = Label(
            text="Bu tahmin API-Football'un istatistiksel modeline aittir; gelecekteki sonucun garantisi değildir.",
            size_hint_y=None, height=dp(60), color=(0.949, 0.600, 0.290, 0.8),
            italic=True, halign="center", valign="middle"
        )
        self._bind_ts(note_label, box)
        box.add_widget(note_label)

    def _bind_ts(self, label, box):
        label.text_size = (box.width, None)
        label.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))

    @mainthread
    def _on_error(self, message: str):
        self.loading = False
        self.status_text = f"Hata: {message}"

    def _section_title(self, text):
        lbl = Label(text=text, bold=True, size_hint_y=None, height=dp(44),
                     color=(0.949, 0.600, 0.290, 1), halign="center", valign="middle")
        lbl.text_size = (self.ids.results_box.width, None)
        lbl.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
        return lbl

    def _pct_box(self, text):
        lbl = Label(text=text, halign="center", valign="middle",
                     color=(0.969, 0.949, 0.980, 1), bold=True, font_size="13sp")
        lbl.bind(size=lambda i, v: setattr(i, "text_size", v))
        return lbl

    def _info_row(self, label_text, value_text):
        row = BoxLayout(size_hint_y=None, height=dp(32), padding=[dp(4), 0])
        lbl = Label(text=label_text, halign="left", valign="middle",
                     color=(0.9, 0.88, 0.92, 1), font_size="12sp", size_hint_x=0.6)
        lbl.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
        row.add_widget(lbl)
        val = Label(text=value_text, halign="right", valign="middle",
                     color=(0.949, 0.600, 0.290, 1), bold=True, font_size="12sp", size_hint_x=0.4)
        val.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
        row.add_widget(val)
        return row

    def _compare_row(self, label, home_val, away_val):
        row = BoxLayout(size_hint_y=None, height=dp(32), padding=[dp(4), 0])
        h = Label(text=str(home_val or "?"), halign="left", color=(0.9, 0.88, 0.92, 1), font_size="12sp")
        h.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
        row.add_widget(h)
        c = Label(text=label, halign="center", color=(0.949, 0.600, 0.290, 1), bold=True, font_size="11sp")
        c.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
        row.add_widget(c)
        a = Label(text=str(away_val or "?"), halign="right", color=(0.9, 0.88, 0.92, 1), font_size="12sp")
        a.bind(size=lambda i, v: setattr(i, "text_size", (v[0], None)))
        row.add_widget(a)
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
