"""
Head-to-Head Comparison Runner:
MCX Aluminium Raw 200 SMA vs Enhanced 200 SMA on 15m Futures (Nov 2025 - Nov 2026).
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.indicators import adx, sma_envelope
from src.engine.costs import TransactionCostModel
from src.schema.strategy import OrderAction, InstrumentType
from src.strategies.mcx_aluminium_200_sma_enhanced import get_mcx_aluminium_200_sma_enhanced_strategy


def run_mcx_backtest(parquet_path: str, is_mini: bool = False):
    df = pd.read_parquet(parquet_path)
    lot_size = 1000 if is_mini else 5000
    lot_name = "Mini Lot (1 MT / 1,000 kg)" if is_mini else "Big Lot (5 MT / 5,000 kg)"
    
    print(f"\n================================================================================")
    print(f"📊 MCX ALUMINIUM 200 SMA 15M FUTURES BACKTEST AUDIT")
    print(f"Contract: {lot_name} | Period: {df.index[0].date()} to {df.index[-1].date()}")
    print(f"Total Candles: {len(df):,} | Price Range: ₹{df['close'].min():.2f} - ₹{df['close'].max():.2f}")
    print(f"================================================================================\n")

    # Compute indicators
    df['sma200'] = df['close'].rolling(200).mean()
    env = sma_envelope(df[['open', 'high', 'low', 'close']], period=200, atr_period=14, multiplier=1.0, field='close')
    df['upper_band'] = env['upper']
    df['lower_band'] = env['lower']
    adx_res = adx(df[['high', 'low', 'close']], period=14)
    df['adx'] = adx_res['adx']

    cost_model = TransactionCostModel(
        brokerage_per_order=20.0,
        futures_stt_pct=0.0001,  # 0.01% CTT
        futures_exchange_pct=0.000021,  # 0.0021% MCX
        futures_slippage_fixed=20.0
    )

    def simulate(use_envelope, adx_thresh, sl_pct, tp_pct, cooldown_bars, time_filter):
        valid = df.dropna(subset=['sma200', 'adx', 'upper_band']).copy()
        valid.reset_index(inplace=True)
        
        pos = 0
        entry_price = 0.0
        entry_bar = -1
        last_loss_bar = -999
        trades = []
        
        for i, row in valid.iterrows():
            close = row['close']
            high = row['high']
            low = row['low']
            sma = row['sma200']
            up = row['upper_band'] if use_envelope else sma
            dn = row['lower_band'] if use_envelope else sma
            adx_val = row['adx']
            bar_time = row['timestamp'].time()
            
            if pos != 0:
                exit_trade = False
                exit_price = close
                exit_reason = ''
                
                if pos == 1:
                    if sl_pct and low <= entry_price * (1 - sl_pct):
                        exit_price = entry_price * (1 - sl_pct)
                        exit_reason = 'SL'
                        exit_trade = True
                    elif tp_pct and high >= entry_price * (1 + tp_pct):
                        exit_price = entry_price * (1 + tp_pct)
                        exit_reason = 'TP'
                        exit_trade = True
                    elif close < sma:
                        exit_price = close
                        exit_reason = 'SMA_CROSS'
                        exit_trade = True
                elif pos == -1:
                    if sl_pct and high >= entry_price * (1 + sl_pct):
                        exit_price = entry_price * (1 + sl_pct)
                        exit_reason = 'SL'
                        exit_trade = True
                    elif tp_pct and low <= entry_price * (1 - tp_pct):
                        exit_price = entry_price * (1 - tp_pct)
                        exit_reason = 'TP'
                        exit_trade = True
                    elif close > sma:
                        exit_price = close
                        exit_reason = 'SMA_CROSS'
                        exit_trade = True
                        
                if exit_trade:
                    gross_pnl = (exit_price - entry_price) * pos * lot_size
                    c_entry = cost_model.calculate(OrderAction.BUY if pos == 1 else OrderAction.SELL, InstrumentType.FUTURES, entry_price, lot_size)
                    c_exit = cost_model.calculate(OrderAction.SELL if pos == 1 else OrderAction.BUY, InstrumentType.FUTURES, exit_price, lot_size)
                    friction = c_entry.total + c_exit.total
                    net_pnl = gross_pnl - friction
                    
                    if net_pnl < 0:
                        last_loss_bar = i
                        
                    trades.append({
                        'gross_pnl': gross_pnl,
                        'friction': friction,
                        'net_pnl': net_pnl,
                        'exit_reason': exit_reason,
                    })
                    pos = 0
                    
            if pos == 0:
                if (i - last_loss_bar) < cooldown_bars:
                    continue
                if time_filter:
                    time_mins = bar_time.hour * 60 + bar_time.minute
                    if time_mins < 13 * 60 or time_mins > 22 * 60 + 30:
                        continue
                if adx_thresh and adx_val < adx_thresh:
                    continue
                    
                if close > up:
                    pos = 1
                    entry_price = close
                    entry_bar = i
                elif close < dn:
                    pos = -1
                    entry_price = close
                    entry_bar = i
                    
        tdf = pd.DataFrame(trades)
        wins = tdf[tdf['net_pnl'] > 0]
        losses = tdf[tdf['net_pnl'] < 0]
        win_rate = (len(wins) / len(tdf) * 100) if len(tdf) > 0 else 0
        profit_factor = (wins['net_pnl'].sum() / abs(losses['net_pnl'].sum())) if len(losses) > 0 else np.nan
        
        return {
            'trades': len(tdf),
            'gross_pnl': tdf['gross_pnl'].sum(),
            'friction': tdf['friction'].sum(),
            'net_pnl': tdf['net_pnl'].sum(),
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'tp_count': (tdf['exit_reason'] == 'TP').sum(),
            'sl_count': (tdf['exit_reason'] == 'SL').sum(),
            'sma_count': (tdf['exit_reason'] == 'SMA_CROSS').sum(),
        }

    raw = simulate(False, 0, None, None, 0, False)
    enh = simulate(True, 25.0, 0.008, 0.015, 8, True)
    
    print(f"{'Metric':<25} | {'Raw 200 SMA (Baseline)':<22} | {'Enhanced Strategy (V2)':<22} | {'Impact / Alpha':<15}")
    print(f"{'-'*25}-|-{'-'*22}-|-{'-'*22}-|-{'-'*15}")
    print(f"{'Trades Count':<25} | {raw['trades']:<22} | {enh['trades']:<22} | {enh['trades'] - raw['trades']} trades")
    print(f"{'Win Rate (%)':<25} | {raw['win_rate']:<21.1f}% | {enh['win_rate']:<21.1f}% | +{enh['win_rate'] - raw['win_rate']:.1f}%")
    print(f"{'Profit Factor':<25} | {raw['profit_factor']:<22.2f} | {enh['profit_factor']:<22.2f} | +{enh['profit_factor'] - raw['profit_factor']:.2f}")
    print(f"{'Gross PnL (₹)':<25} | ₹{raw['gross_pnl']:<21,.0f} | ₹{enh['gross_pnl']:<21,.0f} | +₹{enh['gross_pnl'] - raw['gross_pnl']:,.0f}")
    print(f"{'Friction / Taxes (₹)':<25} | ₹{raw['friction']:<21,.0f} | ₹{enh['friction']:<21,.0f} | -₹{raw['friction'] - enh['friction']:,.0f}")
    print(f"{'Net PnL (₹)':<25} | ₹{raw['net_pnl']:<21,.0f} | ₹{enh['net_pnl']:<21,.0f} | +₹{enh['net_pnl'] - raw['net_pnl']:,.0f}")
    print(f"\nExit Breakdown for Enhanced: TP Hit: {enh['tp_count']} | SL Hit: {enh['sl_count']} | SMA Cross: {enh['sma_count']}")


if __name__ == '__main__':
    run_mcx_backtest('data/cache/MCX_ALUMINIUM_15m_2025_2026.parquet', is_mini=False)
    run_mcx_backtest('data/cache/MCX_ALUMINIUM_15m_2025_2026.parquet', is_mini=True)

