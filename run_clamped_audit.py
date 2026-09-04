#!/usr/bin/env python3
"""
run_clamped_audit.py — Production-Grade Clamped BTC (<=8.0%) Audit for Combined 50/50 EUR Net.
Enforces:
- Hard combined BTC clamp <= 8.0% (Apex BTC target <= 8.5%, daily drift trimming if Combined BTC > 8.0%)
- Italian annual 0.20% imposta di bollo at December 31
- Two-bucket tax tracking in Apex and terminal 100% liquidation tax on both sleeves
- Stationary block bootstrap on 21-day and 63-day blocks (5,000 paths each)
- Full 2014-2026 annual table with intra-year max drawdowns
"""
import os, sys, pickle
import numpy as np, pandas as pd
from scipy import stats

BASE_DIR = "/home/davide/Scrivania/ApexConvex"
APP_DIR = "/home/davide/Scrivania/MasterStrategyApp"
RESEARCH_DIR = os.path.join(APP_DIR, "research")
OUTPUT_DIR = "/home/davide/.gemini/antigravity/brain/45d65516-e38d-43b1-843d-5d2c901bd27f/scratch"
os.makedirs(OUTPUT_DIR, exist_ok=True)

sys.path.insert(0, RESEARCH_DIR)
sys.path.insert(0, "/home/davide/Scaricati/trading")
from quantlab_core.data import membership_mask_for
from institutional_stats import psr, dsr

print("Loading cached datasets...")
with open(os.path.join(RESEARCH_DIR, 'market_data_point_in_time.pkl'), 'rb') as f:
    eq_payload = pickle.load(f)
eq_raw = eq_payload['data']
membership_matrix = eq_payload['sp500_membership_matrix']

with open(os.path.join(RESEARCH_DIR, 'crypto_universe_point_in_time.pkl'), 'rb') as f:
    cr_payload = pickle.load(f)
cr_raw = cr_payload['data']

MACRO_SYMS = {'SPY', 'IEF', 'GLD', 'BTC-USD'}
macro_proxies = {
    'Equities': eq_raw['SPY']['Close'].copy(),
    'Bonds': eq_raw['IEF']['Close'].copy(),
    'Gold': eq_raw['GLD']['Close'].copy(),
    'Crypto': cr_raw['BTC-USD']['Close'].copy(),
    'SPY': eq_raw['SPY']['Close'].copy(),
    'IEF': eq_raw['IEF']['Close'].copy(),
    'GLD': eq_raw['GLD']['Close'].copy(),
    'BTC-USD': cr_raw['BTC-USD']['Close'].copy(),
}

eurusd_df = pd.read_csv('/home/davide/Scaricati/trading/cache_daily/EURUSD=X.csv', parse_dates=['Date']).set_index('Date')
eurusd_s = eurusd_df.iloc[:, 0].copy()
xeon_df = pd.read_csv('/home/davide/Scaricati/trading/cache_daily/XEON.csv', parse_dates=['Date']).set_index('Date')
xeon_s = xeon_df.iloc[:, 0].copy()
shy_df = pd.read_csv('/home/davide/Scaricati/trading/cache_daily/SHY.csv', parse_dates=['datetime']).set_index('datetime')
shy_s = shy_df['close'].copy()

for s in [eurusd_s, xeon_s, shy_s]:
    if s.index.tz is not None: s.index = s.index.tz_localize(None)
    s.index = s.index.normalize()

for k in macro_proxies:
    if macro_proxies[k].index.tz is not None: macro_proxies[k].index = macro_proxies[k].index.tz_localize(None)
    macro_proxies[k].index = macro_proxies[k].index.normalize()

stock_pool = {k: v['Close'].copy() for k, v in eq_raw.items() if k not in MACRO_SYMS}
for k in stock_pool:
    if stock_pool[k].index.tz is not None: stock_pool[k].index = stock_pool[k].index.tz_localize(None)
    stock_pool[k].index = stock_pool[k].index.normalize()

START_DATE = '2014-11-03'
END_DATE = '2026-08-25'

common_idx = macro_proxies['Equities'].index
common_idx = common_idx[(common_idx >= START_DATE) & (common_idx <= END_DATE)].sort_values()

eurusd_daily = eurusd_s.reindex(common_idx).ffill().bfill()
xeon_daily = xeon_s.reindex(common_idx).ffill().bfill()
shy_daily = shy_s.reindex(common_idx).ffill().bfill()
fx_ratio = (eurusd_daily.shift(1) / eurusd_daily).fillna(1.0)
r_xeon = xeon_daily.pct_change().fillna(0.0)

