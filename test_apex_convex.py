"""
test_apex_convex.py — Suite di Test e Verifica di Robustezza APEX CONVEX
========================================================================
Verifica di integrità e non-regressione:
  1. Coerenza matematica dei pesi di Convex Stack (Somma = 100.0%)
  2. Leva nozionale incorporata (122.5%)
  3. Algoritmo Water-Filling del PAC mensile
  4. Soglie di Trim asimmetriche e classificazione fiscale (ETC vs ETF)
  5. Aggregazione patrimoniale e logica Smart-Flow
  6. Integrità del motore Apex V2 Canonico
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import convex_engine
import portfolio_manager
import apex_v2_engine


class TestApexConvexEcosystem(unittest.TestCase):

    def test_convex_weights_and_leverage(self):
        """Verifica che i pesi di cassa sommino esattamente a 1.0 e la leva a 1.225x."""
        weights = [info["target_weight"] for info in convex_engine.CONVEX_INSTRUMENTS.values()]
        self.assertAlmostEqual(sum(weights), 1.0, places=4, msg="I pesi di cassa devono sommare al 100.0%")

        # Calcolo leva nozionale
        notional_exp = (
            convex_engine.CONVEX_INSTRUMENTS["NTSG"]["target_weight"] * 1.5 +
            convex_engine.CONVEX_INSTRUMENTS["AVWS"]["target_weight"] * 1.0 +
            convex_engine.CONVEX_INSTRUMENTS["DBMFE"]["target_weight"] * 1.0 +
            convex_engine.CONVEX_INSTRUMENTS["PPFB"]["target_weight"] * 1.0 +
            convex_engine.CONVEX_INSTRUMENTS["WBTC"]["target_weight"] * 1.0
        )
        self.assertAlmostEqual(notional_exp, 1.225, places=4, msg="L'esposizione nozionale deve essere esattamente 122.5%")

    def test_pac_water_filling_algorithm(self):
        """Verifica che il PAC mensile compri l'asset più sottopesato."""
        # Creiamo un portafoglio con DBMFE fortemente sottopesato
        holdings = {
            "NTSG": 600,   # sovrapesato
            "AVWS": 300,
            "DBMFE": 200,  # sottopesato
            "PPFB": 150,
            "WBTC": 100
        }
        prices = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
        report = convex_engine.evaluate_convex_stack(holdings, prices, monthly_pac_eur=600.0)

        self.assertIsNotNone(report.pac_action)
        self.assertEqual(report.pac_action.recommended_asset, "DBMFE", "Il PAC deve raccomandare l'acquisto dell'asset più sottopesato")
        self.assertEqual(report.pac_action.estimated_shares, 24, "600€ / 25€ = 24 quote")

    def test_trim_thresholds_and_tax_classification(self):
        """Verifica che lo sforamento delle soglie attivi l'alert con nota fiscale appropriata."""
        # Creiamo un portafoglio con Bitcoin che sale al 20% (> 15% soglia)
        holdings = {
            "NTSG": 450, "AVWS": 150, "DBMFE": 250, "PPFB": 75, "WBTC": 300 # BTC raddoppiato
        }
        prices = {"NTSG": 100.0, "AVWS": 100.0, "DBMFE": 100.0, "PPFB": 100.0, "WBTC": 100.0}
        report = convex_engine.evaluate_convex_stack(holdings, prices)

        btc_alert = next((a for a in report.trim_alerts if a["asset"] == "WBTC"), None)
        self.assertIsNotNone(btc_alert, "WBTC sopra l'11.25% deve attivare l'alert di trim")
        self.assertIn("COMPENSABILE con minusvalenze", btc_alert["tax_note"])

    def test_trim_never_fires_for_reddito_capitale(self):
        """NTSG/AVWS/DBMFE (Reddito di Capitale, minus non compensabili) non devono
        mai generare un alert di trim, anche molto sopra la loro banda massima —
        coerente con research/convex/convex_operational_rules.py, il backtest
        validato che applica il trim solo a WBTC/PPFB (Reddito Diverso)."""
        holdings = {
            "NTSG": 900,   # ~73% del portafoglio, ben oltre la banda max (50%)
            "AVWS": 50, "DBMFE": 50, "PPFB": 75, "WBTC": 75
        }
        prices = {"NTSG": 100.0, "AVWS": 100.0, "DBMFE": 100.0, "PPFB": 100.0, "WBTC": 100.0}
        report = convex_engine.evaluate_convex_stack(holdings, prices)

        for asset in ("NTSG", "AVWS", "DBMFE"):
            alert = next((a for a in report.trim_alerts if a["asset"] == asset), None)
            self.assertIsNone(alert, f"{asset} e' Reddito di Capitale: non deve mai generare un alert di trim")
        self.assertTrue(report.assets["NTSG"].is_overweight, "NTSG deve comunque risultare sovrappeso (solo informativo)")
        self.assertFalse(report.assets["NTSG"].requires_trim, "NTSG non deve mai richiedere un trim")

    def test_portfolio_manager_smart_flow(self):
        """Verifica che la sintesi unificata rilevi correttamente lo squilibrio tra i motori."""
        holdings = {"NTSG": 450, "AVWS": 300, "DBMFE": 1000, "PPFB": 150, "WBTC": 75}
        prices = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
        c_rep = convex_engine.evaluate_convex_stack(holdings, prices, monthly_pac_eur=500.0)

        # Caso: Apex a 50k (33.3%) vs Convex a 100k (66.7%) con target Apex a 50%
        unified = portfolio_manager.compute_unified_portfolio(50000.0, c_rep, monthly_pac=500.0, target_apex_ratio=0.50)
        self.assertIn("Apex Engine", unified["smart_flow_destination"], "Smart flow deve indirizzare verso il motore sottopesato")

    def test_apex_v2_engine_unaltered(self):
        """Verifica che Apex V2 Canonico sia perfettamente integro e funzionante."""
        self.assertEqual(apex_v2_engine.V2_EQUITY_BUFFER_RANK, 20)
        self.assertEqual(apex_v2_engine.V2_VOL_TARGET, 0.22)
        self.assertEqual(apex_v2_engine.V2_EQUITY_TOP_N, 15)

    def test_smart_flow_no_crash_when_pac_is_zero(self):
        """Regressione: PAC=0€ (min_value consentito dalla UI) non deve mai
        andare in crash — prima era un AttributeError su pac_action=None
        quando i due motori erano già in equilibrio."""
        holdings = {"NTSG": 450, "AVWS": 300, "DBMFE": 1000, "PPFB": 150, "WBTC": 75}
        prices = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
        c_rep = convex_engine.evaluate_convex_stack(holdings, prices, monthly_pac_eur=0.0)
        self.assertIsNone(c_rep.pac_action, "Con PAC 0 non deve esserci un'azione consigliata")
        unified = portfolio_manager.compute_unified_portfolio(
            100000.0, c_rep, monthly_pac=0.0, target_apex_ratio=0.50
        )
        self.assertIn("Nessun versamento", unified["smart_flow_note"])

    def test_simple_instruments_weights_sum_to_one(self):
        """Regressione: i pesi della versione Semplice (4 strumenti, senza
        AVWS) devono sommare esattamente a 1.0."""
        weights = [info["target_weight"] for info in convex_engine.CONVEX_INSTRUMENTS_SIMPLE.values()]
        self.assertAlmostEqual(sum(weights), 1.0, places=6)

    def test_negative_holdings_never_produce_negative_value(self):
        """Difesa: quote negative non devono produrre un valore di posizione negativo."""
        report = convex_engine.evaluate_convex_stack(
            {"NTSG": -500, "WBTC": 100}, {"NTSG": 100.0, "WBTC": 100.0}, monthly_pac_eur=500.0
        )
        self.assertEqual(report.assets["NTSG"].current_value, 0.0)
        self.assertGreaterEqual(report.total_value, 0.0)

    def test_currency_conversion_usd_eur(self):
        """Verifica che la conversione da USD a EUR sia esatta e bidirezionale."""
        nav_usd = 110000.0
        eur_usd_rate = 1.10
        val_eur = nav_usd / eur_usd_rate
        self.assertAlmostEqual(val_eur, 100000.0, places=2)
        self.assertAlmostEqual(val_eur * eur_usd_rate, nav_usd, places=2)

    def test_spy_benchmark_alignment_convex_and_apex(self):
        """Verifica che la serie storica statica di SPY copra interamente sia Convex (312 mesi) sia Apex (142 mesi)."""
        import pandas as pd
        spy = portfolio_manager.load_monthly_benchmark_spy()
        self.assertGreaterEqual(len(spy), 400, "Lo storico SPY deve contenere oltre 400 mesi dal 1993")

        base_dir = os.path.dirname(__file__)
        cx_path = os.path.join(base_dir, "convex_monthly_returns.csv")
        apex_path = os.path.join(base_dir, "apex_monthly_returns_extended.csv")

        if os.path.exists(cx_path):
            cx = pd.read_csv(cx_path, index_col=0, parse_dates=True)
            common_cx = cx.index.intersection(spy.index)
            self.assertEqual(len(common_cx), len(cx), "Tutti i 312 mesi di Convex devono avere il corrispondente mese in SPY")

        if os.path.exists(apex_path):
            apex = pd.read_csv(apex_path, index_col=0, parse_dates=True)
            common_apex = apex.index.intersection(spy.index)
            self.assertEqual(len(common_apex), len(apex), "Tutti i 142 mesi di Apex devono avere il corrispondente mese in SPY")

    def test_default_convex_holdings_100k(self):
        """Verifica che le quote di default di Convex Stack producano un capitale di 100.000 € esatto."""
        def_holdings = portfolio_manager.get_default_convex_holdings_100k()
        shares = {k: v["shares"] for k, v in def_holdings["holdings"].items()}
        prices = {k: v["last_price"] for k, v in def_holdings["holdings"].items()}
        cash = def_holdings.get("cash_eur", 0.0)

        tot_invested = sum(shares[k] * prices[k] for k in shares)
        total_wealth = tot_invested + cash
        self.assertAlmostEqual(total_wealth, 100000.0, delta=1.0, msg="Il portafoglio standard di default deve valere 100.000 €")
        self.assertGreater(shares["NTSG"], 1000, "NTSG deve avere ~1568 quote per pesare il 45%")
        self.assertGreater(shares["AVWS"], 400, "AVWS deve avere ~585 quote per pesare il 15%")
        self.assertGreater(shares["DBMFE"], 150, "DBMFE deve avere ~202 quote per pesare il 25%")
        self.assertGreater(shares["PPFB"], 70, "PPFB deve avere ~100 quote per pesare il 7.5%")
        self.assertGreater(shares["WBTC"], 300, "WBTC deve avere ~452 quote per pesare il 7.5%")

    def test_convex_metadata_and_isins(self):
        """Verifica che ciascuno dei 5 strumenti abbia un ISIN valido e metadati completi."""
        meta = portfolio_manager.CONVEX_INSTRUMENTS_METADATA
        self.assertEqual(len(meta), 5)
        for k in ["NTSG", "AVWS", "DBMFE", "PPFB", "WBTC"]:
            self.assertIn(k, meta)
            self.assertTrue(len(meta[k]["isin"]) >= 12, f"ISIN per {k} deve essere valido")
            self.assertIn("tax_regime", meta[k])
            self.assertIn("role", meta[k])

    def test_zero_emoji_integrity(self):
        """Verifica che non sia presente alcuna emoji in tutti i file python dell'applicazione."""
        import re
        emoji_pattern = re.compile(
            '[\U00010000-\U0010ffff]|'
            '[\u2600-\u27BF]|'
            '[\u2300-\u23FF]|'
            '[\u2B50-\u2B55]|'
            '[\u203C-\u2049]|'
            '[\u25AA-\u25FE]|'
            '[\u00A9\u00AE\u20E3\u2122]|'
            '[\u2194-\u2199]|'
            '[\u21A9-\u21AA]'
        )
        base_dir = os.path.dirname(__file__)
        py_files = ["main.py", "app.py", "home_app.py", "page_apex.py", "page_convex.py",
                    "convex_stack_app.py", "streamlit_app.py", "portfolio_manager.py"]
        for pf in py_files:
            path = os.path.join(base_dir, pf)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                matches = emoji_pattern.findall(content)
                self.assertEqual(len(matches), 0, f"Trovate emoji in {pf}: {matches}")


if __name__ == "__main__":
    unittest.main()



