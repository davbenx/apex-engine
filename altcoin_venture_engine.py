"""
altcoin_venture_engine.py — Motore Asimmetrico Venture Satellite Altcoin
================================================================================
Gestione quantitativa a convessita' asimmetrica (Power-Law) su token alternativi:
- Budget rigorosamente isolato e ring-fenced (default 2% Net Worth)
- Sizing a slot fissi (default 10 slot)
- Protocollo Free-Ride: al +100% (2x) liquidazione automatica del 50% per recuperare
  il 100% del capitale iniziale investito (azzeramento del rischio di rovina)
- Ladder di prese di profitto progressive (+300%, +700%, +1500%) con trailing stop
- Profit Recycling Loop: travaso degli utili realizzati verso il portafoglio principale
================================================================================
"""

from __future__ import annotations
import datetime
import json
import os
from typing import Dict, List, Optional, Tuple, Any

DEFAULT_PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "venture_altcoin_portfolio.json")

DEFAULT_BUDGET_EUR = 10000.0  # 5% su 200.000 EUR
DEFAULT_MAX_SLOTS = 10  # 10 slot da 1.000 EUR
HARD_STOP_LOSS_PCT = -0.40  # -40% dal prezzo di ingresso
FREE_RIDE_MULTIPLIER = 2.25  # +125% (2.25x): recupero 100% capitale vendendo solo il 44.4% delle quote
FREE_RIDE_SELL_FRACTION = 1.0 / FREE_RIDE_MULTIPLIER  # ~0.4444
TRAILING_STOP_MOONBAG_PCT = 0.30  # Trailing stop del 30% dal massimo post-Milestone 2
BREAKOUT_LOOKBACK_DAYS = 30  # Lookback breakout ottimale
RS_LOOKBACK_DAYS = 20  # Lookback forza relativa vs BTC ottimale

# Kill-switch pre-committato
KILL_SWITCH_MAX_DRAWDOWN_PCT = -0.40  # Floor al -40% del budget (es. 6.000 EUR su 10.000 EUR)
KILL_SWITCH_MAX_RELATIVE_LAG_PCT = -0.15  # Sotto-performance massima tollerabile vs BTC B&H

SATELLITE_TARGET_OPTIONS = {
    "2.5%": {"pct": 0.025, "budget_eur": 5000.0, "slots": 5, "slot_size_eur": 1000.0},
    "5.0%": {"pct": 0.050, "budget_eur": 10000.0, "slots": 10, "slot_size_eur": 1000.0},
    "7.5%": {"pct": 0.075, "budget_eur": 15000.0, "slots": 15, "slot_size_eur": 1000.0},
    "10.0%": {"pct": 0.100, "budget_eur": 20000.0, "slots": 20, "slot_size_eur": 1000.0},
    "12.5%": {"pct": 0.125, "budget_eur": 25000.0, "slots": 25, "slot_size_eur": 1000.0},
}

# Blacklist tassativa: token wrapped, derivati di staking e stablecoins
EXCLUDED_CRYPTO_SYMBOLS = {
    # Wrapped tokens e liquid staking
    "WBTC", "WETH", "STETH", "CBBTC", "WBNB", "WSOL", "RETH", "TBTC", "WBETH", "FBTC", "LBTC",
    # Stablecoins fiat-pegged e algoritmiche
    "USDT", "USDC", "DAI", "FDUSD", "USDE", "TUSD", "EURC", "EURT", "PYUSD", "BUSD", "GUSD", "FRAX", "LUSD", "USDD"
}

KRAKEN_FUTURES_INSTRUMENTS_URL = "https://futures.kraken.com/derivatives/api/v3/instruments"