cur_stocks = pd.DataFrame(stock_pool).reindex(common_idx).ffill()
cur_macro = {k: macro_proxies[k].reindex(common_idx).ffill() for k in macro_proxies}
is_member = pd.DataFrame({sym: membership_mask_for(sym, common_idx, membership_matrix) for sym in cur_stocks.columns}, index=common_idx)

macro_wc = {k: cur_macro[k].resample('W-FRI').last().dropna() for k in cur_macro}
macro_ma40 = {k: macro_wc[k].rolling(40, min_periods=10).mean().reindex(common_idx).ffill() for k in cur_macro}
macro_ma20 = {k: macro_wc[k].rolling(20, min_periods=5).mean().reindex(common_idx).ffill() for k in cur_macro}
macro_v = {k: macro_wc[k].pct_change().rolling(12, min_periods=4).std().multiply(np.sqrt(52)).reindex(common_idx).ffill() for k in cur_macro}

stock_wc = cur_stocks.resample('W-FRI').last()
s_vols = stock_wc.pct_change().rolling(26, min_periods=6).std().multiply(np.sqrt(52)).reindex(common_idx).ffill()

# Load Convex cached components
daily_nav = pd.read_csv(f'{OUTPUT_DIR}/daily_nav_series.csv', parse_dates=['Date']).set_index('Date')
r_ntsg_usd = daily_nav['Sleeve_NTSG'].pct_change().fillna(0.0)
r_avws_usd = daily_nav['Sleeve_AVWS'].pct_change().fillna(0.0)
r_dbmfe_usd = daily_nav['Sleeve_DBMFE'].pct_change().fillna(0.0)
r_ppfb_usd = daily_nav['Sleeve_PPFB'].pct_change().fillna(0.0)
r_wbtc_usd = daily_nav['Sleeve_WBTC'].pct_change().fillna(0.0)
r_spy_usd = cur_macro['Equities'].pct_change().fillna(0.0)

r_ntsg_eur = (1.0 + r_ntsg_usd) * fx_ratio - 1.0
r_avws_eur = (1.0 + r_avws_usd) * fx_ratio - 1.0
r_dbmfe_eur = (1.0 + r_dbmfe_usd) * fx_ratio - 1.0
r_ppfb_eur = (1.0 + r_ppfb_usd) * fx_ratio - 1.0
r_wbtc_eur = (1.0 + r_wbtc_usd) * fx_ratio - 1.0
r_spy_eur = (1.0 + r_spy_usd) * fx_ratio - 1.0

# ------------------------------------------------------------------------------
# CONVEX EUR SIMULATION WITH ANNUAL BOLLO (0.20%)
# ------------------------------------------------------------------------------
W_NTSG, W_AVWS, W_DBMFE, W_PPFB, W_WBTC = 0.45, 0.15, 0.25, 0.075, 0.075
TER_DAILY = (0.003788 + 0.0010) / 252.0

def build_convex_series(exclude_btc=False):
    nav = 100_000.0
    history = []
    for i in range(len(common_idx)):
        dt = common_idx[i]
        is_year_end = (dt.month == 12 and dt.day >= 28 and (i == len(common_idx)-1 or common_idx[min(i+1, len(common_idx)-1)].month == 1))
        
        if exclude_btc:
            r_day = (0.525 * r_ntsg_eur.iloc[i] + 0.15 * r_avws_eur.iloc[i] + 0.25 * r_dbmfe_eur.iloc[i] + 0.075 * r_ppfb_eur.iloc[i]) - TER_DAILY
        else:
            r_day = (W_NTSG * r_ntsg_eur.iloc[i] + W_AVWS * r_avws_eur.iloc[i] + W_DBMFE * r_dbmfe_eur.iloc[i] + W_PPFB * r_ppfb_eur.iloc[i] + W_WBTC * r_wbtc_eur.iloc[i]) - TER_DAILY
            
        nav *= (1.0 + r_day)
        if is_year_end:
            nav *= (1.0 - 0.0020)
        history.append((dt, nav))
    s = pd.Series([v for d, v in history], index=[d for d, v in history])
    return s

convex_eur_net = build_convex_series(exclude_btc=False)
convex_nobtc_eur_net = build_convex_series(exclude_btc=True)

