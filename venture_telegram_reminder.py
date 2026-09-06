"""
venture_telegram_reminder.py — Alert Automatici Telegram per Frontier Venture
================================================================================
Monitora quotidianamente lo stato del satellite Frontier Venture:
1. Stato Macro Gate Bitcoin (MA 40w / MA 20w).
2. Segnali di Uscita e Prese di Profitto (Free-Ride, Milestone, Trailing Stop, Stop Loss).
3. Nuovi Token in Breakout qualificati su Kraken Futures (senza wrapped e stablecoins).
4. Riepilogo cassa, slot liberi e profitti riciclati su Apex/Convex.

Uso:
  python venture_telegram_reminder.py [--dry-run]
"""

from __future__ import annotations
import os
import sys
import glob
import pandas as pd
from altcoin_venture_engine import (
    send_venture_telegram_alert,
    load_crypto_universe_data,
    VentureAltcoinEngine
)


def main(dry_run: bool = False) -> int:
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    dfs, btc = load_crypto_universe_data()

    ok, msg = send_venture_telegram_alert(
        token=token,
        chat_id=chat_id,
        crypto_close_dict=dfs,
        btc_series=btc,
        dry_run=dry_run
    )


    if dry_run:
        print("[DRY RUN] Messaggio generato con successo:\n")
        print(msg)
        return 0

    if ok:
        print("[+] Notifica Telegram Frontier Venture inviata con successo.")
        return 0
    else:
        print(f"[!] Invio notifica Telegram fallito: {msg}")
        return 1


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
