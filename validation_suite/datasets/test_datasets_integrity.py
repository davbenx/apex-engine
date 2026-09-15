"""
test_datasets_integrity.py — Suite di validazione quantitativa per i dataset completi.
======================================================================================
Verifica l'integrità, la completezza storica, l'assenza di survivorship bias e
la coerenza matematica di tutti i dataset dell'ecosistema Apex e Convex:
1. Serie macroeconomiche estese (Oro LBMA/COMEX 1986-2026, T-Bills 1960-2026, S&P 500, Bond).
2. Splicing continuo Crypto Venture (2010-2026).
3. Snapshot point-in-time reali S&P 500 (2012-2024, esenti da survivorship bias).
4. Mappa point-in-time dei titoli delistati (195 proxy sintetici verificati).
5. Snapshot point-in-time reali altcoin CoinMarketCap (132 coin, 2019-2026).
6. Archivio storico completo delle operazioni Apex V3 (1.183 trade, 1987-2026, solo ticker puri).
7. Coerenza metadati UCITS Convex Stack e cache prezzi live.
======================================================================================
"""

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
import pandas as pd
import pytest


# ==============================================================================
# 1. SERIE MACROECONOMICHE ESTESE (1960 - 2026)
# ==============================================================================

def test_macro_extended_gold_continuity(macro_data_dir: Path):
    """Verifica la continuità e l'estensione quarantennale della serie dell'Oro (LBMA/COMEX + GLD)."""
    gc_file = macro_data_dir / "GC_F_weekly.csv"
    gld_file = macro_data_dir / "GLD_weekly.csv"

    assert gc_file.exists(), f"File non trovato: {gc_file}"
    assert gld_file.exists(), f"File non trovato: {gld_file}"

    df_gc = pd.read_csv(gc_file, index_col=0, parse_dates=True)
    assert len(df_gc) >= 2000, f"Attese almeno 2000 barre settimanali Oro, trovate {len(df_gc)}"
    assert df_gc.index.min() <= pd.Timestamp("1987-01-01"), f"Serie GC non sufficientemente profonda: {df_gc.index.min()}"
    assert df_gc.index.max() >= pd.Timestamp("2026-09-01"), f"Serie GC non aggiornata a settembre 2026: {df_gc.index.max()}"
    assert df_gc.iloc[:, 0].isna().sum() == 0, "Rilevati valori NaN nella serie dell'Oro"

    df_gld = pd.read_csv(gld_file, index_col=0, parse_dates=True)
    assert len(df_gld) >= 1100, f"Attese almeno 1100 barre GLD, trovate {len(df_gld)}"
    assert df_gld.index.min() <= pd.Timestamp("2005-01-01"), "GLD deve iniziare entro il 2004-2005"


def test_macro_extended_tbills_continuity(macro_data_dir: Path):
    """Verifica la serie storica dei rendimenti dei Treasury Bill a 3 mesi (1960-2026)."""
    tbill_file = macro_data_dir / "US_3M_TBILL_weekly.csv"
    assert tbill_file.exists(), f"File non trovato: {tbill_file}"

    df_tbill = pd.read_csv(tbill_file, parse_dates=["Date"]).set_index("Date")
    assert len(df_tbill) >= 3000, f"Attese almeno 3000 barre settimanali T-Bills, trovate {len(df_tbill)}"
    assert df_tbill.index.min() <= pd.Timestamp("1965-01-01"), f"Inizio T-Bills non sufficientemente profondo: {df_tbill.index.min()}"
    assert df_tbill.index.max() >= pd.Timestamp("2026-09-01"), f"T-Bills non aggiornati a settembre 2026: {df_tbill.index.max()}"
    assert "rate_pct" in df_tbill.columns, "Colonna rate_pct mancante nel file T-Bills"
    assert df_tbill["rate_pct"].isna().sum() == 0, "Rilevati valori NaN nei tassi T-Bill"
    # I tassi T-Bills sono stati storicamente compresi tra -0.10% (picco panico COVID marzo 2020) e 20.0% (Volcker 1981)
    assert (df_tbill["rate_pct"] >= -0.10).all() and (df_tbill["rate_pct"] < 25.0).all(), "Tassi T-Bills fuori dal range macroeconomico"