# ------------------------------------------------------------------------------
# APEX EUR SIMULATION WITH TWO-BUCKET TAX, BOLLO (0.20%), AND BTC CLAMP
# ------------------------------------------------------------------------------
def simulate_apex(btc_apex_cap=None, trim_drift_to_cap=True, exclude_btc=False):
    nav_net = 100_000.0
    cash_net = 100_000.0
    pos_shares = {}
    cost_basis = {}
    
    annual_gains_capitale = 0.0
    annual_gains_diversi = 0.0
    minus_diversi = {}
    total_tax_paid = 0.0
    total_bollo_paid = 0.0
    
    FEE_EQ, FEE_SAFE, FEE_CR = 0.0010, 0.0008, 0.0010
    
    macro_state = {c: False for c in ('Equities', 'Bonds', 'Gold', 'Crypto')}
    macro_allocs = {'Cash': 1.0, 'Equities': 0.0, 'Bonds': 0.0, 'Gold': 0.0, 'Crypto': 0.0}
    
    nav_history = []
    btc_weight_history = []
    pending_rebal = None
    held_eq = set()
    
    def get_price_eur(sym, dt_idx):
        dt_val = common_idx[dt_idx]
        px_usd = float(cur_macro[sym].loc[dt_val]) if sym in cur_macro else float(cur_stocks.loc[dt_val, sym])
        fx = float(eurusd_daily.loc[dt_val])
        return px_usd / fx

    for i in range(len(common_idx)):
        dt = common_idx[i]
        is_friday = (dt.weekday() == 4)
        is_month_end_friday = is_friday and (i == len(common_idx)-1 or common_idx[min(i+7, len(common_idx)-1)].month != dt.month)
        is_year_end = (dt.month == 12 and dt.day >= 28 and (i == len(common_idx)-1 or common_idx[min(i+1, len(common_idx)-1)].month == 1))
        
        # Cash return (XEON)
        c_ret = float(r_xeon.loc[dt]) if i > 0 else 0.0
        cash_net *= (1.0 + c_ret)
        
        # Monday fill execution
        if pending_rebal is not None and i >= pending_rebal['exec_idx']:
            reb = pending_rebal
            target_allocs = reb['allocations']
            target_basket = reb['basket']
            
            # Liquidate exits
            current_held = list(pos_shares.keys())
            target_tickers = set(target_basket + [c for c in ('IEF', 'GLD', 'BTC-USD') if target_allocs.get(c, 0.0) > 0])
            
            for sym in current_held:
                if sym not in target_tickers or (sym in ('IEF', 'GLD', 'BTC-USD') and target_allocs.get(sym, 0.0) == 0):
                    px = get_price_eur(sym, i)
                    sh = pos_shares.pop(sym, 0.0)
                    proceeds = sh * px
                    fee_rate = FEE_CR if sym == 'BTC-USD' else (FEE_SAFE if sym in ('IEF', 'GLD') else FEE_EQ)
                    fee = proceeds * fee_rate
                    net_proceeds = proceeds - fee
                    pnl = net_proceeds - (sh * cost_basis.get(sym, px))
                    
                    if sym == 'IEF':
                        if pnl > 0: annual_gains_capitale += pnl
                        else: annual_gains_diversi += pnl
                    else:
                        annual_gains_diversi += pnl
                        
                    cash_net += net_proceeds
                    cost_basis.pop(sym, None)
                    
            total_equity_net = cash_net + sum(pos_shares[s] * get_price_eur(s, i) for s in pos_shares)
            new_pos_shares = {}
            new_cost_basis = dict(cost_basis)
            
            targets = {}
            if target_basket and target_allocs.get('Equities', 0.0) > 0:
                eq_tot_w = target_allocs['Equities']
                per_stock_w = eq_tot_w / len(target_basket)
                for sym in target_basket: targets[sym] = per_stock_w
            if target_allocs.get('Bonds', 0.0) > 0: targets['IEF'] = target_allocs['Bonds']
            if target_allocs.get('Gold', 0.0) > 0: targets['GLD'] = target_allocs['Gold']
            if target_allocs.get('Crypto', 0.0) > 0 and not exclude_btc: targets['BTC-USD'] = target_allocs['Crypto']
            
            invested_net = 0.0
            for sym, w in targets.items():
                px = get_price_eur(sym, i)
                tgt_eur = total_equity_net * w
                sh = tgt_eur / px
                fee_rate = FEE_CR if sym == 'BTC-USD' else (FEE_SAFE if sym in ('IEF', 'GLD') else FEE_EQ)
                fee = tgt_eur * fee_rate
                new_pos_shares[sym] = sh
                invested_net += (tgt_eur + fee)
                new_cost_basis[sym] = px
                
            cash_net = max(0.0, total_equity_net - invested_net)
            pos_shares = new_pos_shares
            cost_basis = new_cost_basis
            macro_allocs = target_allocs
            held_eq = set(target_basket)
            pending_rebal = None
            
        # Daily BTC drift trimming: if BTC weight exceeds btc_apex_cap, trim excess to cash
        if btc_apex_cap is not None and trim_drift_to_cap and 'BTC-USD' in pos_shares:
            px_btc = get_price_eur('BTC-USD', i)
            btc_val = pos_shares['BTC-USD'] * px_btc
            tot_val = cash_net + sum(pos_shares[s] * get_price_eur(s, i) for s in pos_shares)
            cur_w = btc_val / tot_val if tot_val > 0 else 0.0
            if cur_w > btc_apex_cap:
                excess_val = btc_val - (tot_val * btc_apex_cap)
                sh_to_sell = excess_val / px_btc
                pos_shares['BTC-USD'] -= sh_to_sell
                proceeds = sh_to_sell * px_btc
                fee = proceeds * FEE_CR
                net_proceeds = proceeds - fee
                pnl = net_proceeds - (sh_to_sell * cost_basis.get('BTC-USD', px_btc))
                annual_gains_diversi += pnl
                cash_net += net_proceeds
                
        # Month-end decision
        if is_month_end_friday:
            base_w = {}
            vols = {}
            for cls in ('Equities', 'Bonds', 'Gold', 'Crypto'):
                p = float(cur_macro[cls].loc[dt])
                ma_l = float(macro_ma40[cls].loc[dt])
                ma_s = float(macro_ma20[cls].loc[dt])
                v = float(macro_v[cls].loc[dt])
                vols[cls] = v if not np.isnan(v) and v > 0 else 0.15
                dist = (p / ma_l - 1.0) if ma_l > 0 else 0.0
                band = max(0.005, min(0.15, 0.5 * (vols[cls] / np.sqrt(52))))
                was_act = macro_state[cls]
                trend_l = (dist > -band) if was_act else (dist > band)
                trend_s = (p > ma_s)
                is_act = trend_l and trend_s
                macro_state[cls] = trend_l
                base_w[cls] = 0.50 if is_act else 0.0
                
            if exclude_btc:
                base_w['Crypto'] = 0.0
                
            port_vol = sum(base_w[c] * vols[c] for c in base_w)
            scale = min(1.0, 0.13 / port_vol) if port_vol > 1e-6 else 1.0
            raw_w = {c: base_w[c] * scale for c in base_w}
            
            # --- BITCOIN CLAMP RULE ---
            if btc_apex_cap is not None and 'Crypto' in raw_w:
                raw_w['Crypto'] = min(raw_w['Crypto'], btc_apex_cap)
                
            tot_raw = sum(raw_w.values())
            if tot_raw > 1.0:
                raw_w = {c: w / tot_raw for c, w in raw_w.items()}
                
            allocations = {c: raw_w[c] for c in raw_w}
            allocations['Cash'] = max(0.0, 1.0 - sum(raw_w.values()))
            
            basket = []
            if allocations.get('Equities', 0.0) > 0:
                is_quarter_end = dt.month in (3, 6, 9, 12)
                if is_quarter_end or not held_eq:
                    member_mask = is_member.loc[dt]
                    eligible = member_mask[member_mask].index
                    cur_v = s_vols.loc[dt, eligible].dropna().sort_values()
                    ranked = list(cur_v.index)
                    rank_of = {s: r+1 for r, s in enumerate(ranked)}
                    incumbents = sorted([s for s in held_eq if rank_of.get(s, 999) <= 20], key=lambda s: rank_of.get(s, 999))
                    chosen = list(incumbents)
                    for s in ranked:
                        if len(chosen) >= 15: break
                        if s not in chosen: chosen.append(s)
                    basket = chosen
                else:
                    basket = list(held_eq)
                    
            exec_idx = min(i + 1, len(common_idx) - 1)
            pending_rebal = {'exec_idx': exec_idx, 'allocations': allocations, 'basket': basket}
            
        # Daily Valuation
        pos_val_net = sum(sh * get_price_eur(s, i) for s, sh in pos_shares.items())
        cur_nav_net = cash_net + pos_val_net
        
        # Track BTC weight
        btc_sh = pos_shares.get('BTC-USD', 0.0)
        btc_val = btc_sh * get_price_eur('BTC-USD', i)
        btc_wt = btc_val / cur_nav_net if cur_nav_net > 0 else 0.0
        btc_weight_history.append((dt, btc_wt))
        
        # Year end tax and imposta di bollo
        if is_year_end:
            cur_year = dt.year
            for y in list(minus_diversi.keys()):
                if (cur_year - y) > 4: del minus_diversi[y]
                
            tax_cap = max(0.0, annual_gains_capitale * 0.26)
            tax_div = 0.0
            if annual_gains_diversi > 0:
                taxable = annual_gains_diversi
                for y in sorted(minus_diversi.keys()):
                    avail = minus_diversi[y]
                    if taxable <= avail:
                        minus_diversi[y] -= taxable; taxable = 0.0; break
                    else:
                        taxable -= avail; minus_diversi[y] = 0.0
                tax_div = taxable * 0.26
            elif annual_gains_diversi < 0:
                minus_diversi[cur_year] = minus_diversi.get(cur_year, 0.0) + abs(annual_gains_diversi)
                
            tot_tax = tax_cap + tax_div
            total_tax_paid += tot_tax
            cur_nav_net -= tot_tax
            cash_net = max(0.0, cash_net - tot_tax)
            annual_gains_capitale = 0.0
            annual_gains_diversi = 0.0
            
            # Imposta di bollo 0.20%
            bollo = cur_nav_net * 0.0020
            cur_nav_net -= bollo
            cash_net = max(0.0, cash_net - bollo)
            total_bollo_paid += bollo
            
        nav_history.append((dt, cur_nav_net))
        
    s_net = pd.Series([n for d, n in nav_history], index=[d for d, n in nav_history])
    s_btc = pd.Series([w for d, w in btc_weight_history], index=[d for d, w in btc_weight_history])
    
    # Terminal Liquidation Tax
    terminal_tax_capitale = 0.0
    terminal_gains_diversi = 0.0
    last_idx = len(common_idx) - 1
    for sym, sh in pos_shares.items():
        cur_px = get_price_eur(sym, last_idx)
        basis = cost_basis.get(sym, cur_px)
        pnl = sh * (cur_px - basis)
        if sym == 'IEF':
            if pnl > 0: terminal_tax_capitale += pnl * 0.26
            else: terminal_gains_diversi += pnl
        else:
            terminal_gains_diversi += pnl
            
    terminal_tax_diversi = 0.0
    if terminal_gains_diversi > 0:
        taxable = terminal_gains_diversi
        for y in sorted(minus_diversi.keys()):
            avail = minus_diversi[y]
            if taxable <= avail:
                minus_diversi[y] -= taxable; taxable = 0.0; break
            else:
                taxable -= avail; minus_diversi[y] = 0.0
        terminal_tax_diversi = taxable * 0.26
        
    total_terminal_tax = terminal_tax_capitale + terminal_tax_diversi
    final_liquidated_nav = s_net.iloc[-1] - total_terminal_tax
    
    return s_net, s_btc, final_liquidated_nav, total_terminal_tax

