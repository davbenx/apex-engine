import yfinance as yf
import pandas as pd
import numpy as np
import datetime
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

class ZainettoFiscale:
    def __init__(self, tax_rate=0.26):
        self.tax_rate = tax_rate
        self.minusvalenze = defaultdict(float) # {anno_scadenza: importo}
        self.tasse_pagate = 0.0

    def add_minusvalenza(self, amount, current_year):
        # Le minus scrostano dopo 4 anni
        self.minusvalenze[current_year + 4] += abs(amount)

    def apply_plusvalenza(self, profit, current_year):
        # Pulisci le minusvalenze scadute
        for year in list(self.minusvalenze.keys()):
            if year < current_year:
                del self.minusvalenze[year]
                
        # Compensa il profitto con le minusvalenze partendo dalle più vecchie
        taxable_profit = profit
        for year in sorted(self.minusvalenze.keys()):
            if taxable_profit <= 0: break
            available = self.minusvalenze[year]
            if available > 0:
                used = min(available, taxable_profit)
                self.minusvalenze[year] -= used
                taxable_profit -= used
                
        # Calcola le tasse sul profitto residuo
        tax = taxable_profit * self.tax_rate
        self.tasse_pagate += tax
        return tax

class ApexBacktester:
    def __init__(self, tickers, start_date="2015-01-01", end_date="2024-01-01", initial_capital=100000):
        self.tickers = tickers
        self.start = start_date
        self.end = end_date
        self.capital = initial_capital
        self.cash = initial_capital
        self.positions = {} # {ticker: {"shares": x, "entry_price": y}}
        self.history = []
        
        # Costi
        self.commission_pct = 0.001  # 0.1% a transazione
        self.slippage_pct = 0.001    # 0.1% slippage
        self.fisco = ZainettoFiscale()

    def fetch_data(self):
        print(f"Scaricamento dati per {len(self.tickers)} ticker...")
        df = yf.download(self.tickers, start=self.start, end=self.end, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            self.data = df['Close'].ffill().dropna()
        else:
            self.data = pd.DataFrame({self.tickers[0]: df['Close']}).ffill().dropna()
        print("Dati pronti.")

    def run(self, top_n=3, mom_period=90):
        print("Avvio simulazione...")
        self.fetch_data()
        
        # Calcolo indicatori vettoriali
        df_m = self.data.resample('M').last()
        momentum = df_m.pct_change(mom_period // 30).dropna()
        ma200 = self.data.rolling(200).mean().resample('M').last()
        
        # Simulazione Event-Driven mese per mese
        for i in range(1, len(df_m)):
            date = df_m.index[i]
            prev_date = df_m.index[i-1]
            year = date.year
            
            # 1. Trova i segnali di fine mese scorso
            if prev_date not in momentum.index or prev_date not in ma200.index: continue
            
            curr_prices = df_m.loc[date]
            prev_prices = df_m.loc[prev_date]
            mom_scores = momentum.loc[prev_date]
            ma_scores = ma200.loc[prev_date]
            
            # Filtro MA200 e classifica Momentum
            valid_tickers = []
            for t in self.tickers:
                if t in prev_prices and t in ma_scores and prev_prices[t] > ma_scores[t]:
                    valid_tickers.append(t)
            
            valid_mom = mom_scores[valid_tickers].dropna().sort_values(ascending=False)
            target_portfolio = valid_mom.head(top_n).index.tolist()
            
            # 2. Esecuzione Vendite (Chiude chi non è più nel target)
            for t in list(self.positions.keys()):
                if t not in target_portfolio:
                    sell_price = curr_prices[t] * (1 - self.slippage_pct)
                    shares = self.positions[t]['shares']
                    entry = self.positions[t]['entry_price']
                    
                    gross_value = shares * sell_price
                    commission = gross_value * self.commission_pct
                    net_value = gross_value - commission
                    
                    # Tasse
                    profit = net_value - (shares * entry)
                    if profit > 0:
                        tax = self.fisco.apply_plusvalenza(profit, year)
                        net_value -= tax
                    else:
                        self.fisco.add_minusvalenza(profit, year)
                        
                    self.cash += net_value
                    del self.positions[t]

            # 3. Esecuzione Acquisti e Ribilanciamento
            if len(target_portfolio) > 0:
                target_weight = self.cash / len(target_portfolio) if len(self.positions) == 0 else (self.cash + sum([self.positions[t]['shares'] * curr_prices[t] for t in self.positions])) / top_n
                
                for t in target_portfolio:
                    buy_price = curr_prices[t] * (1 + self.slippage_pct)
                    
                    if t not in self.positions:
                        # Nuovo acquisto
                        alloc = min(target_weight, self.cash)
                        if alloc > 0:
                            commission = alloc * self.commission_pct
                            shares = (alloc - commission) / buy_price
                            self.positions[t] = {'shares': shares, 'entry_price': buy_price}
                            self.cash -= alloc

            # 4. Registra storico
            port_value = self.cash + sum([self.positions[t]['shares'] * curr_prices[t] for t in self.positions])
            self.history.append({'Date': date, 'Value': port_value})

        return pd.DataFrame(self.history).set_index('Date')

    def report(self, eq_curve):
        cagr = (eq_curve['Value'].iloc[-1] / self.capital) ** (12 / len(eq_curve)) - 1
        peak = eq_curve['Value'].cummax()
        dd = (eq_curve['Value'] - peak) / peak
        max_dd = dd.min()
        
        print("\n=== APEX REPORT ISTITUZIONALE ===")
        print(f"Capitale Iniziale: ${self.capital:,.2f}")
        print(f"Capitale Finale Netto (Post Tasse 26% e Commissioni): ${eq_curve['Value'].iloc[-1]:,.2f}")
        print(f"CAGR Netto: {cagr*100:.2f}%")
        print(f"Max Drawdown: {max_dd*100:.2f}%")
        print(f"Tasse Totali Versate: ${self.fisco.tasse_pagate:,.2f}")

if __name__ == "__main__":
    # Test su un micro-universo (per evitare ban da Yahoo, proxy settoriale)
    test_tickers = ["AAPL", "MSFT", "NVDA", "JPM", "V", "JNJ", "UNH", "XOM", "PG", "MA", "HD", "CVX", "ABBV", "MRK", "META", "AMZN", "GOOGL", "SPY", "GLD", "TLT"]
    
    engine = ApexBacktester(tickers=test_tickers, start_date="2010-01-01")
    eq = engine.run(top_n=2, mom_period=90)
    engine.report(eq)
with open("tax_report.txt", "w") as out:
    cagr = (eq['Value'].iloc[-1] / engine.capital) ** (12 / len(eq)) - 1
    max_dd = ((eq['Value'] - eq['Value'].cummax()) / eq['Value'].cummax()).min()
    out.write(f"Capitale Finale: ${eq['Value'].iloc[-1]:.2f}\nCAGR Netto: {cagr*100:.2f}%\nMax Drawdown: {max_dd*100:.2f}%\nTasse: ${engine.fisco.tasse_pagate:.2f}\n")