def test_macro_extended_equities_and_bonds_continuity(macro_data_dir: Path):
    """Verifica le serie storiche dei benchmark azionari (VFINX/SPY) e obbligazionari (VUSTX/IEF)."""
    vfinx_file = macro_data_dir / "VFINX_weekly.csv"
    spy_file = macro_data_dir / "SPY_weekly.csv"
    vustx_file = macro_data_dir / "VUSTX_weekly.csv"
    ief_file = macro_data_dir / "IEF_weekly.csv"

    for f_path in (vfinx_file, spy_file, vustx_file, ief_file):
        assert f_path.exists(), f"File benchmark mancante: {f_path}"
        df = pd.read_csv(f_path, index_col=0, parse_dates=True)
        assert len(df) >= 1000, f"Campione insufficiente per {f_path.name}: {len(df)} righe"
        assert df.iloc[:, 0].isna().sum() == 0, f"Valori NaN rilevati in {f_path.name}"
        assert df.index.max() >= pd.Timestamp("2026-09-01"), f"{f_path.name} non aggiornato a settembre 2026"

    df_vfinx = pd.read_csv(vfinx_file, index_col=0, parse_dates=True)
    assert df_vfinx.index.min() <= pd.Timestamp("1987-01-01"), "VFINX deve coprire l'era dal 1986"

    df_vustx = pd.read_csv(vustx_file, index_col=0, parse_dates=True)
    assert df_vustx.index.min() <= pd.Timestamp("1987-01-01"), "VUSTX deve coprire l'era dal 1986"


def test_crypto_venture_weekly_spliced_continuity(macro_data_dir: Path):
    """Verifica la serie storica concatenata dei rendimenti settimanali Crypto Venture (2010-2026)."""
    spliced_file = macro_data_dir / "crypto_venture_weekly_spliced.csv"
    assert spliced_file.exists(), f"File non trovato: {spliced_file}"

    df_spliced = pd.read_csv(spliced_file, index_col=0, parse_dates=True)
    assert len(df_spliced) >= 800, f"Attese almeno 800 barre Crypto Venture, trovate {len(df_spliced)}"
    assert df_spliced.index.min() <= pd.Timestamp("2011-01-01"), "Crypto Venture deve iniziare dal 2010"
    assert df_spliced.index.max() >= pd.Timestamp("2026-09-01"), "Crypto Venture deve raggiungere settembre 2026"
    assert "gross" in df_spliced.columns and "net" in df_spliced.columns, "Colonne gross/net mancanti"
    assert df_spliced["gross"].isna().sum() == 0 and df_spliced["net"].isna().sum() == 0, "Valori NaN rilevati"
    # Rendimento settimanale compreso tra -100% e +500%
    assert (df_spliced["gross"] >= -1.0).all() and (df_spliced["net"] >= -1.0).all()
    # Rendimento composto a lungo termine ampiamente positivo
    cum_ret = (1.0 + df_spliced["gross"]).cumprod().iloc[-1]
    assert cum_ret > 100.0, f"Rendimento cumulativo Crypto Venture incoerente: {cum_ret}"


# ==============================================================================
# 2. DATASET POINT-IN-TIME (SURVIVORSHIP-BIAS-FREE)
# ==============================================================================

def test_point_in_time_sp500_survivorship_bias_freedom(sp500_pit_snapshots: Dict[str, List[str]]):
    """Verifica che gli snapshot dell'S&P 500 siano autentici point-in-time esenti da survivorship bias."""
    assert len(sp500_pit_snapshots) >= 12, f"Attesi almeno 12 snapshot storici S&P 500, trovati {len(sp500_pit_snapshots)}"

    for period, tickers in sp500_pit_snapshots.items():
        assert len(tickers) >= 490, f"Snapshot {period} incompleto: {len(tickers)} titoli (attesi >= 490)"
        assert len(tickers) == len(set(tickers)), f"Snapshot {period} contiene ticker duplicati"

    # Presenza di aziende storicamente capitalizzate ma successivamente acquisite o delistate
    all_historic_tickers = set(t for tickers in sp500_pit_snapshots.values() for t in tickers)
    known_delisted_giants = {"TWX", "MON", "CELG", "ALXN", "TIF"}
    for sym in known_delisted_giants:
        assert sym in all_historic_tickers, f"Titolo delistato storico atteso mancante negli snapshot S&P 500: {sym}"


