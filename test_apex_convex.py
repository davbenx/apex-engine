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

    def test_portfolio_manager_smart_flow(self):
        """Verifica che la sintesi unificata rilevi correttamente lo squilibrio tra i motori."""
        holdings = {"NTSG": 585, "AVWS": 390, "DBMFE": 1300, "PPFB": 195, "WBTC": 97.5}
        prices = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
        c_rep = convex_engine.evaluate_convex_stack(holdings, prices, monthly_pac_eur=600.0)

        # Caso: Apex a 50k (27.7%) vs Convex a 130k (72.2%) con target Apex a 45%
        unified = portfolio_manager.compute_unified_portfolio(50000.0, c_rep, monthly_pac=600.0, target_apex_ratio=0.45)
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
        holdings = {"NTSG": 585, "AVWS": 390, "DBMFE": 1300, "PPFB": 195, "WBTC": 97.5}
        prices = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
        c_rep = convex_engine.evaluate_convex_stack(holdings, prices, monthly_pac_eur=0.0)
        self.assertIsNone(c_rep.pac_action, "Con PAC 0 non deve esserci un'azione consigliata")
        # Apex in equilibrio col target (non sottopesato) + Convex report con
        # pac_action=None: prima di questo fix, andava in crash qui sotto.
        unified = portfolio_manager.compute_unified_portfolio(
            100000.0, c_rep, monthly_pac=0.0, target_apex_ratio=0.45
        )
        self.assertIn("Nessun versamento", unified["smart_flow_note"])

    def test_simple_instruments_weights_sum_to_one(self):
        """Regressione: i pesi della versione Semplice (4 strumenti, senza
        AVWS) devono sommare esattamente a 1.0 — prima sommavano a 0.999 per
        via di letterali troncati a mano a 3 decimali."""
        weights = [info["target_weight"] for info in convex_engine.CONVEX_INSTRUMENTS_SIMPLE.values()]
        self.assertAlmostEqual(sum(weights), 1.0, places=6)

    def test_negative_holdings_never_produce_negative_value(self):
        """Difesa: quote negative (input malformato, non raggiungibile dalla
        UI che impone min_value=0.0, ma possibile da una chiamata diretta alla
        funzione) non devono produrre un valore di posizione negativo."""
        report = convex_engine.evaluate_convex_stack(
            {"NTSG": -500, "WBTC": 100}, {"NTSG": 100.0, "WBTC": 100.0}, monthly_pac_eur=600.0
        )
        self.assertEqual(report.assets["NTSG"].current_value, 0.0)
        self.assertGreaterEqual(report.total_value, 0.0)


if __name__ == "__main__":
    unittest.main()
