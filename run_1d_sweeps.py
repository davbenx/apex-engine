#!/usr/bin/env python3
"""
run_1d_sweeps.py — Execution of 1D Policy Cuts (T1 Mix, T2 BTC Cap, T3 Vol-Target)
Implements:
  Objective: max 0.5 * CAGR_spend + 0.5 * CAGR_5p_63d
  s.t. MDD_boot_63d >= -B, MDD_hist >= -1.1B, w_BTC <= c, sum(w) <= 1
  with B in {15%, 20%, 25%}.
Calculates all required metrics:
  - CAGR ongoing & spendable, Vol, Sharpe (rf=0, rf=3%), Sortino, Calmar
  - Ulcer Index, Months Underwater (count & %), CVaR 95/99, STARR
  - Historical MDD, 21d and 63d Block Bootstrap (5,000 paths: 5th pct CAGR & MDD)
  - 4-Fold Walk-Forward Efficiency (IS vs OOS Calmar & Sharpe)
  - Terminal Tax Drag, Mean BTC weight, BTC Contribution
  - Stress tests (2018, 2020, 2022, 2025)
Also executes Apex fine vol-target sweep (13-35% at 1% steps) evaluating OOS metrics.
"""
import os, sys, pickle, time
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

print("Loading cached point-in-time market data...")
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

for s in [eurusd_s, xeon_s]:
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

r_ntsg_eur = (1.0 + r_ntsg_usd) * fx_ratio - 1.0
r_avws_eur = (1.0 + r_avws_usd) * fx_ratio - 1.0
r_dbmfe_eur = (1.0 + r_dbmfe_usd) * fx_ratio - 1.0
r_ppfb_eur = (1.0 + r_ppfb_usd) * fx_ratio - 1.0
r_wbtc_eur = (1.0 + r_wbtc_usd) * fx_ratio - 1.0

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
    return pd.Series([v for d, v in history], index=[d for d, v in history])

convex_eur_standard = build_convex_series(exclude_btc=False)
convex_eur_nobtc = build_convex_series(exclude_btc=True)

# ------------------------------------------------------------------------------
# SIMULATION ENGINE FOR APEX
# ------------------------------------------------------------------------------
def simulate_apex_engine(vol_target=0.13, btc_apex_cap=0.085, trim_drift_to_cap=True, exclude_btc=False):
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
        
        # Cash return
        c_ret = float(r_xeon.loc[dt]) if i > 0 else 0.0
        cash_net *= (1.0 + c_ret)
        
        # Execution
        if pending_rebal is not None and i >= pending_rebal['exec_idx']:
            reb = pending_rebal
            target_allocs = reb['allocations']
            target_basket = reb['basket']
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
            
        # Drift trim
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
                
        # Decision
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
            scale = min(1.0, vol_target / port_vol) if port_vol > 1e-6 else 1.0
            raw_w = {c: base_w[c] * scale for c in base_w}
            
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
            
        pos_val_net = sum(sh * get_price_eur(s, i) for s, sh in pos_shares.items())
        cur_nav_net = cash_net + pos_val_net
        
        btc_sh = pos_shares.get('BTC-USD', 0.0)
        btc_val = btc_sh * get_price_eur('BTC-USD', i)
        btc_wt = btc_val / cur_nav_net if cur_nav_net > 0 else 0.0
        btc_weight_history.append((dt, btc_wt))
        
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
            
            bollo = cur_nav_net * 0.0020
            cur_nav_net -= bollo
            cash_net = max(0.0, cash_net - bollo)
            total_bollo_paid += bollo
            
        nav_history.append((dt, cur_nav_net))
        
    s_net = pd.Series([n for d, n in nav_history], index=[d for d, n in nav_history])
    s_btc = pd.Series([w for d, w in btc_weight_history], index=[d for d, w in btc_weight_history])
    
    # Terminal tax
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