def test_delisted_proxy_mapping_completeness(delisted_proxy_map: Dict[str, Any]):
    """Verifica la completezza della mappa dei 195 proxy per i titoli delistati dell'S&P 500."""
    assert len(delisted_proxy_map) == 195, f"Attesi esattamente 195 proxy per titoli delistati, trovati {len(delisted_proxy_map)}"

    valid_types = {"RENAME", "M&A", "MERGER", "DELISTED_OR_ACQUIRED", "SPINOFF", "BANKRUPTCY", "BANKRUPTCY_M&A", "TAKEN_PRIVATE"}
    for sym, meta in delisted_proxy_map.items():
        assert isinstance(meta, dict), f"Metadati non validi per {sym}"
        assert "type" in meta, f"Tipo mancante per {sym}"
        has_resolution = ("successor" in meta or "action" in meta or "cash_deal" in meta or "delisting_return" in meta)
        assert has_resolution, f"Nessuna regola di risoluzione definita per {sym}: {meta}"


def test_point_in_time_altcoins_survivorship_bias_freedom(cmc_altcoin_pit_snapshots: Dict[str, Any]):
    """Verifica che gli snapshot CoinMarketCap riflettano il mercato crypto reale punto per punto."""
    assert len(cmc_altcoin_pit_snapshots) >= 20, f"Attesi almeno 20 snapshot trimestrali altcoin, trovati {len(cmc_altcoin_pit_snapshots)}"

    all_coins = set()
    for snap_date, snap_obj in cmc_altcoin_pit_snapshots.items():
        coin_list = snap_obj.get("coins", []) if isinstance(snap_obj, dict) else snap_obj
        assert len(coin_list) >= 20, f"Snapshot {snap_date} con meno di 20 coin ({len(coin_list)})"
        for c in coin_list:
            sym = c.get("symbol") if isinstance(c, dict) else str(c)
            if sym:
                all_coins.add(sym)

    # Universo storico esente da survivorship bias: deve comprendere almeno 100 coin differenti
    assert len(all_coins) >= 100, f"Universo complessivo altcoin insufficiente: {len(all_coins)} coin (attese >= 100)"

    # Verifica presenza di coin di epoche passate (uscite dalla top ten o fallite successivamente)
    assert any(c in all_coins for c in ("EOS", "NEO", "MIOTA", "LUNC", "FTT", "DASH", "XEM")), (
        "Mancano coin storiche di cicli passati (segno di possibile survivorship bias)"
    )


# ==============================================================================
# 3. ARCHIVIO STORICO OPERAZIONI APEX V3 (1987 - 2026)
# ==============================================================================

def test_full_historical_trades_integrity_and_math(
    full_historical_trades: List[Dict[str, Any]],
    historical_trades_csv_path: Path
):
    """Verifica l'integrità matematica, la pulizia dei ticker e la struttura dell'archivio trade."""
    # Soglia abbassata da 1100 a 800: quella copriva anche i trade dell'era
    # "2024-Oggi (Tracking Live)" di un portafoglio live poi resettato a zero posizioni
    # (nessuna posizione realmente investita/collegata alla dashboard — richiesta esplicita
    # dell'utente). Le componenti deterministiche (macro + point-in-time + crypto pre-live)
    # restano a 868.
    assert len(full_historical_trades) >= 800, f"Attesi almeno 800 trade storici, trovati {len(full_historical_trades)}"
    assert historical_trades_csv_path.exists(), f"File CSV trade mancante: {historical_trades_csv_path}"

    df_csv = pd.read_csv(historical_trades_csv_path)
    assert len(df_csv) == len(full_historical_trades), "Disallineamento righe tra JSON e CSV"

    required_keys = {
        "trade_id", "ticker", "entry_date", "exit_date", "entry_price",
        "exit_price", "profit_pct", "weight", "reason", "is_crypto",
        "asset_class", "era"
    }

    eras = set()
    classes = set()
    emoji_pattern = re.compile(r"[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]")

    for t in full_historical_trades:
        assert required_keys.issubset(t.keys()), f"Campi mancanti nel trade {t.get('trade_id')}"
        tkr = str(t["ticker"])

        # Punteggiatura ticker pulita: ZERO suffissi -USD, ZERO "Bitcoin Core Ballast"
        assert not tkr.endswith("-USD"), f"Rilevato suffisso -USD nel ticker: {tkr}"
        assert "Bitcoin Core" not in tkr, f"Rilevata terminologia obsoleta: {tkr}"

        # Assoluta assenza di emoji nei campi testuali
        assert not emoji_pattern.findall(t["reason"]), f"Emoji rilevata nella reason del trade {t['trade_id']}"

        # Coerenza matematica del rendimento (tolleranza 0.60% per costi transattivi, dividendi e slippage simulati)
        en_p = float(t["entry_price"])
        ex_p = float(t["exit_price"])
        if en_p > 0 and ex_p > 0:
            gross_pnl = ((ex_p / en_p) - 1.0) * 100
            actual_pnl = float(t["profit_pct"])
            assert abs(actual_pnl - gross_pnl) <= 0.60, (
                f"Discrepanza matematica anomala trade {t['trade_id']} ({tkr}): lordo {gross_pnl:.2f}%, registrato {actual_pnl:.2f}%"
            )

        eras.add(t["era"])
        classes.add(t["asset_class"])

    # Le ere storiche deterministiche e le classi macro devono essere rappresentate.
    # L'era crypto ha un'etichetta DINAMICA (anno min/max reale dei trade, non piu' un
    # intervallo fisso "2018-2024") da quando e' stato corretto il bug per cui restava
    # etichettata cosi' a prescindere dalle date reali e dal taglio contro il tracking
    # live — verificare solo che un'era crypto esista, non l'anno esatto.
    # "2024-Oggi (Tracking Live)" non e' piu' garantita: il portafoglio live e' stato
    # resettato a zero trade chiusi (nessuna posizione realmente investita — richiesta
    # esplicita dell'utente), quindi quest'era compare solo con trade live reali chiusi.
    expected_eras_fixed = {
        "1987-2011 (Macro Allocazione)",
        "2012-2024 (Point-In-Time)",
    }
    assert expected_eras_fixed.issubset(eras), f"Ere mancanti nel registro storico: {expected_eras_fixed - eras}"
    assert any("Crypto Frontier Venture" in e for e in eras), f"Nessuna era crypto trovata in {eras}"
    assert "Cryptovalute" in classes, "Classe Cryptovalute assente dal registro storico"
    assert "Azioni (Low-Beta)" in classes, "Classe Azioni Low-Beta assente dal registro storico"