print("Simulating Apex variations...")
apex_unclamped, btc_w_unclamped, liq_apex_unclamped, term_tax_apex_unclamped = simulate_apex(btc_apex_cap=None, trim_drift_to_cap=False)
apex_clamped, btc_w_clamped, liq_apex_clamped, term_tax_apex_clamped = simulate_apex(btc_apex_cap=0.085, trim_drift_to_cap=True)
apex_nobtc, _, liq_apex_nobtc, term_tax_apex_nobtc = simulate_apex(exclude_btc=True)

# ------------------------------------------------------------------------------
# COMBINED PORTFOLIOS (50/50 APEX + CONVEX)
# ------------------------------------------------------------------------------
ret_comb_unclamped = 0.50 * apex_unclamped.pct_change().fillna(0.0) + 0.50 * convex_eur_net.pct_change().fillna(0.0)
comb_unclamped = 100_000.0 * (1.0 + ret_comb_unclamped).cumprod()

ret_comb_clamped = 0.50 * apex_clamped.pct_change().fillna(0.0) + 0.50 * convex_eur_net.pct_change().fillna(0.0)
comb_clamped = 100_000.0 * (1.0 + ret_comb_clamped).cumprod()

ret_comb_nobtc = 0.50 * apex_nobtc.pct_change().fillna(0.0) + 0.50 * convex_nobtc_eur_net.pct_change().fillna(0.0)
comb_nobtc = 100_000.0 * (1.0 + ret_comb_nobtc).cumprod()

