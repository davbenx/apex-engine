"""
convex_telegram_reminder.py — Promemoria mensile PAC per Convex Stack
======================================================================
A differenza di Apex Engine (automatico, conosce sempre il proprio stato
reale), Convex Stack non ha un motore che traccia le posizioni dal vivo:
l'utente inserisce le proprie quote a mano ogni volta che apre la dashboard
(convex_portfolio.json non è un conto tracciato in automatico — vedi nota
in fondo al file). Per questo NON esiste un alert di trim/ribilanciamento
automatico: costruirne uno oggi significherebbe fingere un'automazione che
non c'è, basata su dati che nessuno aggiorna.

L'unica notifica che si può inviare in modo onesto e affidabile è un
promemoria mensile, basato solo sul calendario — non richiede dati di
portafoglio reali, quindi non può mai "sbagliare" per mancanza di dati.

Uso:
  TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=... python convex_telegram_reminder.py

Pensato per un cron mensile (vedi .github/workflows/convex_reminder.yml).
Nessun credenziale è codificato qui: se le variabili d'ambiente mancano,
lo script si ferma senza inviare nulla (stesso comportamento di backend.py).
"""

from __future__ import annotations
import os
import sys
import urllib.request
import urllib.parse
import datetime


def build_message() -> str:
    oggi = datetime.date.today().strftime("%d/%m/%Y")
    return (
        f"*CONVEX STACK* · {oggi}\n\n"
        "È il momento del versamento PAC mensile.\n\n"
        "*TARGET DI ALLOCAZIONE (5 STRUMENTI UCITS):*\n"
        "• NTSG (Azionario Globale + Bond USA leva 1.5x): 45.0%\n"
        "• DBMFE (Managed Futures CTA Anti-Crisi): 25.0%\n"
        "• AVWS (Small Cap Value Globale): 15.0%\n"
        "• PPFB (Oro Fisico ETC - Compensa Minusvalenze): 7.5%\n"
        "• WBTC (Bitcoin ETP - Compensa Minusvalenze): 7.5%\n\n"
        "*REGOLE OPERATIVE:*\n"
        "1. Versa la liquidità sull'asset con maggior deficit (Water-Filling a costo fiscale zero).\n"
        "2. Esegui il trim parziale solo se WBTC o PPFB superano l'11.25% (+50% sopra target).\n"
        "3. Apri la dashboard per calcolare esattamente quote e residuo cassa."
    )


def send_telegram_reminder(token: str, chat_id: str, message: str, timeout: int = 15) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    ).encode("utf-8")
    req = urllib.request.Request(url, data=payload)
    try:
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception as e_md:
        print(f"[!] Errore invio Markdown ({e_md}), riprovo in modalità testo semplice...")
        plain = message.replace("*", "")
        payload_plain = urllib.parse.urlencode({"chat_id": chat_id, "text": plain}).encode("utf-8")
        req_plain = urllib.request.Request(url, data=payload_plain)
        try:
            urllib.request.urlopen(req_plain, timeout=timeout)
            return True
        except Exception as e:
            print(f"[!] Errore invio alert Telegram: {e}")
            return False


def main(dry_run: bool = False) -> int:
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    message = build_message()

    if dry_run:
        print("[DRY RUN] Nessun messaggio verrà inviato. Contenuto:\n")
        print(message)
        return 0

    if not token or not chat_id:
        print("[-] Credenziali Telegram non configurate (TELEGRAM_TOKEN/TELEGRAM_CHAT_ID). Skip invio.")
        return 0

    sent = send_telegram_reminder(token, chat_id, message)
    print("[+] Promemoria Convex inviato con successo." if sent else "[!] Invio fallito.")
    return 0 if sent else 1


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