# ==============================================================================
# 4. CONVEX STACK, METADATI UCITS E FRESCHEZZA CACHE PREZZI
# ==============================================================================

def test_convex_instruments_and_live_prices_schema(
    convex_metadata: Dict[str, Any],
    live_prices_cache: Dict[str, Any]
):
    """Verifica i metadati ufficiali degli strumenti Convex e lo schema della cache prezzi."""
    expected_instruments = {"NTSG", "AVWS", "DBMFE", "PPFB", "WBTC"}
    assert set(convex_metadata.keys()) == expected_instruments, "Strumenti Convex disallineati"

    tot_weight = sum(meta["target_weight"] for meta in convex_metadata.values())
    assert abs(tot_weight - 1.0) < 1e-6, f"La somma dei target weight deve fare 1.0, ottenuta {tot_weight}"

    # Soglia di trim per asset volatili fiscalmente efficienti (+75% sopra il target del 7.5%)
    assert convex_metadata["PPFB"]["trim_threshold"] == 0.13125, "Soglia trim PPFB deve essere 13.125%"
    assert convex_metadata["WBTC"]["trim_threshold"] == 0.13125, "Soglia trim WBTC deve essere 13.125%"

    # Verifica cache prezzi se disponibile
    if live_prices_cache:
        assert "fetched_at" in live_prices_cache, "Campo fetched_at mancante nella cache prezzi"
        prices = live_prices_cache.get("prices", {})
        for sym in expected_instruments:
            if sym in prices:
                assert float(prices[sym]) > 0, f"Prezzo non positivo per {sym} in live_prices_cache"


def test_contiguous_history_loaders_reach_live_date():
    """Verifica che i loader storici unificati raggiungano esattamente la data di operatività reale odierna (2026-09-14)."""
    import portfolio_manager

    # 1. Storico contiguo Apex
    df_apex = portfolio_manager.load_apex_contiguous_history()
    assert not df_apex.empty, "La serie contigua Apex non deve essere vuota"
    assert "value" in df_apex.columns, "Colonna value (NAV) mancante in Apex"
    assert df_apex.index[-1].strftime("%Y-%m-%d") >= "2026-09-11", f"Apex storico termina prima di settembre 2026: {df_apex.index[-1]}"
    assert df_apex["value"].isna().sum() == 0, "Valori NaN rilevati nella curva NAV Apex"

    # 2. Storico contiguo Convex
    df_convex = portfolio_manager.load_convex_contiguous_history()
    assert not df_convex.empty, "La serie contigua Convex non deve essere vuota"
    assert "value" in df_convex.columns, "Colonna value (NAV) mancante in Convex"
    assert df_convex.index[-1].strftime("%Y-%m-%d") >= "2026-09-14", f"Convex storico non raccordato a oggi: {df_convex.index[-1]}"
    assert df_convex["value"].isna().sum() == 0, "Valori NaN rilevati nella curva NAV Convex"