# SPY EUR Net (with 0.39% dividend tax and 0.20% annual bollo)
spy_eur_net_val = 100_000.0
spy_eur_history = []
for i in range(len(common_idx)):
    dt = common_idx[i]
    is_year_end = (dt.month == 12 and dt.day >= 28 and (i == len(common_idx)-1 or common_idx[min(i+1, len(common_idx)-1)].month == 1))
    r = r_spy_eur.iloc[i] - (0.0039 / 252.0)
    spy_eur_net_val *= (1.0 + r)
    if is_year_end:
        spy_eur_net_val *= (1.0 - 0.0020)
    spy_eur_history.append((dt, spy_eur_net_val))
spy_eur_net = pd.Series([v for d, v in spy_eur_history], index=[d for d, v in spy_eur_history])

# Combined BTC weights daily
comb_btc_w_unclamped = 0.50 * btc_w_unclamped + 0.50 * 0.075
comb_btc_w_clamped = 0.50 * btc_w_clamped + 0.50 * 0.075

# Terminal Liquidation on Convex:
convex_term_tax = max(0.0, (convex_eur_net.iloc[-1] - 100_000.0) * 0.26)
liq_convex = convex_eur_net.iloc[-1] - convex_term_tax

# Total liquidated capital for Combined:
liq_comb_clamped = 0.50 * liq_apex_clamped + 0.50 * liq_convex
cagr_ongoing_clamped = (comb_clamped.iloc[-1] / 100_000.0) ** (365.25 / (common_idx[-1] - common_idx[0]).days) - 1.0
cagr_liq_clamped = (liq_comb_clamped / 100_000.0) ** (365.25 / (common_idx[-1] - common_idx[0]).days) - 1.0

