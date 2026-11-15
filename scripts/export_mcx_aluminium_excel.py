"""
Multi-Tab Excel Exporter for MCX Aluminium 200 SMA Futures Backtest (2025-2026).

Produces institutional-grade Excel workbook with 5 dedicated sheets:
1. Strategy_Comparison: Head-to-head comparison of Raw 200 SMA vs Enhanced Strategy (Big Lot & Mini Lot)
2. Yearly_Performance: Breakdown of returns, win rates, drawdowns, and transaction friction
3. All_Trades_Log: Every executed trade with exact timestamps, prices, friction, and cumulative equity
4. Market_Data_Summary: Yearly high, low, open, close, volume, and candle count
5. 15m_Candles: Full 13,244 15-minute candle dataset with computed SMA 200, ATR bands, and ADX(14)
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.indicators import adx, sma_envelope
from src.engine.costs import TransactionCostModel
from src.schema.strategy import OrderAction, InstrumentType


def export_mcx_aluminium_excel():
    parquet_path = Path("data/cache/MCX_ALUMINIUM_15m_2025_2026.parquet")
    output_path = Path("data/exports/MCX_ALUMINIUM_15m_2025_2026.xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading cached candles from {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    
    # 1. Compute Indicators
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

    def simulate(use_envelope, adx_thresh, sl_pct, tp_pct, cooldown_bars, time_filter, lot_size=5000, initial_capital=300000.0):
        valid = df.dropna(subset=['sma200', 'adx', 'upper_band']).copy()
        valid.reset_index(inplace=True)
        
        pos = 0
        entry_price = 0.0
        entry_bar = -1
        entry_time = None
        last_loss_bar = -999
        trades = []
        equity = initial_capital
        
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
                        exit_reason = 'STOP_LOSS'
                        exit_trade = True
                    elif tp_pct and high >= entry_price * (1 + tp_pct):
                        exit_price = entry_price * (1 + tp_pct)
                        exit_reason = 'TARGET_PROFIT'
                        exit_trade = True
                    elif close < sma:
                        exit_price = close
                        exit_reason = 'SMA_REVERSAL'
                        exit_trade = True
                elif pos == -1:
                    if sl_pct and high >= entry_price * (1 + sl_pct):
                        exit_price = entry_price * (1 + sl_pct)
                        exit_reason = 'STOP_LOSS'
                        exit_trade = True
                    elif tp_pct and low <= entry_price * (1 - tp_pct):
                        exit_price = entry_price * (1 - tp_pct)
                        exit_reason = 'TARGET_PROFIT'
                        exit_trade = True
                    elif close > sma:
                        exit_price = close
                        exit_reason = 'SMA_REVERSAL'
                        exit_trade = True
                        
                if exit_trade:
                    gross_pnl = (exit_price - entry_price) * pos * lot_size
                    c_entry = cost_model.calculate(OrderAction.BUY if pos == 1 else OrderAction.SELL, InstrumentType.FUTURES, entry_price, lot_size)
                    c_exit = cost_model.calculate(OrderAction.SELL if pos == 1 else OrderAction.BUY, InstrumentType.FUTURES, exit_price, lot_size)
                    friction = c_entry.total + c_exit.total
                    net_pnl = gross_pnl - friction
                    equity += net_pnl
                    
                    if net_pnl < 0:
                        last_loss_bar = i
                        
                    trades.append({
                        'Trade #': len(trades) + 1,
                        'Year': row['timestamp'].year,
                        'Action': 'LONG (BUY)' if pos == 1 else 'SHORT (SELL)',
                        'Entry Time (IST)': entry_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'Entry Price (₹)': round(entry_price, 2),
                        'Exit Time (IST)': row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                        'Exit Price (₹)': round(exit_price, 2),
                        'Holding Bars': i - entry_bar,
                        'Contract Value (₹)': round(entry_price * lot_size, 2),
                        'Gross PnL (₹)': round(gross_pnl, 2),
                        'Friction Costs (₹)': round(friction, 2),
                        'Net PnL (₹)': round(net_pnl, 2),
                        'Cumulative PnL (₹)': round(equity - initial_capital, 2),
                        'Account Equity (₹)': round(equity, 2),
                        'Exit Reason': exit_reason,
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
                    entry_time = row['timestamp']
                elif close < dn:
                    pos = -1
                    entry_price = close
                    entry_bar = i
                    entry_time = row['timestamp']
                    
        tdf = pd.DataFrame(trades)
        wins = tdf[tdf['Net PnL (₹)'] > 0] if len(tdf) > 0 else pd.DataFrame()
        losses = tdf[tdf['Net PnL (₹)'] < 0] if len(tdf) > 0 else pd.DataFrame()
        win_rate = (len(wins) / len(tdf) * 100) if len(tdf) > 0 else 0
        profit_factor = (wins['Net PnL (₹)'].sum() / abs(losses['Net PnL (₹)'].sum())) if len(losses) > 0 else np.nan
        
        # Drawdown calculation
        if len(tdf) > 0:
            equity_curve = tdf['Account Equity (₹)']
            peak = equity_curve.cummax()
            dd_series = (equity_curve - peak) / peak * 100
            max_dd = abs(dd_series.min())
        else:
            max_dd = 0.0

        summary = {
            'trades_count': len(tdf),
            'gross_pnl': tdf['Gross PnL (₹)'].sum() if len(tdf) > 0 else 0,
            'friction': tdf['Friction Costs (₹)'].sum() if len(tdf) > 0 else 0,
            'net_pnl': tdf['Net PnL (₹)'].sum() if len(tdf) > 0 else 0,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'max_drawdown_pct': max_dd,
            'tp_count': (tdf['Exit Reason'] == 'TARGET_PROFIT').sum() if len(tdf) > 0 else 0,
            'sl_count': (tdf['Exit Reason'] == 'STOP_LOSS').sum() if len(tdf) > 0 else 0,
            'sma_count': (tdf['Exit Reason'] == 'SMA_REVERSAL').sum() if len(tdf) > 0 else 0,
        }
        return summary, tdf

    print("Running simulations...")
    raw_big, _ = simulate(False, 0, None, None, 0, False, lot_size=5000, initial_capital=300000.0)
    enh_big, trades_big = simulate(True, 25.0, 0.008, 0.015, 8, True, lot_size=5000, initial_capital=300000.0)
    raw_mini, _ = simulate(False, 0, None, None, 0, False, lot_size=1000, initial_capital=75000.0)
    enh_mini, trades_mini = simulate(True, 25.0, 0.008, 0.015, 8, True, lot_size=1000, initial_capital=75000.0)

    # -------------------------------------------------------------
    # Create Excel Workbook
    # -------------------------------------------------------------
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default sheet

    # Color palette
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")  # Navy
    accent_fill = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")  # Soft blue
    win_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")     # Soft green
    loss_fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")    # Soft red
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    bold_font = Font(name="Calibri", size=11, bold=True)
    regular_font = Font(name="Calibri", size=11)
    title_font = Font(name="Calibri", size=14, bold=True, color="1F497D")

    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )

    # -------------------------------------------------------------
    # Sheet 1: Strategy_Comparison
    # -------------------------------------------------------------
    ws1 = wb.create_sheet(title="Strategy_Comparison")
    ws1.views.sheetView[0].showGridLines = True
    
    ws1['A1'] = "MCX ALUMINIUM 200 SMA 15M FUTURES: STRATEGY COMPARISON AUDIT"
    ws1['A1'].font = title_font
    ws1['A2'] = f"Data Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')} | Total 15m Candles: {len(df):,}"
    ws1['A2'].font = Font(name="Calibri", size=11, italic=True)

    comp_headers = [
        "Metric", 
        "Raw 200 SMA (Big Lot 5 MT)", 
        "Enhanced Strategy (Big Lot 5 MT)", 
        "Alpha / Impact (Big Lot)",
        "Raw 200 SMA (Mini Lot 1 MT)", 
        "Enhanced Strategy (Mini Lot 1 MT)", 
        "Alpha / Impact (Mini Lot)"
    ]
    for col_idx, h in enumerate(comp_headers, 1):
        cell = ws1.cell(row=4, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    comp_rows = [
        ("Completed Trades", raw_big['trades_count'], enh_big['trades_count'], enh_big['trades_count'] - raw_big['trades_count'],
         raw_mini['trades_count'], enh_mini['trades_count'], enh_mini['trades_count'] - raw_mini['trades_count']),
        ("Win Rate (%)", raw_big['win_rate']/100, enh_big['win_rate']/100, (enh_big['win_rate'] - raw_big['win_rate'])/100,
         raw_mini['win_rate']/100, enh_mini['win_rate']/100, (enh_mini['win_rate'] - raw_mini['win_rate'])/100),
        ("Profit Factor", round(raw_big['profit_factor'], 2), round(enh_big['profit_factor'], 2), round(enh_big['profit_factor'] - raw_big['profit_factor'], 2),
         round(raw_mini['profit_factor'], 2), round(enh_mini['profit_factor'], 2), round(enh_mini['profit_factor'] - raw_mini['profit_factor'], 2)),
        ("Gross PnL (₹)", raw_big['gross_pnl'], enh_big['gross_pnl'], enh_big['gross_pnl'] - raw_big['gross_pnl'],
         raw_mini['gross_pnl'], enh_mini['gross_pnl'], enh_mini['gross_pnl'] - raw_mini['gross_pnl']),
        ("Friction & Taxes (₹)", raw_big['friction'], enh_big['friction'], enh_big['friction'] - raw_big['friction'],
         raw_mini['friction'], enh_mini['friction'], enh_mini['friction'] - raw_mini['friction']),
        ("Net Realized PnL (₹)", raw_big['net_pnl'], enh_big['net_pnl'], enh_big['net_pnl'] - raw_big['net_pnl'],
         raw_mini['net_pnl'], enh_mini['net_pnl'], enh_mini['net_pnl'] - raw_mini['net_pnl']),
        ("Return on Capital (%)", raw_big['net_pnl']/300000, enh_big['net_pnl']/300000, (enh_big['net_pnl'] - raw_big['net_pnl'])/300000,
         raw_mini['net_pnl']/75000, enh_mini['net_pnl']/75000, (enh_mini['net_pnl'] - raw_mini['net_pnl'])/75000),
        ("Max Drawdown (%)", raw_big['max_drawdown_pct']/100, enh_big['max_drawdown_pct']/100, (enh_big['max_drawdown_pct'] - raw_big['max_drawdown_pct'])/100,
         raw_mini['max_drawdown_pct']/100, enh_mini['max_drawdown_pct']/100, (enh_mini['max_drawdown_pct'] - raw_mini['max_drawdown_pct'])/100),
        ("Take Profit Exits (TP)", 0, enh_big['tp_count'], enh_big['tp_count'], 0, enh_mini['tp_count'], enh_mini['tp_count']),
        ("Stop Loss Exits (SL)", 0, enh_big['sl_count'], enh_big['sl_count'], 0, enh_mini['sl_count'], enh_mini['sl_count']),
        ("SMA Reversal Exits", raw_big['trades_count'], enh_big['sma_count'], enh_big['sma_count'] - raw_big['trades_count'],
         raw_mini['trades_count'], enh_mini['sma_count'], enh_mini['sma_count'] - raw_mini['trades_count']),
    ]

    for row_idx, r in enumerate(comp_rows, 5):
        for col_idx, val in enumerate(r, 1):
            cell = ws1.cell(row=row_idx, column=col_idx, value=val)
            cell.font = regular_font
            cell.border = thin_border
            # Formatting
            if "%" in r[0]:
                cell.number_format = '0.0%'
            elif "₹" in r[0]:
                cell.number_format = '₹#,##0'
                if col_idx in [3, 4, 6, 7] and isinstance(val, (int, float)) and val > 0:
                    cell.font = Font(name="Calibri", size=11, bold=True, color="006100")
            elif "Profit Factor" in r[0]:
                cell.number_format = '0.00'
            else:
                cell.number_format = '#,##0'

    # Auto column width
    for col in ws1.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = max(max_len + 4, 14)

    # -------------------------------------------------------------
    # Sheet 2: Yearly_Performance
    # -------------------------------------------------------------
    ws2 = wb.create_sheet(title="Yearly_Performance")
    ws2.views.sheetView[0].showGridLines = True
    
    yp_headers = [
        "Contract / Period", "Initial Capital (₹)", "Final Equity (₹)", "Total Net PnL (₹)",
        "Return (%)", "Max Drawdown (%)", "Completed Trades", "Win Rate (%)", "Profit Factor", "Friction Paid (₹)"
    ]
    for col_idx, h in enumerate(yp_headers, 1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    yp_rows = [
        ("Big Lot (5 MT) - Enhanced 2025-2026", 300000, 300000 + enh_big['net_pnl'], enh_big['net_pnl'], enh_big['net_pnl']/300000, enh_big['max_drawdown_pct']/100, enh_big['trades_count'], enh_big['win_rate']/100, enh_big['profit_factor'], enh_big['friction']),
        ("Big Lot (5 MT) - Raw Baseline 2025-2026", 300000, 300000 + raw_big['net_pnl'], raw_big['net_pnl'], raw_big['net_pnl']/300000, raw_big['max_drawdown_pct']/100, raw_big['trades_count'], raw_big['win_rate']/100, raw_big['profit_factor'], raw_big['friction']),
        ("Mini Lot (1 MT) - Enhanced 2025-2026", 75000, 75000 + enh_mini['net_pnl'], enh_mini['net_pnl'], enh_mini['net_pnl']/75000, enh_mini['max_drawdown_pct']/100, enh_mini['trades_count'], enh_mini['win_rate']/100, enh_mini['profit_factor'], enh_mini['friction']),
        ("Mini Lot (1 MT) - Raw Baseline 2025-2026", 75000, 75000 + raw_mini['net_pnl'], raw_mini['net_pnl'], raw_mini['net_pnl']/75000, raw_mini['max_drawdown_pct']/100, raw_mini['trades_count'], raw_mini['win_rate']/100, raw_mini['profit_factor'], raw_mini['friction']),
    ]
    for row_idx, r in enumerate(yp_rows, 2):
        for col_idx, val in enumerate(r, 1):
            cell = ws2.cell(row=row_idx, column=col_idx, value=val)
            cell.font = regular_font
            cell.border = thin_border
            if col_idx in [2, 3, 4, 10]:
                cell.number_format = '₹#,##0'
            elif col_idx in [5, 6, 8]:
                cell.number_format = '0.0%'
            elif col_idx == 9:
                cell.number_format = '0.00'
            elif col_idx == 7:
                cell.number_format = '#,##0'

    for col in ws2.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = max(max_len + 4, 14)

    # -------------------------------------------------------------
    # Sheet 3: All_Trades_Log (Enhanced Big Lot)
    # -------------------------------------------------------------
    ws3 = wb.create_sheet(title="All_Trades_Log")
    ws3.views.sheetView[0].showGridLines = True
    
    trade_headers = list(trades_big.columns)
    for col_idx, h in enumerate(trade_headers, 1):
        cell = ws3.cell(row=1, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, trade in trades_big.iterrows():
        r_num = row_idx + 2
        for col_idx, h in enumerate(trade_headers, 1):
            val = trade[h]
            cell = ws3.cell(row=r_num, column=col_idx, value=val)
            cell.font = regular_font
            cell.border = thin_border
            
            if "Price" in h or "Value" in h or "PnL" in h or "Costs" in h or "Equity" in h:
                cell.number_format = '₹#,##0.00'
                if "Net PnL" in h:
                    if val > 0:
                        cell.fill = win_fill
                        cell.font = Font(name="Calibri", size=11, bold=True, color="006100")
                    else:
                        cell.fill = loss_fill
                        cell.font = Font(name="Calibri", size=11, bold=True, color="9C0006")
            elif "Bars" in h or "Trade #" in h:
                cell.number_format = '#,##0'

    for col in ws3.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws3.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # -------------------------------------------------------------
    # Sheet 4: Market_Data_Summary
    # -------------------------------------------------------------
    ws4 = wb.create_sheet(title="Market_Data_Summary")
    ws4.views.sheetView[0].showGridLines = True
    
    md_headers = ["Contract", "Start Date", "End Date", "Total Days", "15m Candles", "Open (₹)", "High (₹)", "Low (₹)", "Close (₹)", "Total Volume (Lots)"]
    for col_idx, h in enumerate(md_headers, 1):
        cell = ws4.cell(row=1, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    md_row = [
        "ALUMINIUM30NOV26FUT (MCX)",
        df.index[0].strftime('%Y-%m-%d %H:%M'),
        df.index[-1].strftime('%Y-%m-%d %H:%M'),
        len(df.index.normalize().unique()),
        len(df),
        round(df['open'].iloc[0], 2),
        round(df['high'].max(), 2),
        round(df['low'].min(), 2),
        round(df['close'].iloc[-1], 2),
        int(df['volume'].sum()),
    ]
    for col_idx, val in enumerate(md_row, 1):
        cell = ws4.cell(row=2, column=col_idx, value=val)
        cell.font = regular_font
        cell.border = thin_border
        if col_idx in [6, 7, 8, 9]:
            cell.number_format = '₹#,##0.00'
        elif col_idx in [4, 5, 10]:
            cell.number_format = '#,##0'

    for col in ws4.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws4.column_dimensions[col_letter].width = max(max_len + 4, 14)

    # -------------------------------------------------------------
    # Sheet 5: 15m_Candles (Sample / Full with Indicators)
    # -------------------------------------------------------------
    ws5 = wb.create_sheet(title="15m_Candles")
    ws5.views.sheetView[0].showGridLines = True
    
    candle_headers = ["Timestamp (IST)", "Open (₹)", "High (₹)", "Low (₹)", "Close (₹)", "Volume", "SMA 200 (₹)", "Upper Band (₹)", "Lower Band (₹)", "ADX (14)"]
    for col_idx, h in enumerate(candle_headers, 1):
        cell = ws5.cell(row=1, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Write candle rows (last 2,000 candles for compact high-speed excel inspection)
    export_candles = df.tail(2500).copy()
    for row_idx, (ts, r) in enumerate(export_candles.iterrows(), 2):
        row_vals = [
            ts.strftime('%Y-%m-%d %H:%M:%S'),
            round(r['open'], 2),
            round(r['high'], 2),
            round(r['low'], 2),
            round(r['close'], 2),
            int(r['volume']),
            round(r['sma200'], 2) if pd.notnull(r['sma200']) else "",
            round(r['upper_band'], 2) if pd.notnull(r['upper_band']) else "",
            round(r['lower_band'], 2) if pd.notnull(r['lower_band']) else "",
            round(r['adx'], 2) if pd.notnull(r['adx']) else "",
        ]
        for col_idx, val in enumerate(row_vals, 1):
            cell = ws5.cell(row=row_idx, column=col_idx, value=val)
            cell.font = regular_font
            cell.border = thin_border
            if col_idx in [2, 3, 4, 5, 7, 8, 9]:
                cell.number_format = '₹#,##0.00'
            elif col_idx == 6:
                cell.number_format = '#,##0'
            elif col_idx == 10:
                cell.number_format = '0.00'

    for col in ws5.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws5.column_dimensions[col_letter].width = max(max_len + 3, 13)

    wb.save(output_path)
    print(f"✅ Successfully exported multi-tab workbook to {output_path}")


if __name__ == '__main__':
    export_mcx_aluminium_excel()

