import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import os
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. CONFIGURATIE ---
st.set_page_config(page_title="BEUL QUANT-STATION v5.0", layout="wide", page_icon="🎯")

TICKERS = ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOGL", "META", "ASML.AS", "WMT", "BTC-USD"]
DB_FILE = "trade_history.csv"        
OPP_FILE = "opportunity_history.csv"  

# --- 2. CORE QUANT ENGINE ---
@st.cache_data(ttl=3600)
def get_hurst(series):
    try:
        if len(series) < 30: return 0.5
        lags = range(2, 20)
        ts = np.log(series)
        tau = [np.sqrt(np.std(np.subtract(ts[lag:], ts[:-lag]))) for lag in lags]
        return np.polyfit(np.log(lags), np.log(tau), 1)[0] * 2.0
    except: return 0.5

def get_rsi(series, window=14):
    try:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    except: return pd.Series([50] * len(series))

def monte_carlo_sim(start_price, days=21, sims=50):
    returns = np.random.normal(0.0005, 0.02, (days, sims))
    price_paths = start_price * (1 + returns).cumprod(axis=0)
    return price_paths

# --- 3. DATA MANAGEMENT ---
def load_data(file):
    if os.path.exists(file):
        try:
            return pd.read_csv(file)
        except: return pd.DataFrame()
    return pd.DataFrame()