# Walk-forward fold definitions
FOLDS = [
    ('Fold 1 (2014-2016 IS -> 2017-2019 OOS)', '2014-11-03', '2016-12-30', '2017-01-03', '2019-12-31'),
    ('Fold 2 (2014-2018 IS -> 2019-2021 OOS)', '2014-11-03', '2018-12-31', '2019-01-02', '2021-12-31'),
    ('Fold 3 (2014-2021 IS -> 2022-2024 OOS)', '2014-11-03', '2021-12-31', '2022-01-03', '2024-12-31'),
    ('Fold 4 (2014-2022 IS -> 2023-2026 OOS)', '2014-11-03', '2022-12-30', '2023-01-03', '2026-08-25')
]

# ------------------------------------------------------------------------------
# FULL CELL EVALUATOR
# ------------------------------------------------------------------------------
def evaluate_cell(w_apex, btc_cap, vol_target):
    w_convex = 1.0 - w_apex
    
    # Convex sleeve selection & BTC capacity
    if btc_cap == 0.0:
        convex_s = convex_eur_nobtc
        btc_apex_cap = 0.0
        exclude_btc = True
    else:
        convex_s = convex_eur_standard
        # Convex provides w_convex * 0.075 to BTC
        w_btc_convex = w_convex * 0.075
        btc_apex_cap = max(0.0, (btc_cap - w_btc_convex) / w_apex) if w_apex > 0 else 0.0
        exclude_btc = False
        
    # Simulate Apex
    apex_nav, apex_btc_w, apex_liq, _ = simulate_apex_engine(
        vol_target=vol_target,
        btc_apex_cap=btc_apex_cap,
        trim_drift_to_cap=True,
        exclude_btc=exclude_btc
    )
    
    # Combine daily returns
    r_comb = w_apex * apex_nav.pct_change().fillna(0.0) + w_convex * convex_s.pct_change().fillna(0.0)
    comb_nav = 100_000.0 * (1.0 + r_comb).cumprod()
    
    # Combined BTC weight daily
    if exclude_btc:
        comb_btc_w = pd.Series(0.0, index=apex_nav.index)
    else:
        comb_btc_w = w_apex * apex_btc_w + w_convex * 0.075
        
    # Terminal liquidation
    convex_gain = max(0.0, convex_s.iloc[-1] - 100_000.0)
    convex_liq = convex_s.iloc[-1] - (convex_gain * 0.26)
    comb_liq = w_apex * apex_liq + w_convex * convex_liq
    
    yrs = (comb_nav.index[-1] - comb_nav.index[0]).days / 365.25
    cagr_ongoing = (comb_nav.iloc[-1] / 100_000.0) ** (1.0 / yrs) - 1.0
    cagr_spend = (comb_liq / 100_000.0) ** (1.0 / yrs) - 1.0
    tax_drag = cagr_ongoing - cagr_spend
    
    # Return metrics
    r = comb_nav.pct_change().dropna()
    vol = r.std() * np.sqrt(252)
    sh0 = (r.mean() * 252) / (vol + 1e-12)
    sh3 = (r.mean() * 252 - 0.03) / (vol + 1e-12)
    
    downside = r[r < 0]
    sortino = (r.mean() * 252) / (downside.std() * np.sqrt(252) + 1e-12)
    
    # Drawdown & Ulcer Index
    roll_max = comb_nav.cummax()
    dd_curve = (comb_nav - roll_max) / roll_max
    mdd_hist = dd_curve.min()
    ulcer_index = np.sqrt(np.mean(dd_curve ** 2)) * 100.0
    calmar = cagr_spend / abs(mdd_hist) if mdd_hist != 0 else np.nan
    
    # Months underwater
    monthly_nav = comb_nav.resample('ME').last()
    monthly_rollmax = monthly_nav.cummax()
    is_underwater = monthly_nav < monthly_rollmax
    n_underwater_months = int(is_underwater.sum())
    pct_underwater_months = float(is_underwater.mean()) * 100.0
    
    # Daily CVaR 95% and 99% (expressed as positive annualised loss)
    q05 = np.percentile(r, 5)
    cvar_95_daily = -float(r[r <= q05].mean())
    cvar_95_ann = cvar_95_daily * np.sqrt(252)
    
    q01 = np.percentile(r, 1)
    cvar_99_daily = -float(r[r <= q01].mean())
    cvar_99_ann = cvar_99_daily * np.sqrt(252)
    
    starr_95 = (r.mean() * 252) / (cvar_95_ann + 1e-12)
    
    # Block bootstrap (5,000 paths) on 21d and 63d blocks
    np.random.seed(42)
    r_arr = r.values
    N_DAYS = len(r_arr)
    N_PATHS = 5000
    
    def bootstrap_stats(block_len):
        n_blocks = int(np.ceil(N_DAYS / block_len))
        cagrs, mdds = [], []
        for _ in range(N_PATHS):
            starts = np.random.randint(0, N_DAYS - block_len + 1, size=n_blocks)
            sample = np.concatenate([r_arr[s:s+block_len] for s in starts])[:N_DAYS]
            curve = np.cumprod(1.0 + sample)
            cagrs.append((curve[-1] ** (252.0 / N_DAYS)) - 1.0)
            rm = np.maximum.accumulate(curve)
            mdds.append(np.min((curve - rm) / rm))
        return {
            'cagr_p5': float(np.percentile(cagrs, 5)),
            'cagr_p50': float(np.percentile(cagrs, 50)),
            'mdd_p5_worst': float(np.percentile(mdds, 5)),
            'mdd_p50': float(np.percentile(mdds, 50))
        }
        
    boot_21 = bootstrap_stats(21)
    boot_63 = bootstrap_stats(63)
    
    # Walk-forward 4-fold
    wfe_calmar_list = []
    wfe_sharpe_list = []
    oos_calmars = []
    oos_starrs = []
    
    for label, is_s, is_e, oos_s, oos_e in FOLDS:
        s_is = comb_nav.loc[is_s:is_e]
        s_oos = comb_nav.loc[oos_s:oos_e]
        
        # IS stats
        yrs_is = (s_is.index[-1] - s_is.index[0]).days / 365.25
        cagr_is = (s_is.iloc[-1] / s_is.iloc[0]) ** (1.0 / yrs_is) - 1.0
        mdd_is = (s_is / s_is.cummax() - 1.0).min()
        calmar_is = cagr_is / abs(mdd_is) if mdd_is != 0 else np.nan
        r_is = s_is.pct_change().dropna()
        sh_is = (r_is.mean() * 252) / (r_is.std() * np.sqrt(252) + 1e-12)
        
        # OOS stats
        yrs_oos = (s_oos.index[-1] - s_oos.index[0]).days / 365.25
        cagr_oos = (s_oos.iloc[-1] / s_oos.iloc[0]) ** (1.0 / yrs_oos) - 1.0
        mdd_oos = (s_oos / s_oos.cummax() - 1.0).min()
        calmar_oos = cagr_oos / abs(mdd_oos) if mdd_oos != 0 else np.nan
        r_oos = s_oos.pct_change().dropna()
        sh_oos = (r_oos.mean() * 252) / (r_oos.std() * np.sqrt(252) + 1e-12)
        q05_oos = np.percentile(r_oos, 5)
        cvar95_oos = -float(r_oos[r_oos <= q05_oos].mean()) * np.sqrt(252)
        starr_oos = (r_oos.mean() * 252) / (cvar95_oos + 1e-12)
        
        oos_calmars.append(calmar_oos)
        oos_starrs.append(starr_oos)
        wfe_calmar_list.append(calmar_oos / calmar_is if calmar_is > 0 else np.nan)
        wfe_sharpe_list.append(sh_oos / sh_is if sh_is > 0 else np.nan)
        
    mean_wfe_calmar = float(np.nanmean(wfe_calmar_list))
    mean_wfe_sharpe = float(np.nanmean(wfe_sharpe_list))
    mean_oos_calmar = float(np.nanmean(oos_calmars))
    mean_oos_starr = float(np.nanmean(oos_starrs))
    
    # Stress years: 2018, 2020, 2022, 2025
    stress = {}
    for y in [2018, 2020, 2022, 2025]:
        sub = comb_nav[comb_nav.index.year == y]
        if len(sub) > 10:
            ret_y = (sub.iloc[-1] / sub.iloc[0] - 1.0) * 100.0
            mdd_y = (sub / sub.cummax() - 1.0).min() * 100.0
            stress[y] = (ret_y, mdd_y)
        else:
            stress[y] = (np.nan, np.nan)
            
    # Objective scores for B in {15%, 20%, 25%}
    obj_raw = 0.5 * cagr_spend + 0.5 * boot_63['cagr_p5']
    feasibility = {}
    for B in [0.15, 0.20, 0.25]:
        is_feas = (boot_63['mdd_p5_worst'] >= -B) and (mdd_hist >= -1.1 * B)
        feasibility[B] = is_feas
        
    return {
        'w_apex': w_apex,
        'w_convex': w_convex,
        'btc_cap': btc_cap,
        'vol_target': vol_target,
        'cagr_ongoing': cagr_ongoing,
        'cagr_spend': cagr_spend,
        'tax_drag': tax_drag,
        'vol': vol,
        'sh0': sh0,
        'sh3': sh3,
        'sortino': sortino,
        'calmar': calmar,
        'ulcer_index': ulcer_index,
        'n_underwater_months': n_underwater_months,
        'pct_underwater_months': pct_underwater_months,
        'cvar_95_ann': cvar_95_ann,
        'cvar_99_ann': cvar_99_ann,
        'starr_95': starr_95,
        'mdd_hist': mdd_hist,
        'boot21_mdd5': boot_21['mdd_p5_worst'],
        'boot21_cagr5': boot_21['cagr_p5'],
        'boot63_mdd5': boot_63['mdd_p5_worst'],
        'boot63_cagr5': boot_63['cagr_p5'],
        'wfe_calmar': mean_wfe_calmar,
        'wfe_sharpe': mean_wfe_sharpe,
        'oos_calmar': mean_oos_calmar,
        'oos_starr': mean_oos_starr,
        'mean_btc_w': float(comb_btc_w.mean()),
        'max_btc_w': float(comb_btc_w.max()),
        'stress_2018': stress[2018],
        'stress_2020': stress[2020],
        'stress_2022': stress[2022],
        'stress_2025': stress[2025],
        'obj_raw': obj_raw,
        'feas_15': feasibility[0.15],
        'feas_20': feasibility[0.20],
        'feas_25': feasibility[0.25],
    }