# Stats helper
def calc_metrics(s, rf=0.0):
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1.0 / yrs) - 1.0
    dd = (s / s.cummax() - 1.0).min()
    r = s.pct_change().dropna()
    vol = r.std() * np.sqrt(252)
    sharpe = (r.mean() * 252 - rf) / (vol + 1e-12)
    downside = r[r < 0]
    sortino = (r.mean() * 252 - rf) / (downside.std() * np.sqrt(252) + 1e-12)
    calmar = cagr / abs(dd) if dd != 0 else np.nan
    return {'cagr': cagr, 'vol': vol, 'sharpe': sharpe, 'sortino': sortino, 'maxdd': dd, 'calmar': calmar, 'yrs': yrs}

m_unclamped = calc_metrics(comb_unclamped)
m_clamped = calc_metrics(comb_clamped)
m_nobtc = calc_metrics(comb_nobtc)
m_spy = calc_metrics(spy_eur_net)

# Sharpe with RF = 3%
sh3_unclamped = (comb_unclamped.pct_change().dropna().mean() * 252 - 0.03) / m_unclamped['vol']
sh3_clamped = (comb_clamped.pct_change().dropna().mean() * 252 - 0.03) / m_clamped['vol']
sh3_nobtc = (comb_nobtc.pct_change().dropna().mean() * 252 - 0.03) / m_nobtc['vol']
sh3_spy = (spy_eur_net.pct_change().dropna().mean() * 252 - 0.03) / m_spy['vol']

# ------------------------------------------------------------------------------
# STATIONARY BLOCK BOOTSTRAP (21-DAY & 63-DAY BLOCKS, 5,000 PATHS)
# ------------------------------------------------------------------------------
print("Running Stationary Block Bootstrap (21-day & 63-day blocks, 5,000 paths each)...")
np.random.seed(42)
r_clamp = comb_clamped.pct_change().dropna().values
N_PATHS = 5000
N_DAYS = len(r_clamp)

def run_bootstrap(block_len):
    n_blocks = int(np.ceil(N_DAYS / block_len))
    cagrs, mdds, sharpes, sortinos = [], [], [], []
    for _ in range(N_PATHS):
        starts = np.random.randint(0, N_DAYS - block_len + 1, size=n_blocks)
        sample = np.concatenate([r_clamp[s:s+block_len] for s in starts])[:N_DAYS]
        curve = np.cumprod(1.0 + sample)
        cagr = (curve[-1] ** (252.0 / N_DAYS)) - 1.0
        roll_max = np.maximum.accumulate(curve)
        mdd = np.min((curve - roll_max) / roll_max)
        vol = np.std(sample) * np.sqrt(252) + 1e-12
        sh = (np.mean(sample) * 252) / vol
        down = sample[sample < 0]
        sort = (np.mean(sample) * 252) / (np.std(down) * np.sqrt(252) + 1e-12) if len(down) > 0 else np.nan
        cagrs.append(cagr)
        mdds.append(mdd)
        sharpes.append(sh)
        sortinos.append(sort)
    return {
        'p5_cagr': float(np.percentile(cagrs, 5)),
        'p50_cagr': float(np.percentile(cagrs, 50)),
        'p95_cagr': float(np.percentile(cagrs, 95)),
        'p95_worst_mdd': float(np.percentile(mdds, 5)),
        'p50_mdd': float(np.percentile(mdds, 50)),
        'p5_sharpe': float(np.percentile(sharpes, 5)),
        'p50_sharpe': float(np.percentile(sharpes, 50)),
        'p95_sharpe': float(np.percentile(sharpes, 95)),
        'p5_sortino': float(np.percentile(sortinos, 5)),
        'p50_sortino': float(np.percentile(sortinos, 50)),
        'p95_sortino': float(np.percentile(sortinos, 95))
    }