class VentureAltcoinEngine:
    """
    Motore quantitativo per la gestione del portafoglio Venture Satellite Altcoin.
    """

    def __init__(self, portfolio_path: str = DEFAULT_PORTFOLIO_PATH):
        self.portfolio_path = portfolio_path
        self.state: Dict[str, Any] = self.load_portfolio()

    def load_portfolio(self) -> Dict[str, Any]:
        if os.path.exists(self.portfolio_path):
            try:
                with open(self.portfolio_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[WARN] Errore lettura {self.portfolio_path}: {e}")
        return self._create_default_state()

    def _create_default_state(self) -> Dict[str, Any]:
        return {
            "budget_total_eur": DEFAULT_BUDGET_EUR,
            "max_slots": DEFAULT_MAX_SLOTS,
            "recycled_profits_eur": 0.0,
            "cash_available_eur": DEFAULT_BUDGET_EUR,
            "positions": {},
            "trade_history": []
        }

    def save_portfolio(self) -> None:
        try:
            with open(self.portfolio_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=4)
        except Exception as e:
            print(f"[ERROR] Impossibile salvare {self.portfolio_path}: {e}")

    def get_slot_size_eur(self) -> float:
        return round(self.state["budget_total_eur"] / max(1, self.state["max_slots"]), 2)

    def set_satellite_budget(self, budget_eur: float, max_slots: int = 10) -> None:
        """
        Aggiorna la dimensione del budget del satellite (es. 2.5%, 5.0%, 7.5%, 10.0%, 12.5%).
        """
        diff = budget_eur - self.state["budget_total_eur"]
        self.state["budget_total_eur"] = float(budget_eur)
        self.state["max_slots"] = int(max_slots)
        self.state["cash_available_eur"] = max(0.0, round(self.state["cash_available_eur"] + diff, 2))
        self.save_portfolio()

    def check_kill_switch(
        self,
        eur_usd_rate: float = 1.0850,
        btc_perf_since_inception: float = 0.0
    ) -> Dict[str, Any]:
        """
        Verifica i due criteri quantitativi pre-committati di Kill-Switch:
        1. Drawdown del satellite > 40% dal budget iniziale (Floor a 60% del capitale).
        2. Sotto-performance relativa vs BTC Buy & Hold > 15 punti percentuali.
        """
        summary = self.get_portfolio_summary(eur_usd_rate=eur_usd_rate)
        total_equity = summary["total_satellite_equity_eur"]
        budget = float(self.state.get("budget_total_eur", DEFAULT_BUDGET_EUR))
        floor_equity = round(budget * (1.0 + KILL_SWITCH_MAX_DRAWDOWN_PCT), 2)

        dd_pct = (total_equity - budget) / budget if budget > 0 else 0.0
        is_dd_triggered = dd_pct <= KILL_SWITCH_MAX_DRAWDOWN_PCT

        perf_satellite = dd_pct
        relative_lag = perf_satellite - btc_perf_since_inception
        is_lag_triggered = relative_lag <= KILL_SWITCH_MAX_RELATIVE_LAG_PCT

        triggered = is_dd_triggered or is_lag_triggered

        if is_dd_triggered:
            status = "TRIGGERED_DRAWDOWN"
            reason = f"Drawdown satellite ({dd_pct * 100:.1f}%) ha superato la soglia di kill-switch (-40.0%). Valore residuo: {total_equity:.2f} EUR (Floor: {floor_equity:.2f} EUR)."
            action = "LIQUIDARE IMMEDIATAMENTE TUTTI I CONTRATTI E CONGELARE IL SATELLITE PER 180 GIORNI"
        elif is_lag_triggered:
            status = "TRIGGERED_RELATIVE_LAG"
            reason = f"Sotto-performance rispetto a BTC Buy & Hold ({relative_lag * 100:.1f}%) ha superato la soglia critica (-15.0%)."
            action = "AZZERARE IL SATELLITE E RIASSORBIRE IL CAPITALE RESIDUO NELLA QUOTA BITCOIN DI APEX"
        else:
            status = "NORMALE"
            reason = "Parametri di rischio entro le soglie di tolleranza quantitative."
            action = "Operativita' regolare consentita nel rispetto delle regole di money management"

        return {
            "triggered": triggered,
            "status": status,
            "reason": reason,
            "action": action,
            "current_equity_eur": round(total_equity, 2),
            "budget_eur": round(budget, 2),
            "floor_equity_eur": floor_equity,
            "drawdown_pct": round(dd_pct * 100.0, 2),
            "relative_lag_pct": round(relative_lag * 100.0, 2)
        }

    @staticmethod
    def get_dynamic_allocation_target(breadth_pct: float, macro_gate_active: bool, net_worth: float = 200000.0) -> Dict[str, Any]:
        """
        Calcola l'allocazione dinamica target del satellite in funzione del regime macro e dell'ampiezza di mercato:
        - Macro Bearish: 0.0% (100% Cassa).
        - Macro Bullish & Breadth < 40%: 2.5% (allocazione cautelativa).
        - Macro Bullish & Breadth 40% - 75%: 5.0% - 7.5% (allocazione standard/target ottimale).
        - Macro Bullish & Breadth > 80%: 5.0% (de-escalation preventiva da surriscaldamento/mania).
        """
        if not macro_gate_active:
            return {
                "target_pct": 0.0,
                "target_eur": 0.0,
                "slots_max": 0,
                "regime_label": "RISK-OFF (100% Cassa / Riserva Protetta)",
                "action": "Nessun nuovo slot; posizioni protette da trailing stop"
            }
        if breadth_pct < 40.0:
            target_pct = 0.025
            return {
                "target_pct": target_pct,
                "target_eur": round(net_worth * target_pct, 2),
                "slots_max": 5,
                "regime_label": "CAUTELATIVO (Breadth ristretto <40%)",
                "action": "Massimo 5 slot da 1.000 EUR solo su leader assoluti"
            }
        if breadth_pct <= 75.0:
            target_pct = 0.075
            return {
                "target_pct": target_pct,
                "target_eur": round(net_worth * target_pct, 2),
                "slots_max": 15,
                "regime_label": "ESPANSIONE TARGET (Breadth sano 40%-75%)",
                "action": "Piena allocazione target su 10-15 slot da 1.000 EUR"
            }
        target_pct = 0.050
        return {
            "target_pct": target_pct,
            "target_eur": round(net_worth * target_pct, 2),
            "slots_max": 10,
            "regime_label": "MANIA / IPERESTENSIONE (Breadth >80%)",
            "action": "De-escalation difensiva: congelare nuovi slot, stringere trailing stop"
        }

    def open_position(
        self,
        ticker: str,
        name: str,
        entry_price_usd: float,
        sector: str = "General",
        custom_capital_eur: Optional[float] = None,
        entry_date: Optional[str] = None,
        eur_usd_rate: float = 1.0850
    ) -> Dict[str, Any]:
        ticker = ticker.upper().strip()
        if ticker in self.state["positions"]:
            raise ValueError(f"Posizione su {ticker} gia' aperta nel satellite.")

        capital_eur = custom_capital_eur if custom_capital_eur is not None else self.get_slot_size_eur()
        if capital_eur > self.state["cash_available_eur"]:
            raise ValueError(
                f"Liquidita' insufficiente nel satellite ({self.state['cash_available_eur']:.2f} EUR) per allocare {capital_eur:.2f} EUR."
            )

        if entry_date is None:
            entry_date = datetime.datetime.now().strftime("%Y-%m-%d")

        capital_usd = capital_eur * eur_usd_rate
        initial_shares = capital_usd / entry_price_usd

        pos = {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "entry_date": entry_date,
            "entry_price_usd": entry_price_usd,
            "current_price_usd": entry_price_usd,
            "highest_price_usd": entry_price_usd,
            "initial_shares": initial_shares,
            "current_shares": initial_shares,
            "initial_cost_eur": capital_eur,
            "initial_cost_usd": capital_usd,
            "capital_recovered_eur": 0.0,
            "realized_pnl_eur": 0.0,
            "is_free_ride": False,
            "milestones_reached": [],
            "next_target_usd": round(entry_price_usd * FREE_RIDE_MULTIPLIER, 4),
            "next_target_label": f"Milestone 1 (+{(FREE_RIDE_MULTIPLIER - 1.0) * 100:.0f}% / {FREE_RIDE_MULTIPLIER:.2f}x): Free-Ride (Sell {FREE_RIDE_SELL_FRACTION * 100:.1f}%)",
            "stop_loss_usd": round(entry_price_usd * (1.0 + HARD_STOP_LOSS_PCT), 4),
            "status": "OPEN"
        }

        self.state["positions"][ticker] = pos
        self.state["cash_available_eur"] = round(self.state["cash_available_eur"] - capital_eur, 2)

        self.state["trade_history"].append({
            "date": entry_date,
            "ticker": ticker,
            "action": "BUY",
            "price_usd": entry_price_usd,
            "shares": initial_shares,
            "total_eur": capital_eur,
            "note": "Apertura posizione slot Venture Satellite"
        })

        self.save_portfolio()
        return pos

    def update_price(self, ticker: str, current_price_usd: float) -> Dict[str, Any]:
        ticker = ticker.upper().strip()
        if ticker not in self.state["positions"]:
            raise KeyError(f"Posizione {ticker} non trovata.")

        pos = self.state["positions"][ticker]
        pos["current_price_usd"] = current_price_usd
        if current_price_usd > pos.get("highest_price_usd", 0.0):
            pos["highest_price_usd"] = current_price_usd

        # Aggiorna prossimo target o trailing stop se già superata la Milestone 2
        mult = current_price_usd / pos["entry_price_usd"]
        p0 = pos["entry_price_usd"]

        if not pos["is_free_ride"]:
            pos["next_target_usd"] = round(p0 * FREE_RIDE_MULTIPLIER, 4)
            pos["next_target_label"] = f"Milestone 1 (+{(FREE_RIDE_MULTIPLIER-1.0)*100:.0f}% / {FREE_RIDE_MULTIPLIER:.2f}x): Free-Ride (Sell {FREE_RIDE_SELL_FRACTION*100:.1f}%)"
        elif "M2_300PCT" not in pos["milestones_reached"]:
            pos["next_target_usd"] = round(p0 * 4.0, 4)
            pos["next_target_label"] = "Milestone 2 (+300% / 4x): Take-Profit 20%"
        elif "M3_700PCT" not in pos["milestones_reached"]:
            pos["next_target_usd"] = round(p0 * 8.0, 4)
            pos["next_target_label"] = "Milestone 3 (+700% / 8x): Take-Profit 25%"
        elif "M4_1500PCT" not in pos["milestones_reached"]:
            pos["next_target_usd"] = round(p0 * 16.0, 4)
            pos["next_target_label"] = "Milestone 4 (+1500% / 16x): Take-Profit 50%"
        else:
            # Runner finale: trailing stop del 30% dal massimo
            trailing_stop = pos["highest_price_usd"] * (1.0 - TRAILING_STOP_MOONBAG_PCT)
            pos["next_target_usd"] = round(trailing_stop, 4)
            pos["next_target_label"] = f"Trailing Stop Moonbag (-30% da max {pos['highest_price_usd']:.4f}$)"

        return pos

    def evaluate_signals(self, eur_usd_rate: float = 1.0850) -> List[Dict[str, Any]]:
        """
        Analizza tutte le posizioni aperte e genera la lista dei segnali esecutivi (Take Profit o Stop Loss).
        """
        signals = []
        for ticker, pos in list(self.state["positions"].items()):
            p_cur = pos["current_price_usd"]
            p0 = pos["entry_price_usd"]
            mult = p_cur / p0

            # 1. Controllo Hard Stop Loss (solo prima di Free-Ride)
            if not pos["is_free_ride"] and p_cur <= pos["stop_loss_usd"]:
                signals.append({
                    "ticker": ticker,
                    "type": "STOP_LOSS",
                    "action": "SELL_ALL",
                    "reason": f"Hard Stop Loss toccato a {p_cur:.4f}$ ({HARD_STOP_LOSS_PCT*100:.0f}% dall'ingresso)",
                    "shares_to_sell": pos["current_shares"],
                    "price_usd": p_cur
                })
                continue

            # 2. Controllo Milestone 1: Free Ride (2.25x)
            if not pos["is_free_ride"] and p_cur >= (p0 * FREE_RIDE_MULTIPLIER):
                shares_sell = pos["initial_shares"] * FREE_RIDE_SELL_FRACTION
                signals.append({
                    "ticker": ticker,
                    "type": "MILESTONE_1_FREE_RIDE",
                    "action": "SELL_FREE_RIDE",
                    "reason": f"Raggiunto +{(FREE_RIDE_MULTIPLIER-1.0)*100:.0f}% ({mult:.2f}x). Vendita {FREE_RIDE_SELL_FRACTION*100:.1f}% per recuperare integralmente il capitale iniziale ({pos['initial_cost_eur']:.2f} EUR)",
                    "shares_to_sell": min(shares_sell, pos["current_shares"]),
                    "price_usd": p_cur
                })
                continue

            # 3. Controllo Milestone 2: +300% / 4x
            if pos["is_free_ride"] and "M2_300PCT" not in pos["milestones_reached"] and p_cur >= (p0 * 4.0):
                shares_sell = pos["current_shares"] * 0.20
                signals.append({
                    "ticker": ticker,
                    "type": "MILESTONE_2",
                    "action": "SELL_20_PCT_CURRENT",
                    "reason": f"Raggiunto +300% ({mult:.2f}x). Liquidazione 20% della quota residua.",
                    "shares_to_sell": shares_sell,
                    "price_usd": p_cur
                })
                continue

            # 4. Controllo Milestone 3: +700% / 8x
            if pos["is_free_ride"] and "M3_700PCT" not in pos["milestones_reached"] and p_cur >= (p0 * 8.0):
                shares_sell = pos["current_shares"] * 0.25
                signals.append({
                    "ticker": ticker,
                    "type": "MILESTONE_3",
                    "action": "SELL_25_PCT_CURRENT",
                    "reason": f"Raggiunto +700% ({mult:.2f}x). Liquidazione 25% della quota residua.",
                    "shares_to_sell": shares_sell,
                    "price_usd": p_cur
                })
                continue

            # 5. Controllo Milestone 4: +1500% / 16x
            if pos["is_free_ride"] and "M4_1500PCT" not in pos["milestones_reached"] and p_cur >= (p0 * 16.0):
                shares_sell = pos["current_shares"] * 0.50
                signals.append({
                    "ticker": ticker,
                    "type": "MILESTONE_4",
                    "action": "SELL_50_PCT_CURRENT",
                    "reason": f"Raggiunto +1500% ({mult:.2f}x). Liquidazione 50% della quota residua.",
                    "shares_to_sell": shares_sell,
                    "price_usd": p_cur
                })
                continue

            # 6. Controllo Trailing Stop Runner Moonbag (dopo Milestone 2)
            if "M2_300PCT" in pos["milestones_reached"]:
                trailing_thresh = pos["highest_price_usd"] * (1.0 - TRAILING_STOP_MOONBAG_PCT)
                if p_cur <= trailing_thresh:
                    signals.append({
                        "ticker": ticker,
                        "type": "TRAILING_STOP",
                        "action": "SELL_ALL",
                        "reason": f"Trailing stop scattato a {p_cur:.4f}$ (-30% dal massimo di {pos['highest_price_usd']:.4f}$)",
                        "shares_to_sell": pos["current_shares"],
                        "price_usd": p_cur
                    })

        return signals

    def execute_sell_signal(
        self,
        signal: Dict[str, Any],
        exec_price_usd: Optional[float] = None,
        date_str: Optional[str] = None,
        eur_usd_rate: float = 1.0850
    ) -> Dict[str, Any]:
        ticker = signal["ticker"]
        pos = self.state["positions"].get(ticker)
        if not pos:
            raise KeyError(f"Posizione {ticker} non presente.")

        px = exec_price_usd if exec_price_usd is not None else signal["price_usd"]
        shares = min(signal["shares_to_sell"], pos["current_shares"])
        if date_str is None:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")

        proceeds_usd = shares * px
        proceeds_eur = round(proceeds_usd / eur_usd_rate, 2)

        sig_type = signal["type"]

        if sig_type == "MILESTONE_1_FREE_RIDE":
            pos["is_free_ride"] = True
            pos["capital_recovered_eur"] += proceeds_eur
            pos["milestones_reached"].append("M1_FREE_RIDE")
            # Rimette in cassa il capitale iniziale
            self.state["cash_available_eur"] = round(self.state["cash_available_eur"] + pos["initial_cost_eur"], 2)
            profit_excess_eur = max(0.0, proceeds_eur - pos["initial_cost_eur"])
            if profit_excess_eur > 0:
                self.state["recycled_profits_eur"] = round(self.state["recycled_profits_eur"] + profit_excess_eur, 2)
                pos["realized_pnl_eur"] = round(pos["realized_pnl_eur"] + profit_excess_eur, 2)
        elif sig_type.startswith("MILESTONE_"):
            m_code = sig_type.replace("MILESTONE_", "M") + "PCT"
            pos["milestones_reached"].append(m_code)
            # Tutto il ricavato è profitto puro (capitale già recuperato)
            self.state["recycled_profits_eur"] = round(self.state["recycled_profits_eur"] + proceeds_eur, 2)
            pos["realized_pnl_eur"] = round(pos["realized_pnl_eur"] + proceeds_eur, 2)
        elif sig_type in ("STOP_LOSS", "TRAILING_STOP"):
            # Chiusura totale
            if pos["is_free_ride"]:
                self.state["recycled_profits_eur"] = round(self.state["recycled_profits_eur"] + proceeds_eur, 2)
                pos["realized_pnl_eur"] = round(pos["realized_pnl_eur"] + proceeds_eur, 2)
            else:
                pnl = proceeds_eur - pos["initial_cost_eur"]
                pos["realized_pnl_eur"] = round(pos["realized_pnl_eur"] + pnl, 2)
                self.state["cash_available_eur"] = round(self.state["cash_available_eur"] + proceeds_eur, 2)

        pos["current_shares"] = max(0.0, pos["current_shares"] - shares)

        self.state["trade_history"].append({
            "date": date_str,
            "ticker": ticker,
            "action": "SELL",
            "type": sig_type,
            "price_usd": px,
            "shares": shares,
            "total_eur": proceeds_eur,
            "reason": signal["reason"]
        })

        if pos["current_shares"] < 1e-6 or sig_type in ("STOP_LOSS", "TRAILING_STOP"):
            pos["status"] = "CLOSED"
            del self.state["positions"][ticker]

        self.save_portfolio()
        return {"status": "SUCCESS", "proceeds_eur": proceeds_eur, "ticker": ticker, "type": sig_type}

    def get_portfolio_summary(self, eur_usd_rate: float = 1.0850) -> Dict[str, Any]:
        positions = self.state.get("positions", {})
        total_initial_cost_eur = sum(p["initial_cost_eur"] for p in positions.values())
        total_current_val_usd = sum(p["current_shares"] * p["current_price_usd"] for p in positions.values())
        total_current_val_eur = round(total_current_val_usd / eur_usd_rate, 2)

        unrealized_pnl_eur = round(total_current_val_eur - total_initial_cost_eur, 2)
        free_rides_count = sum(1 for p in positions.values() if p.get("is_free_ride", False))

        total_satellite_equity_eur = round(self.state["cash_available_eur"] + total_current_val_eur, 2)

        rows = []
        for sym, p in sorted(positions.items(), key=lambda x: x[1]["current_price_usd"] / x[1]["entry_price_usd"], reverse=True):
            mult = p["current_price_usd"] / p["entry_price_usd"]
            val_usd = p["current_shares"] * p["current_price_usd"]
            val_eur = val_usd / eur_usd_rate
            rows.append({
                "Ticker": sym,
                "Nome": p.get("name", sym),
                "Settore": p.get("sector", "General"),
                "Prezzo Carico ($)": round(p["entry_price_usd"], 4),
                "Prezzo Attuale ($)": round(p["current_price_usd"], 4),
                "Moltiplicatore": f"{mult:.2f}x",
                "P&L Non Real. (%)": f"{(mult - 1.0)*100:+.1f}%",
                "Valore Posizione (€)": round(val_eur, 2),
                "Stato": "FREE RIDE" if p["is_free_ride"] else "A RISCHIO",
                "Prossimo Target ($)": round(p.get("next_target_usd", 0.0), 4),
                "Azione al Target": p.get("next_target_label", "In attesa"),
                "Capitale Iniziale (€)": round(p["initial_cost_eur"], 2),
                "Capitale Recuperato (€)": round(p["capital_recovered_eur"], 2)
            })

        return {
            "budget_total_eur": self.state["budget_total_eur"],
            "cash_available_eur": self.state["cash_available_eur"],
            "recycled_profits_eur": self.state["recycled_profits_eur"],
            "total_current_val_eur": total_current_val_eur,
            "total_satellite_equity_eur": total_satellite_equity_eur,
            "unrealized_pnl_eur": unrealized_pnl_eur,
            "open_positions_count": len(positions),
            "free_rides_count": free_rides_count,
            "positions_table": rows
        }


# ==============================================================================
# FUNZIONE DI SIMULAZIONE SCENARIO ASIMMETRICO (BACKTEST CASO STUDIO)
# ==============================================================================
def simulate_asymmetric_lifecycle(
    ticker: str,
    price_series: List[Tuple[str, float]],
    initial_capital_eur: float = 400.0,
    eur_usd_rate: float = 1.0850
) -> Dict[str, Any]:
    """
    Simula il ciclo di vita di una singola posizione sotto le regole asimmetriche
    (Free Ride al 2x, ladder di milestone, trailing stop e riciclo utili).
    """
    if not price_series:
        return {}

    entry_date, p0 = price_series[0]
    initial_shares = (initial_capital_eur * eur_usd_rate) / p0
    current_shares = initial_shares

    recovered_eur = 0.0
    recycled_profits_eur = 0.0
    is_free_ride = False
    milestones_reached = set()
    highest_price = p0

    trades = [{"date": entry_date, "action": "BUY", "price": p0, "shares": initial_shares, "eur": initial_capital_eur}]

    for dt, px in price_series[1:]:
        if px > highest_price:
            highest_price = px

        # 1. Hard stop loss
        if not is_free_ride and px <= (p0 * (1.0 + HARD_STOP_LOSS_PCT)):
            proceeds = (current_shares * px) / eur_usd_rate
            recovered_eur += proceeds
            trades.append({"date": dt, "action": "STOP_LOSS", "price": px, "shares": current_shares, "eur": proceeds})
            current_shares = 0.0
            break

        # 2. Milestone 1: Free Ride
        if not is_free_ride and px >= (p0 * FREE_RIDE_MULTIPLIER):
            sh_sell = initial_shares * FREE_RIDE_SELL_FRACTION
            proceeds = (sh_sell * px) / eur_usd_rate
            recovered_eur += proceeds
            is_free_ride = True
            current_shares -= sh_sell
            trades.append({"date": dt, "action": f"FREE_RIDE_{int(FREE_RIDE_SELL_FRACTION * 100)}_PCT", "price": px, "shares": sh_sell, "eur": proceeds})

        # 3. Milestone 2: 4x (+300%)
        if is_free_ride and "M2" not in milestones_reached and px >= (p0 * 4.0):
            sh_sell = current_shares * 0.20
            proceeds = (sh_sell * px) / eur_usd_rate
            recycled_profits_eur += proceeds
            milestones_reached.add("M2")
            current_shares -= sh_sell
            trades.append({"date": dt, "action": "TAKE_PROFIT_M2_4X", "price": px, "shares": sh_sell, "eur": proceeds})

        # 4. Milestone 3: 8x (+700%)
        if is_free_ride and "M3" not in milestones_reached and px >= (p0 * 8.0):
            sh_sell = current_shares * 0.25
            proceeds = (sh_sell * px) / eur_usd_rate
            recycled_profits_eur += proceeds
            milestones_reached.add("M3")
            current_shares -= sh_sell
            trades.append({"date": dt, "action": "TAKE_PROFIT_M3_8X", "price": px, "shares": sh_sell, "eur": proceeds})

        # 5. Trailing stop dopo M2
        if "M2" in milestones_reached and px <= (highest_price * (1.0 - TRAILING_STOP_MOONBAG_PCT)):
            proceeds = (current_shares * px) / eur_usd_rate
            recycled_profits_eur += proceeds
            trades.append({"date": dt, "action": "TRAILING_STOP_EXIT", "price": px, "shares": current_shares, "eur": proceeds})
            current_shares = 0.0
            break

    final_val_eur = (current_shares * price_series[-1][1]) / eur_usd_rate
    total_extracted_eur = recovered_eur + recycled_profits_eur
    net_pnl_eur = (total_extracted_eur + final_val_eur) - initial_capital_eur
    return {
        "ticker": ticker,
        "initial_capital_eur": initial_capital_eur,
        "recovered_capital_eur": round(recovered_eur, 2),
        "recycled_profits_eur": round(recycled_profits_eur, 2),
        "final_position_val_eur": round(final_val_eur, 2),
        "net_pnl_eur": round(net_pnl_eur, 2),
        "roi_pct": round((net_pnl_eur / initial_capital_eur) * 100.0, 1),
        "is_free_ride": is_free_ride,
        "trades_count": len(trades),
        "trades": trades
    }


def get_kraken_futures_instruments() -> Dict[str, Dict[str, Any]]:
    """
    Interroga le API pubbliche di Kraken Futures per estrarre tutti i contratti
    perpetual attivi (PF_*), escludendo tassativamente:
    - Token Wrapped (WBTC, WETH, stETH, etc.)
    - Stablecoin (USDT, USDC, DAI, etc.)
    - Contratti su indici / stock tradfi
    Ritorna un dizionario: base_ticker -> {symbol, pair, category, quote}
    """
    import urllib.request
    try:
        req = urllib.request.Request(
            KRAKEN_FUTURES_INSTRUMENTS_URL,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            instruments = data.get("instruments", [])

        clean_map = {}
        for i in instruments:
            sym = i.get("symbol", "")
            if not sym.startswith("PF_") or not i.get("tradeable") or i.get("tradfi") is True:
                continue
            base = i.get("base", "").upper()
            quote = i.get("quote", "").upper()
            if not base or base in EXCLUDED_CRYPTO_SYMBOLS:
                continue
            if base.endswith("X") and len(base) > 4:
                continue
            if quote in ("USD", "EUR"):
                clean_map[base] = {
                    "symbol": sym,
                    "pair": i.get("pair", f"{base}:{quote}"),
                    "category": i.get("category", "Crypto"),
                    "quote": quote
                }
        if clean_map:
            return clean_map
    except Exception as e:
        print(f"[WARN] Impossibile contattare Kraken Futures API ({e}). Uso fallback offline.")

    fallback_bases = [
        "SOL", "AVAX", "NEAR", "LINK", "DOT", "ADA", "XRP", "DOGE", "LTC", "ATOM",
        "SUI", "APT", "ARB", "OP", "RENDER", "INJ", "TIA", "SEI", "FET", "AAVE", "BCH", "FIL", "TRX", "UNI"
    ]
    return {b: {"symbol": f"PF_{b}USD", "pair": f"{b}:USD", "category": "Crypto", "quote": "USD"} for b in fallback_bases}


DEFAULT_CRYPTO_CACHE_JSON = os.path.join(os.path.dirname(__file__), "crypto_screener_cache.json")

YAHOO_CRYPTO_MAP = {
    "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD", "AVAX": "AVAX-USD",
    "NEAR": "NEAR-USD", "LINK": "LINK-USD", "DOT": "DOT-USD", "ADA": "ADA-USD",
    "DOGE": "DOGE-USD", "LTC": "LTC-USD", "RENDER": "RENDER-USD", "INJ": "INJ-USD",
    "AAVE": "AAVE-USD", "FET": "FET-USD", "ATOM": "ATOM-USD", "ALGO": "ALGO-USD",
    "SUI": "SUI20947-USD", "ARB": "ARB11841-USD", "OP": "OP-USD", "SEI": "SEI-USD",
    "KAS": "KAS-USD", "XRP": "XRP-USD", "BCH": "BCH-USD", "FIL": "FIL-USD",
    "TRX": "TRX-USD", "UNI": "UNI7083-USD"
}


def load_crypto_universe_data(
    force_live: bool = False,
    timeout_sec: int = 4
) -> Tuple[Dict[str, Any], Optional[Any]]:
    """
    Carica le serie storiche dei prezzi di chiusura giornalieri per l'universo di contratti liquidi
    su Kraken Futures e Bitcoin.
    Architettura multi-tier:
    1. Base offline/cache: carica crypto_screener_cache.json tracciato nel repository Git.
    2. Overlay live: esegue query concorrente leggera alle API Yahoo Finance (ThreadPoolExecutor)
       per aggiornare le candele odierne in tempo reale.
    3. Fallback trasparente: se offline o se le API non rispondono, i dati storici del file JSON
       garantiscono il funzionamento immediato senza errori su qualsiasi istanza Cloud o locale.
    """
    import pandas as pd
    import urllib.request
    import time
    from concurrent.futures import ThreadPoolExecutor

    dfs: Dict[str, pd.Series] = {}

    # 1. Caricamento da bundle JSON locale tracciato nel repository Git
    if os.path.exists(DEFAULT_CRYPTO_CACHE_JSON):
        try:
            with open(DEFAULT_CRYPTO_CACHE_JSON, "r", encoding="utf-8") as f:
                cached_raw = json.load(f)
            for sym, item in cached_raw.items():
                if isinstance(item, dict) and "dates" in item and "closes" in item:
                    idx = pd.to_datetime(item["dates"])
                    dfs[sym] = pd.Series(item["closes"], index=idx)
        except Exception as e:
            print(f"[WARN] Impossibile leggere {DEFAULT_CRYPTO_CACHE_JSON}: {e}")

    # 2. Fetch live concorrente per aggiornare alle quotazioni odierne
    def _fetch_single_ticker(ticker_item):
        base_sym, yf_tick = ticker_item
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{yf_tick}?range=1y&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode())
                res = data["chart"]["result"][0]
                timestamps = res["timestamp"]
                closes = res["indicators"]["quote"][0]["close"]
                clean_dates = []
                clean_closes = []
                for ts_val, c_val in zip(timestamps, closes):
                    if c_val is not None:
                        clean_dates.append(time.strftime("%Y-%m-%d", time.gmtime(ts_val)))
                        clean_closes.append(round(float(c_val), 6))
                if len(clean_closes) >= 30:
                    idx = pd.to_datetime(clean_dates)
                    return base_sym, pd.Series(clean_closes, index=idx)
        except Exception:
            pass
        return base_sym, None

    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            live_results = dict(executor.map(_fetch_single_ticker, YAHOO_CRYPTO_MAP.items()))
        for base_sym, s_px in live_results.items():
            if s_px is not None and not s_px.empty:
                dfs[base_sym] = s_px
    except Exception as e:
        print(f"[WARN] Fetch live concorrente non riuscito ({e}). Uso dati bundle.")

    # 3. Fallback su directory locali se il dizionario e' ancora vuoto
    if not dfs:
        for fallback_dir in ["/home/davide/Scaricati/trading/cache_daily", "research/crypto_ohlcv_cache"]:
            if os.path.exists(fallback_dir):
                import glob
                for csv_path in glob.glob(os.path.join(fallback_dir, "*-USD.csv")):
                    b_name = os.path.basename(csv_path).replace("-USD.csv", "").replace(".csv", "")
                    try:
                        df_local = pd.read_csv(csv_path, index_col=0, parse_dates=True)
                        c_col = "close" if "close" in df_local.columns else "Close"
                        if c_col in df_local.columns:
                            dfs[b_name] = df_local[c_col].dropna()
                    except Exception:
                        pass
                if dfs:
                    break

    btc_series = dfs.get("BTC", dfs.get("BTC-USD", None))
    return dfs, btc_series


def screen_venture_candidates(
    crypto_close_dict: Dict[str, Any],
    btc_series: Any,
    lookback_bo: int = BREAKOUT_LOOKBACK_DAYS,
    lookback_rs: int = RS_LOOKBACK_DAYS,
    cross_kraken_futures: bool = True
) -> Dict[str, Any]:
    """
    Esegue lo screening a 4 stadi sui token crypto:
    1. Gate Macro: Bitcoin > MA 40 settimane e Bitcoin > MA 20 settimane
    2. Breakout Tecnico: Prezzo attuale > Massimo a `lookback_bo` giorni
    3. Forza Relativa vs BTC: Rendimento a `lookback_rs` giorni > Rendimento BTC
    4. Filtro Kraken Futures & Esclusione Wrapped/Stablecoins: il token deve avere
       un contratto Perpetual (PF_*) liquido attivo su Kraken Futures.
    Ritorna lo stato del gate macro, i token in breakout immediato ('candidates')
    e l'intera classifica dell'universo ordinata per forza relativa ('ranked_universe').
    """
    if btc_series is None or len(btc_series) == 0:
        return {
            "macro_gate_active": False,
            "candidates": [],
            "ranked_universe": [],
            "note": "Dati BTC non disponibili"
        }

    btc_wc = btc_series.resample("W-FRI").last()
    btc_ma40 = float(btc_wc.rolling(40, min_periods=10).mean().iloc[-1])
    btc_ma20 = float(btc_wc.rolling(20, min_periods=5).mean().iloc[-1])
    cur_btc_px = float(btc_series.iloc[-1])

    macro_gate_active = (cur_btc_px > btc_ma40) and (cur_btc_px > btc_ma20)

    if len(btc_series) < lookback_rs + 1:
        btc_ret_rs = 0.0
    else:
        btc_ret_rs = (cur_btc_px / float(btc_series.iloc[-1 - lookback_rs])) - 1.0

    kraken_map = get_kraken_futures_instruments() if cross_kraken_futures else {}

    qualified = []
    ranked_universe = []

    for sym, s_px in crypto_close_dict.items():
        base_ticker = sym.replace("-USD", "").replace("USD", "").upper().strip()
        if base_ticker in ("BTC", "BITCOIN") or base_ticker in EXCLUDED_CRYPTO_SYMBOLS:
            continue
        if len(s_px) < max(lookback_bo + 5, lookback_rs + 5):
            continue

        kraken_info = kraken_map.get(base_ticker)
        if cross_kraken_futures and not kraken_info:
            continue

        p_cur = float(s_px.iloc[-1])
        roll_high = float(s_px.iloc[:-1].rolling(lookback_bo, min_periods=lookback_bo).max().iloc[-1])
        is_breakout = p_cur > roll_high
        dist_bo_pct = round(((p_cur / roll_high) - 1.0) * 100.0, 1)

        # Controllo SMA 20w (140d)
        if len(s_px) >= 140:
            sma_20w_val = float(s_px.rolling(140).mean().iloc[-1])
        else:
            sma_20w_val = float(s_px.mean())
        above_sma20w = p_cur > sma_20w_val

        # Controllo Volume Confirmation se disponibile
        vol_ratio = 1.0
        vol_confirmed = True
        if hasattr(s_px, "columns") and "Volume" in s_px.columns:
            s_vol = s_px["Volume"].dropna()
            if len(s_vol) >= 30:
                med_v = float(s_vol.iloc[:-1].rolling(30, min_periods=10).median().iloc[-1])
                cur_v = float(s_vol.iloc[-1])
                vol_ratio = round(cur_v / med_v, 2) if med_v > 0 else 1.0
                vol_confirmed = vol_ratio >= 1.5

        is_crowded = ((p_cur / roll_high) - 1.0) > 0.30

        p_prev_rs = float(s_px.iloc[-1 - lookback_rs])
        r_alt_rs = (p_cur / p_prev_rs) - 1.0 if p_prev_rs > 0 else -1.0
        rs_excess = (r_alt_rs - btc_ret_rs) * 100.0

        # Classificazione operativa qualitativa
        if is_breakout and rs_excess > 0:
            op_status = "BREAKOUT ATTIVO (BUY)"
        elif dist_bo_pct >= -5.0 and rs_excess > 0:
            op_status = "A RIDOSSO DEL BREAKOUT (<5%)"
        elif rs_excess > 0 and above_sma20w:
            op_status = "LEADER FORZA RELATIVA"
        elif above_sma20w:
            op_status = "TREND RIALZISTA"
        else:
            op_status = "FASE CORRETTIVA"

        token_summary = {
            "ticker": base_ticker,
            "kraken_symbol": kraken_info["symbol"] if kraken_info else f"PF_{base_ticker}USD",
            "kraken_category": kraken_info.get("category", "Crypto") if kraken_info else "Crypto",
            "price_usd": round(p_cur, 4),
            "breakout_level_usd": round(roll_high, 4),
            "breakout_pct": dist_bo_pct,
            "dist_breakout_pct": dist_bo_pct,
            "above_sma20w": above_sma20w,
            "trend_label": "SOPRA" if above_sma20w else "SOTTO",
            "sma20w_usd": round(sma_20w_val, 4),
            "alt_ret_20d_pct": round(r_alt_rs * 100.0, 1),
            "btc_ret_20d_pct": round(btc_ret_rs * 100.0, 1),
            "rs_excess_vs_btc_pct": round(rs_excess, 1),
            "vol_ratio_30d": vol_ratio,
            "vol_confirmed": vol_confirmed,
            "is_breakout": is_breakout,
            "is_crowded": is_crowded,
            "status": op_status
        }
        ranked_universe.append(token_summary)

        if is_breakout and rs_excess > 0:
            qualified.append(token_summary)

    # Ordinamento decrescente dell'universo per eccesso di forza relativa vs BTC
    ranked_universe.sort(key=lambda x: x["rs_excess_vs_btc_pct"], reverse=True)
    qualified.sort(key=lambda x: x["rs_excess_vs_btc_pct"], reverse=True)

    # Calcolo Altcoin Breadth (% altcoin sopra SMA 20w / 140d)
    alt_above_sma20w = 0
    total_valid_alts = 0
    for sym, s_px in crypto_close_dict.items():
        b_tick = sym.replace("-USD", "").replace("USD", "").upper().strip()
        if b_tick in ("BTC", "BITCOIN") or b_tick in EXCLUDED_CRYPTO_SYMBOLS:
            continue
        if len(s_px) >= 140:
            total_valid_alts += 1
            if float(s_px.iloc[-1]) > float(s_px.rolling(140).mean().iloc[-1]):
                alt_above_sma20w += 1

    breadth_pct = round((alt_above_sma20w / max(1, total_valid_alts)) * 100.0, 1) if total_valid_alts > 0 else 0.0
    if breadth_pct > 80.0:
        breadth_regime = "IPERESTENSO (Attenzione: possibile rotazione imminente, non inseguire)"
    elif breadth_pct >= 50.0:
        breadth_regime = "FAVOREVOLE (Espansione sana del mercato altcoin)"
    else:
        breadth_regime = "RESTRITTIVO (Solo leader in breakout relativo isolato)"

    return {
        "macro_gate_active": macro_gate_active,
        "btc_price_usd": round(cur_btc_px, 2),
        "btc_ma40w_usd": round(btc_ma40, 2),
        "btc_ma20w_usd": round(btc_ma20, 2),
        "altcoin_breadth_pct": breadth_pct,
        "altcoin_breadth_regime": breadth_regime,
        "candidates": qualified,
        "ranked_universe": ranked_universe,
        "kraken_filtered": cross_kraken_futures
    }


def build_venture_telegram_alert(
    screen_results: Dict[str, Any],
    signals_to_execute: List[Dict[str, Any]],
    portfolio_summary: Dict[str, Any]
) -> str:
    """
    Formatta l'alert Telegram istituzionale per Frontier Venture,
    rispettando la regola ferrea di zero emoji e lo stile di Convex/Apex.
    """
    oggi = datetime.date.today().strftime("%d/%m/%Y")
    macro_active = screen_results.get("macro_gate_active", False)
    btc_px = screen_results.get("btc_price_usd", 0.0)
    candidates = screen_results.get("candidates", [])
    ranked = screen_results.get("ranked_universe", [])

    status_macro = "[ATTIVO]" if macro_active else "[BLOCCATO]"
    regime_desc = "Acquisti autorizzati su Kraken Futures (BTC > MA40w/20w)" if macro_active else "100% Cash / Riserva (Nuovi acquisti congelati)"

    lines = [
        f"*FRONTIER VENTURE (SATELLITE ASIMMETRICO)* · {oggi}",
        "",
        f"*MACRO GATE BITCOIN*: {status_macro}",
        f"• Prezzo BTC: ${btc_px:,.2f}",
        f"• Regime: {regime_desc}",
        f"• Altcoin Breadth: {screen_results.get('altcoin_breadth_pct', 0.0)}% sopra SMA 20w ({screen_results.get('altcoin_breadth_regime', 'N/D')})",
        "",
        f"*STATO DEL SATELLITE ({portfolio_summary.get('budget_total_eur', 10000):,.0f} € - 5% NET WORTH)*:",
        f"• Cassa Disponibile: €{portfolio_summary.get('cash_available_eur', 0):,.2f}",
        f"• Posizioni Aperte: {portfolio_summary.get('open_positions_count', 0)} / {portfolio_summary.get('max_slots', 10)} slot",
        f"• Free-Rides Attivi (Rischio Zero): {portfolio_summary.get('free_rides_count', 0)}",
        f"• Profitti Riciclati su Apex/Convex: €{portfolio_summary.get('recycled_profits_eur', 0):,.2f}",
        ""
    ]

    if signals_to_execute:
        lines.append("*ORDINI OPERATIVI DA ESEGUIRE SU KRAKEN:*")
        for s in signals_to_execute:
            lines.append(f"• *{s['ticker']}*: {s['reason']}")
        lines.append("")

    if macro_active and candidates:
        lines.append(f"*TOKEN IN BREAKOUT SU KRAKEN FUTURES ({len(candidates)}):*")
        for c in candidates[:5]:
            lines.append(f"• *{c['ticker']}* ({c.get('kraken_symbol', 'PF')}) a ${c['price_usd']:.4f} | RS vs BTC: +{c['rs_excess_vs_btc_pct']:.1f}%")
        lines.append("")
    elif macro_active and ranked:
        lines.append("*LEADER FORZA RELATIVA IN WATCHLIST (PROSSIMI AL BREAKOUT):*")
        for w in ranked[:4]:
            lines.append(f"• *{w['ticker']}* (${w['price_usd']:.4f}) | Dist. BO: {w['dist_breakout_pct']:+.1f}% | RS vs BTC: +{w['rs_excess_vs_btc_pct']:+.1f}% [{w['status']}]")
        lines.append("")
    elif macro_active and not candidates:
        lines.append("• Nessun token in breakout qualificato su Kraken Futures alla data odierna.")
        lines.append("")

    lines.append("*REGOLE OPERATIVE KRAKEN FUTURES:*")
    lines.append("1. Leva 1x tassativa (zero margine, 100% collaterale in cassa).")
    lines.append("2. Stop Loss condizionato a -40% inserito subito su Index Price.")
    lines.append("3. Take Profit parziale Free-Ride al +125% (2.25x) per recuperare il 100% del capitale.")

    return "\n".join(lines)


def get_telegram_credentials(
    token: Optional[str] = None,
    chat_id: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Risolve le credenziali Telegram supportando gerarchicamente:
    1. Parametri espliciti token e chat_id
    2. Session state di Streamlit (se attivo nella sessione utente)
    3. Streamlit Cloud Secrets (st.secrets["TELEGRAM_TOKEN"] e st.secrets["TELEGRAM_CHAT_ID"])
    4. Variabili d'ambiente del sistema operativo (os.environ)
    """
    tok = token
    cid = chat_id

    # 1. Streamlit Session State se presente
    if not tok or not cid:
        try:
            import streamlit as st
            tok = tok or st.session_state.get("venture_tg_token")
            cid = cid or st.session_state.get("venture_tg_chat_id")
        except Exception:
            pass

    # 2. Streamlit Secrets (supporto nativo per deploy Streamlit Cloud)
    if not tok or not cid:
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                tok = tok or st.secrets.get("TELEGRAM_TOKEN")
                cid = cid or st.secrets.get("TELEGRAM_CHAT_ID")
        except Exception:
            pass

    # 3. Variabili d'ambiente sistema operativo
    if not tok or not cid:
        tok = tok or os.environ.get("TELEGRAM_TOKEN")
        cid = cid or os.environ.get("TELEGRAM_CHAT_ID")

    return tok, cid


def send_venture_telegram_alert(
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    crypto_close_dict: Optional[Dict[str, Any]] = None,
    btc_series: Optional[Any] = None,
    dry_run: bool = False
) -> Tuple[bool, str]:
    """
    Invia la notifica Telegram per Frontier Venture.
    Se dry_run=True ritorna solo il testo formattato.
    """
    import urllib.request
    import urllib.parse

    tok, cid = get_telegram_credentials(token, chat_id)

    engine = VentureAltcoinEngine()
    summary = engine.get_portfolio_summary()
    signals = engine.evaluate_signals()

    if crypto_close_dict is None or btc_series is None:
        crypto_close_dict, btc_series = load_crypto_universe_data()

    if crypto_close_dict and btc_series is not None:
        screen_res = screen_venture_candidates(crypto_close_dict, btc_series, cross_kraken_futures=True)
    else:
        screen_res = {"macro_gate_active": True, "btc_price_usd": 0.0, "candidates": []}

    msg = build_venture_telegram_alert(screen_res, signals, summary)

    if dry_run:
        return True, msg

    if not tok or not cid:
        return False, "Credenziali TELEGRAM_TOKEN o TELEGRAM_CHAT_ID non configurate."

    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": cid, "text": msg, "parse_mode": "Markdown"}).encode("utf-8")
    req = urllib.request.Request(url, data=payload)
    try:
        with urllib.request.urlopen(req, timeout=12):
            return True, msg
    except Exception as e_md:
        try:
            plain = msg.replace("*", "")
            payload_plain = urllib.parse.urlencode({"chat_id": cid, "text": plain}).encode("utf-8")
            req_plain = urllib.request.Request(url, data=payload_plain)
            with urllib.request.urlopen(req_plain, timeout=12):
                return True, plain
        except Exception as e:
            return False, f"Errore invio Telegram: {e}"