# ==============================================================================
# EXECUTE 1D CUTS
# ==============================================================================
print("\n" + "=" * 115)
print("EXECUTING THREE 1D POLICY CUTS: T1 MIX, T2 BTC CAP, T3 VOL-TARGET")
print("=" * 115)

# Reference zero-cap cell for BTC contribution calculation (50/50, cap 0%, vol 13%)
print("Computing zero-BTC baseline for marginal contribution...")
cell_zero_btc = evaluate_cell(w_apex=0.50, btc_cap=0.0, vol_target=0.13)
cagr_zero_btc = cell_zero_btc['cagr_spend']

# T1: Mix Apex (35% / 50% / 65%) with freeze (Cap BTC 8%, Vol 13%)
print("\n--- Running Cut T1: Mix Apex (35% / 50% / 65%) ---")
t1_results = []
for w in [0.35, 0.50, 0.65]:
    print(f"  Evaluating Apex {int(w*100)}% / Convex {int((1-w)*100)}%...")
    res = evaluate_cell(w_apex=w, btc_cap=0.08, vol_target=0.13)
    t1_results.append(res)

# T2: Cap BTC (0% / 4% / 8% / 10%) with freeze (Mix 50/50, Vol 13%)
print("\n--- Running Cut T2: Cap BTC (0% / 4% / 8% / 10%) ---")
t2_results = []
for c in [0.0, 0.04, 0.08, 0.10]:
    print(f"  Evaluating Cap BTC {int(c*100)}%...")
    res = evaluate_cell(w_apex=0.50, btc_cap=c, vol_target=0.13)
    t2_results.append(res)