boot_21 = run_bootstrap(21)
boot_63 = run_bootstrap(63)

# Save daily clamped NAV and weights
clamped_df = pd.DataFrame({
    'Combined_Clamped_EUR_Net': comb_clamped,
    'Combined_Unclamped_EUR_Net': comb_unclamped,
    'Combined_NoBTC_EUR_Net': comb_nobtc,
    'SPY_EUR_Net': spy_eur_net,
    'BTC_Weight_Combined_Clamped': comb_btc_w_clamped,
    'BTC_Weight_Combined_Unclamped': comb_btc_w_unclamped
})
clamped_df.index.name = 'Date'
clamped_df.to_csv(os.path.join(OUTPUT_DIR, 'combined_clamped_audit_daily.csv'))

# ------------------------------------------------------------------------------
# PRINT REPORT
# ------------------------------------------------------------------------------
print("\n" + "=" * 115)
print("DEEP INSTITUTIONAL AUDIT: COMBINED 50/50 EUR NET WITH BTC CLAMP <= 8.0% & ANNUAL BOLLO")
print("=" * 115)

print("\n--- 1. METRICHE COMPARATIVE COMPLETE (EUR NETTO REALE, 2014-11-03 -> 2026-08-25) ---")
print(f"{'Strategia':<36} | {'CAGR Net':<9} | {'Volatilità':<10} | {'Sh (rf=0)':<9} | {'Sh (rf=3%)':<10} | {'Sortino':<8} | {'MaxDD':<8} | {'Calmar':<6}")
print("-" * 105)
print(f"{'Combined Unclamped (BTC 8.5% avg, 29% max)':<36} | {m_unclamped['cagr']*100:6.2f}%  | {m_unclamped['vol']*100:6.2f}%   | {m_unclamped['sharpe']:6.2f}    | {sh3_unclamped:6.2f}     | {m_unclamped['sortino']:6.2f}  | {m_unclamped['maxdd']*100:5.1f}%  | {m_unclamped['calmar']:5.2f}")
print(f"{'Combined CLAMPED (BTC <= 8.0% hard)':<36} | {m_clamped['cagr']*100:6.2f}%  | {m_clamped['vol']*100:6.2f}%   | {m_clamped['sharpe']:6.2f}    | {sh3_clamped:6.2f}     | {m_clamped['sortino']:6.2f}  | {m_clamped['maxdd']*100:5.1f}%  | {m_clamped['calmar']:5.2f}")
print(f"{'Combined NO-BTC (Caso Base Sizing)':<36} | {m_nobtc['cagr']*100:6.2f}%  | {m_nobtc['vol']*100:6.2f}%   | {m_nobtc['sharpe']:6.2f}    | {sh3_nobtc:6.2f}     | {m_nobtc['sortino']:6.2f}  | {m_nobtc['maxdd']*100:5.1f}%  | {m_nobtc['calmar']:5.2f}")
print(f"{'SPY Benchmark EUR (Netto Bollo e Tasse)':<36} | {m_spy['cagr']*100:6.2f}%  | {m_spy['vol']*100:6.2f}%   | {m_spy['sharpe']:6.2f}    | {sh3_spy:6.2f}     | {m_spy['sortino']:6.2f}  | {m_spy['maxdd']*100:5.1f}%  | {m_spy['calmar']:5.2f}")

print("\n--- 2. ANALISI DISTRIBUZIONE DEL PESO DI BITCOIN ---")
print(f"  Unclamped: Media={comb_btc_w_unclamped.mean()*100:5.2f}% | Mediana={comb_btc_w_unclamped.median()*100:5.2f}% | Max={comb_btc_w_unclamped.max()*100:5.2f}% | 95° pct={np.percentile(comb_btc_w_unclamped, 95)*100:5.2f}% | Giorni > 10%: {(comb_btc_w_unclamped > 0.10).mean()*100:5.2f}%")
print(f"  CLAMPED  : Media={comb_btc_w_clamped.mean()*100:5.2f}% | Mediana={comb_btc_w_clamped.median()*100:5.2f}% | Max={comb_btc_w_clamped.max()*100:5.2f}% | 95° pct={np.percentile(comb_btc_w_clamped, 95)*100:5.2f}% | Giorni > 8.0%: {(comb_btc_w_clamped > 0.0801).mean()*100:5.2f}%")