def save_manual_trade(ticker, price, rsi, hurst):
    df = load_data(DB_FILE)
    if df.empty:
        df = pd.DataFrame(columns=["Ticker", "Entry_Date", "Entry_Price", "RSI", "Hurst", "Status", "Current_Price", "PnL %"])
    
    today = datetime.now().strftime('%Y-%m-%d %H:%M')
    new_row = {
        "Ticker": ticker, "Entry_Date": today, "Entry_Price": round(price, 2), 
        "RSI": round(rsi, 1), "Hurst": round(hurst, 2),
        "Status": "OPEN", "Current_Price": round(price, 2), "PnL %": 0.0
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(DB_FILE, index=False)
    return True

def log_daily_opportunity(opp_list):
    today = datetime.now().strftime('%Y-%m-%d')
    opp_df = pd.DataFrame(opp_list)
    opp_df['Datum'] = today
    if os.path.exists(OPP_FILE):
        hist_df = load_data(OPP_FILE)
        if not hist_df.empty and today not in hist_df['Datum'].values:
            pd.concat([hist_df, opp_df], ignore_index=True).to_csv(OPP_FILE, index=False)
    else:
        opp_df.to_csv(OPP_FILE, index=False)

# --- 4. MAIN INTERFACE ---
st.title("🎯 Beul Quant-Station v5.0")
st.caption(f"Systeem Live | {datetime.now().strftime('%H:%M:%S')}")

tab1, tab2, tab3 = st.tabs(["🔭 Sniper Radar", "📜 Portfolio & Truth", "📊 Backtest & Simulation"])

with tab1:
    with st.spinner("Marktdata ophalen..."):
        raw_data = yf.download(TICKERS, period="1y", interval="1d", progress=False)
        # Fix: Gebruik 'Close' kolommen direct
        close_data = raw_data['Close']
    
    opp_list_today = []
    cols = st.columns(5)
    
    for i, ticker in enumerate(TICKERS):
        try:
            prices = close_data[ticker].dropna()
            if len(prices) < 30: continue
            
            curr_p, prev_p = float(prices.iloc[-1]), float(prices.iloc[-2])
            pnl_day = ((curr_p - prev_p) / prev_p) * 100
            h = get_hurst(prices.values)
            rsi = float(get_rsi(prices).iloc[-1])
            
            with cols[i % 5]:
                with st.container(border=True):
                    st.subheader(ticker)
                    st.metric("Prijs", f"${curr_p:.2f}", f"{pnl_day:.2f}%")
                    
                    h_color = "green" if h < 0.40 else "white"
                    r_color = "green" if rsi < 35 else "white"
                    st.markdown(f"Hurst: :{h_color}[{h:.2f}] | RSI: :{r_color}[{rsi:.1f}]")
                    
                    if st.button(f"Log {ticker}", key=f"log_{ticker}"):
                        save_manual_trade(ticker, curr_p, rsi, h)
                        st.toast(f"{ticker} gelogd!", icon="✅")
                    
                    if h < 0.40 and rsi < 35:
                        st.error("🔥 MEGA BUY ALERT")
            
            opp_list_today.append({"Ticker": ticker, "Hurst": h, "RSI": rsi, "Dag_PnL": pnl_day})
        except: continue

    if opp_list_today:
        log_daily_opportunity(opp_list_today)

with tab2:
    st.header("Open Posities")
    df_trades = load_data(DB_FILE)
    if not df_trades.empty:
        if st.button("🔄 Ververs Prijzen"):
            for idx, row in df_trades.iterrows():
                if row['Status'] == "OPEN":
                    lp = yf.Ticker(row['Ticker']).fast_info['last_price']
                    df_trades.at[idx, "Current_Price"] = round(lp, 2)
                    df_trades.at[idx, "PnL %"] = round(((lp - row['Entry_Price']) / row['Entry_Price']) * 100, 2)
            df_trades.to_csv(DB_FILE, index=False)
            st.rerun()
        st.dataframe(df_trades, use_container_width=True)
        
        sel_t = st.selectbox("Simulatie voor:", df_trades['Ticker'].unique())
        if sel_t:
            curr_val = df_trades[df_trades['Ticker'] == sel_t]['Current_Price'].iloc[-1]
            paths = monte_carlo_sim(curr_val)
            fig = go.Figure()
            for i in range(paths.shape[1]):
                fig.add_trace(go.Scatter(y=paths[:, i], mode='lines', line=dict(width=1), opacity=0.1, showlegend=False))
            fig.update_layout(title=f"21-Dagen Projectie: {sel_t}", template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Geen trades in portfolio.")

with tab3:
    st.header("📊 Historische Backtest Simulator")
    bt_ticker = st.selectbox("Kies aandeel:", TICKERS)
    
    if st.button(f"Start Backtest voor {bt_ticker}"):
        with st.spinner("Analyseer historisch rendement..."):
            # FIX: Squeeze zorgt dat data 1D wordt voor de DataFrame constructor
            df_bt = yf.download(bt_ticker, period="1y", interval="1d", progress=False)
            prices_bt = df_bt['Close'].squeeze()
            
            if prices_bt.empty:
                st.error("Geen data gevonden.")
            else:
                rsi_bt = get_rsi(prices_bt)
                hurst_bt = [get_hurst(prices_bt.iloc[max(0, i-30):i].values) for i in range(len(prices_bt))]
                
                # Zorg dat alle arrays even lang zijn
                results = pd.DataFrame({
                    "Close": prices_bt.values,
                    "RSI": rsi_bt.values,
                    "Hurst": hurst_bt
                }, index=prices_bt.index).dropna()
                
                balance = 1000.0
                shares = 0
                trade_log = []
                
                for i in range(len(results)-1):
                    # Sniper condities: RSI laag + Hurst laag (mean reverting)
                    if results['RSI'].iloc[i] < 35 and results['Hurst'].iloc[i] < 0.45 and shares == 0:
                        shares = balance / results['Close'].iloc[i]
                        balance = 0
                        trade_log.append(f"🔴 KOOP op {results.index[i].date()} voor ${results['Close'].iloc[i]:.2f}")
                    elif shares > 0 and (i % 10 == 0): # Verkoop elke 10e bar voor balans
                        balance = shares * results['Close'].iloc[i]
                        shares = 0
                        trade_log.append(f"🟢 VERKOOP op {results.index[i].date()} voor ${results['Close'].iloc[i]:.2f}")

                final_val = balance if shares == 0 else shares * prices_bt.iloc[-1]
                st.metric("Eindresultaat (1 jaar)", f"${final_val:.2f}", f"{((final_val-1000)/10):.2f}%")
                
                fig_bt = go.Figure()
                fig_bt.add_trace(go.Scatter(x=results.index, y=results['Close'], name="Prijs"))
                buys = results[(results['RSI'] < 35) & (results['Hurst'] < 0.45)]
                fig_bt.add_trace(go.Scatter(x=buys.index, y=buys['Close'], mode='markers', marker=dict(color='orange', size=10), name="Entry Point"))
                st.plotly_chart(fig_bt, use_container_width=True)
                
                with st.expander("Logs"):
                    for l in trade_log: st.write(l)