# T3: Vol-Target Apex (10% / 13% / 16%) with freeze (Mix 50/50, Cap 8%)
print("\n--- Running Cut T3: Vol-Target Apex (10% / 13% / 16%) ---")
t3_results = []
for vt in [0.10, 0.13, 0.16]:
    print(f"  Evaluating Apex Vol-Target {int(vt*100)}%...")
    res = evaluate_cell(w_apex=0.50, btc_cap=0.08, vol_target=vt)
    t3_results.append(res)

# ------------------------------------------------------------------------------
# APEX FINE SWEEP (13-35% at 1% increments)
# ------------------------------------------------------------------------------
print("\n--- Running Apex Standalone Fine Vol-Target Sweep (13% - 35% by 1%) ---")
apex_sweep_results = []
for vt in range(13, 36):
    vt_flt = vt / 100.0
    # Simulate Apex standalone (exclude_btc=False, btc_apex_cap=None, trim_drift=False)
    s_nav, _, s_liq, _ = simulate_apex_engine(vol_target=vt_flt, btc_apex_cap=None, trim_drift_to_cap=False, exclude_btc=False)
    yrs = (s_nav.index[-1] - s_nav.index[0]).days / 365.25
    cagr_full = (s_nav.iloc[-1] / 100_000.0) ** (1.0 / yrs) - 1.0
    mdd_full = (s_nav / s_nav.cummax() - 1.0).min()
    r = s_nav.pct_change().dropna()
    geom_mean = np.exp(np.mean(np.log(1.0 + r))) ** 252 - 1.0
    
    # 4-Fold OOS CAGR and Calmar
    oos_cagrs = []
    oos_mdds = []
    oos_calmars = []
    for label, is_s, is_e, oos_s, oos_e in FOLDS:
        sub_oos = s_nav.loc[oos_s:oos_e]
        yrs_o = (sub_oos.index[-1] - sub_oos.index[0]).days / 365.25
        cg_o = (sub_oos.iloc[-1] / sub_oos.iloc[0]) ** (1.0 / yrs_o) - 1.0
        dd_o = (sub_oos / sub_oos.cummax() - 1.0).min()
        oos_cagrs.append(cg_o)
        oos_mdds.append(dd_o)
        oos_calmars.append(cg_o / abs(dd_o) if dd_o != 0 else np.nan)
        
    apex_sweep_results.append({
        'vol_target': vt,
        'cagr_full': cagr_full,
        'geom_mean': geom_mean,
        'mdd_full': mdd_full,
        'calmar_full': cagr_full / abs(mdd_full),
        'oos_cagr_mean': float(np.mean(oos_cagrs)),
        'oos_mdd_mean': float(np.mean(oos_mdds)),
        'oos_calmar_mean': float(np.nanmean(oos_calmars)),
    })