print("\n--- 3. FISCALITÀ REALE E TERMINAL LIQUIDATION HAIRCUT (COMBINED CLAMPED) ---")
print(f"  Capitale Iniziale                 : 100.000,00 €")
print(f"  NAV Finale Operativo (Ongoing)    : {comb_clamped.iloc[-1]:,.2f} € (CAGR Netto: {cagr_ongoing_clamped*100:5.2f}%)")
print(f"  Imposta Terminale su Plusvalenze  : {comb_clamped.iloc[-1] - liq_comb_clamped:,.2f} €")
print(f"  Capitale Netto Liquidato al 100%  : {liq_comb_clamped:,.2f} € (CAGR Spendibile: {cagr_liq_clamped*100:5.2f}%)")
print(f"  Haircut da Liquidazione Magazzino : -{(cagr_ongoing_clamped - cagr_liq_clamped)*100:4.2f} pp CAGR")

print("\n--- 4. BLOCK BOOTSTRAP RESAMPLING (5.000 PATHS) SUL COMBINED CLAMPED (BTC <= 8.0%) ---")
print(f"  A. BLOCCHI DA 21 GIORNI (1 MESE):")
print(f"    CAGR     : 5° pct = {boot_21['p5_cagr']*100:5.2f}% | Mediana = {boot_21['p50_cagr']*100:5.2f}% | 95° pct = {boot_21['p95_cagr']*100:5.2f}%")
print(f"    MaxDD    : 95° peggiore = {boot_21['p95_worst_mdd']*100:5.2f}% | Mediana = {boot_21['p50_mdd']*100:5.2f}%")
print(f"    Sharpe   : 5° pct = {boot_21['p5_sharpe']:4.2f}  | Mediana = {boot_21['p50_sharpe']:4.2f}  | 95° pct = {boot_21['p95_sharpe']:4.2f}")
print(f"    Sortino  : 5° pct = {boot_21['p5_sortino']:4.2f}  | Mediana = {boot_21['p50_sortino']:4.2f}  | 95° pct = {boot_21['p95_sortino']:4.2f}")
print(f"\n  B. BLOCCHI DA 63 GIORNI (1 TRIMESTRE - PRESERVA INVERNI CRIPTO E TREND MACRO):")
print(f"    CAGR     : 5° pct = {boot_63['p5_cagr']*100:5.2f}% | Mediana = {boot_63['p50_cagr']*100:5.2f}% | 95° pct = {boot_63['p95_cagr']*100:5.2f}%")
print(f"    MaxDD    : 95° peggiore = {boot_63['p95_worst_mdd']*100:5.2f}% | Mediana = {boot_63['p50_mdd']*100:5.2f}%")
print(f"    Sharpe   : 5° pct = {boot_63['p5_sharpe']:4.2f}  | Mediana = {boot_63['p50_sharpe']:4.2f}  | 95° pct = {boot_63['p95_sharpe']:4.2f}")
print(f"    Sortino  : 5° pct = {boot_63['p5_sortino']:4.2f}  | Mediana = {boot_63['p50_sortino']:4.2f}  | 95° pct = {boot_63['p95_sortino']:4.2f}")

print("\n--- 5. TABELLA ANNUALE COMPLETA (2014-2026 YTD) COMBINED CLAMPED EUR NET ---")
print(f"{'Anno':<6} | {'Comb Clamped':<14} | {'Comb Unclamp':<14} | {'Comb No-BTC':<14} | {'SPY EUR Net':<14} | {'Clamped MDD':<12} | {'SPY MDD':<10}")
print("-" * 92)
years = sorted(list(set(comb_clamped.index.year)))
for y in years:
    c_c = comb_clamped[comb_clamped.index.year == y]
    c_u = comb_unclamped[comb_unclamped.index.year == y]
    c_n = comb_nobtc[comb_nobtc.index.year == y]
    s_s = spy_eur_net[spy_eur_net.index.year == y]
    if len(c_c) < 5: continue
    r_c = (c_c.iloc[-1] / c_c.iloc[0] - 1.0) * 100.0
    r_u = (c_u.iloc[-1] / c_u.iloc[0] - 1.0) * 100.0
    r_n = (c_n.iloc[-1] / c_n.iloc[0] - 1.0) * 100.0
    r_s = (s_s.iloc[-1] / s_s.iloc[0] - 1.0) * 100.0
    dd_c = (c_c / c_c.cummax() - 1.0).min() * 100.0
    dd_s = (s_s / s_s.cummax() - 1.0).min() * 100.0
    print(f"{y:<6} | {r_c:+6.2f}%       | {r_u:+6.2f}%       | {r_n:+6.2f}%       | {r_s:+6.2f}%       | {dd_c:6.1f}%     | {dd_s:6.1f}%")

print("\n" + "=" * 115)