df_apex_sweep = pd.DataFrame(apex_sweep_results)
df_apex_sweep.to_csv(os.path.join(OUTPUT_DIR, 'apex_fine_vol_target_sweep.csv'), index=False)

# ------------------------------------------------------------------------------
# PRINT COMPREHENSIVE TABLES FOR T1, T2, T3
# ------------------------------------------------------------------------------
def print_cut_table(cut_name, results):
    print(f"\n" + "=" * 125)
    print(f"RISULTATI TAGLIO 1D: {cut_name}")
    print("=" * 125)
    header = f"{'Configurazione':<22} | {'CAGR Sp':<8} | {'CAGR 5°':<8} | {'Obj 50/50':<9} | {'Vol':<7} | {'Sh 0':<6} | {'Calm':<6} | {'Ulcer':<6} | {'STARR':<6} | {'MDD H':<7} | {'MDD 63g':<8} | {'OOS Calm':<8} | {'Stress 2022':<12} | {'B20 Feas':<8}"
    print(header)
    print("-" * 125)
    for r in results:
        cfg = f"Ap {int(r['w_apex']*100)}/Cv {int(r['w_convex']*100)} C{int(r['btc_cap']*100)} V{int(r['vol_target']*100)}"
        c_sp = f"{r['cagr_spend']*100:5.2f}%"
        c_5p = f"{r['boot63_cagr5']*100:5.2f}%"
        obj = f"{r['obj_raw']*100:5.2f}%"
        vol = f"{r['vol']*100:5.2f}%"
        sh = f"{r['sh0']:4.2f}"
        calm = f"{r['calmar']:4.2f}"
        ulc = f"{r['ulcer_index']:4.2f}"
        starr = f"{r['starr_95']:4.2f}"
        mdd_h = f"{r['mdd_hist']*100:5.1f}%"
        mdd_63 = f"{r['boot63_mdd5']*100:5.1f}%"
        oos_c = f"{r['oos_calmar']:4.2f}"
        st_22 = f"{r['stress_2022'][0]:+5.1f}% ({r['stress_2022'][1]:4.1f}%)"
        feas = "PASS" if r['feas_20'] else "FAIL"
        print(f"{cfg:<22} | {c_sp:<8} | {c_5p:<8} | {obj:<9} | {vol:<7} | {sh:<6} | {calm:<6} | {ulc:<6} | {starr:<6} | {mdd_h:<7} | {mdd_63:<8} | {oos_c:<8} | {st_22:<12} | {feas:<8}")

print_cut_table("T1 — MIX APEX / CONVEX (35% / 50% / 65%) [Freeze: Cap BTC 8%, Vol-Target 13%]", t1_results)
print_cut_table("T2 — CAP BTC COMBINED (0% / 4% / 8% / 10%) [Freeze: Mix 50/50, Vol-Target 13%]", t2_results)
print_cut_table("T3 — VOL-TARGET APEX (10% / 13% / 16%) [Freeze: Mix 50/50, Cap BTC 8%]", t3_results)

# ------------------------------------------------------------------------------
# PRINT DETAILED STRESS TEST AND BTC ELASTICITY METRICS
# ------------------------------------------------------------------------------
print("\n" + "=" * 125)
print("ANALISI DI STRESS ANNUALE E ELASTICITÀ DI BITCOIN")
print("=" * 125)
print(f"{'Taglio & Configurazione':<30} | {'Stress 2018':<14} | {'Stress 2020':<14} | {'Stress 2022':<14} | {'Stress 2025':<14} | {'BTC Mean':<8} | {'BTC Contrib':<11} | {'Elasticità':<10}")
print("-" * 125)

# For T2 calculate elasticity: delta_CAGR / delta_mean_BTC
prev_cagr = None
prev_btc = None
for r in t2_results:
    cfg = f"Cap BTC {int(r['btc_cap']*100)}%"
    s18 = f"{r['stress_2018'][0]:+5.1f}% ({r['stress_2018'][1]:4.1f}%)"
    s20 = f"{r['stress_2020'][0]:+5.1f}% ({r['stress_2020'][1]:4.1f}%)"
    s22 = f"{r['stress_2022'][0]:+5.1f}% ({r['stress_2022'][1]:4.1f}%)"
    s25 = f"{r['stress_2025'][0]:+5.1f}% ({r['stress_2025'][1]:4.1f}%)"
    btc_m = f"{r['mean_btc_w']*100:4.2f}%"
    contrib = f"{(r['cagr_spend'] - cagr_zero_btc)*100:+5.2f} pp"
    if prev_btc is not None and (r['mean_btc_w'] - prev_btc) > 1e-4:
        elast = (r['cagr_spend'] - prev_cagr) / (r['mean_btc_w'] - prev_btc)
        elast_str = f"{elast:6.2f}"
    else:
        elast_str = "Base 0%"
    prev_cagr = r['cagr_spend']
    prev_btc = r['mean_btc_w']
    print(f"{cfg:<30} | {s18:<14} | {s20:<14} | {s22:<14} | {s25:<14} | {btc_m:<8} | {contrib:<11} | {elast_str:<10}")

# Save all results to CSV
all_res = t1_results + t2_results + t3_results
df_all = pd.DataFrame(all_res)
df_all.to_csv(os.path.join(OUTPUT_DIR, 'results_1d_sweeps.csv'), index=False)
print("\nAll 1D results successfully exported to results_1d_sweeps.csv and apex_fine_vol_target_sweep.csv.")
