import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import os
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. CONFIGURATIE ---
st.set_page_config(page_title="BEUL QUANT-STATION v3.5", layout="wide", page_icon="🎯")

# De lijst met aandelen die je wilt tracken
TICKERS = ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOGL", "META", "ASML.AS", "WMT", "BTC-USD"]
DB_FILE = "trade_history.csv"        
OPP_FILE = "opportunity_history.csv"  

# --- 2. CORE QUANT ENGINE ---
@st.cache_data(ttl=3600) # Voorkomt traagheid door data 1 uur te onthouden
def get_hurst(series):
    try:
        lags = range(2, 20)
        ts = np.log(series)
        tau = [np.sqrt(np.std(np.subtract(ts[lag:], ts[:-lag]))) for lag in lags]
        return np.polyfit(np.log(lags), np.log(tau), 1)[0] * 2.0
    except: return 0.5

def get_rsi(series, window=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def monte_carlo_sim(start_price, days=21, sims=50):
    returns = np.random.normal(0.0002, 0.02, (days, sims))
    price_paths = start_price * (1 + returns).cumprod(axis=0)
    return price_paths

# --- 3. DATA MANAGEMENT ---
def load_data(file):
    if os.path.exists(file):
        df = pd.read_csv(file)
        if 'PnL' in df.columns: df = df.rename(columns={'PnL': 'PnL %'})
        return df
    return pd.DataFrame()

def save_manual_trade(ticker, price, rsi, hurst):
    df = load_data(DB_FILE)
    if df.empty:
        df = pd.DataFrame(columns=["Ticker", "Entry_Date", "Entry_Price", "RSI", "Hurst", "Status", "Current_Price", "PnL %"])
    
    today = datetime.now().strftime('%Y-%m-%d')
    # Voorkom dubbel loggen op dezelfde dag
    if not ((df['Ticker'] == ticker) & (df['Entry_Date'] == today)).any():
        new_row = {
            "Ticker": ticker, "Entry_Date": today, "Entry_Price": round(price, 2), 
            "RSI": round(rsi, 1), "Hurst": round(hurst, 2),
            "Status": "OPEN", "Current_Price": round(price, 2), "PnL %": 0.0
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_csv(DB_FILE, index=False)
        return True
    return False

def log_daily_opportunity(opp_list):
    today = datetime.now().strftime('%Y-%m-%d')
    opp_df = pd.DataFrame(opp_list)
    opp_df['Datum'] = today
    if os.path.exists(OPP_FILE):
        hist_df = pd.read_csv(OPP_FILE)
        if today not in hist_df['Datum'].values:
            pd.concat([hist_df, opp_df], ignore_index=True).to_csv(OPP_FILE, index=False)
    else:
        opp_df.to_csv(OPP_FILE, index=False)

# --- 4. MAIN INTERFACE ---
st.title("🎯 Beul Quant-Station")
st.caption(f"Systeem Tijd: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Status: Live Markt-Scanner")

tab1, tab2, tab3 = st.tabs(["🔭 Sniper Radar", "📜 Portfolio & Truth", "📊 Backtest & Performance"])

with tab1:
    with st.spinner("Analyseer marktgegevens..."):
        # Bulk download voor snelheid
        raw_data = yf.download(TICKERS, period="1y", interval="1d", progress=False, auto_adjust=True)
        close_data = raw_data['Close']
        volume_data = raw_data['Volume']
    
    opp_list_today = []
    cols = st.columns(5)
    
    for i, ticker in enumerate(TICKERS):
        prices = close_data[ticker].dropna()
        volumes = volume_data[ticker].dropna()
        if len(prices) < 20: continue
        
        curr_p = float(prices.iloc[-1])
        prev_p = float(prices.iloc[-2])
        pnl_day = ((curr_p - prev_p) / prev_p) * 100
        
        h = get_hurst(prices.values)
        rsi = float(get_rsi(prices).iloc[-1])
        vol_ratio = volumes.iloc[-1] / volumes.rolling(window=20).mean().iloc[-1]
        
        with cols[i % 5]:
            with st.container(border=True):
                st.subheader(ticker)
                st.metric("Prijs", f"${curr_p:.2f}", f"{pnl_day:.2f}%")
                
                # Indicator Status Styling
                h_style = "green" if h < 0.40 else "white"
                r_style = "green" if rsi < 35 else ("red" if rsi > 65 else "white")
                
                st.markdown(f"**Hurst:** :{h_style}[{h:.2f}]")
                st.markdown(f"**RSI:** :{r_style}[{rsi:.1f}]")
                st.markdown(f"**Vol Ratio:** {'✅' if vol_ratio > 1.2 else '⚪'} ({vol_ratio:.1f}x)")
                
                # SNIPER LOGICA
                if h < 0.40 and rsi < 35:
                    st.error("🔥 MEGA BUY ALERT")
                    if st.button(f"Log {ticker}", key=f"log_{ticker}"):
                        if save_manual_trade(ticker, curr_p, rsi, h):
                            st.success("Gelogd!")
                elif h < 0.40 and rsi > 65:
                    st.warning("⚠️ SELL ALERT")

        opp_list_today.append({
            "Ticker": ticker, "Hurst": round(h, 2), "RSI": round(rsi, 1),
            "Vol_Ratio": round(vol_ratio, 2), "Dag_PnL": round(pnl_day, 2)
        })

    log_daily_opportunity(opp_list_today)

with tab2:
    st.header("Jouw Open Posities")
    df_trades = load_data(DB_FILE)
    
    if not df_trades.empty:
        if st.button("🔄 Update Live PnL"):
            for idx, row in df_trades.iterrows():
                if row['Status'] == "OPEN":
                    # Gebruik fast_info voor snelheid
                    info = yf.Ticker(row['Ticker']).fast_info
                    live_p = info['last_price']
                    df_trades.at[idx, "Current_Price"] = round(live_p, 2)
                    df_trades.at[idx, "PnL %"] = round(((live_p - row['Entry_Price']) / row['Entry_Price']) * 100, 2)
            df_trades.to_csv(DB_FILE, index=False)
            st.rerun()

        st.dataframe(df_trades.style.background_gradient(subset=['PnL %'], cmap='RdYlGn', vmin=-10, vmax=10), use_container_width=True)
        
        # Monte Carlo
        st.divider()
        st.subheader("Toekomst Voorspelling")
        sel_t = st.selectbox("Kies trade voor simulatie:", df_trades['Ticker'].unique())
        curr_val = df_trades[df_trades['Ticker'] == sel_t]['Current_Price'].iloc[-1]
        
        paths = monte_carlo_sim(curr_val)
        fig = go.Figure()
        for i in range(paths.shape[1]):
            fig.add_trace(go.Scatter(y=paths[:, i], mode='lines', line=dict(width=1), opacity=0.1, showlegend=False))
        fig.update_layout(title=f"21-Dagen Risico Waaier: {sel_t}", template="plotly_dark", xaxis_title="Dagen", yaxis_title="Prijs ($)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Logboek is leeg. Gebruik de Scanner om trades te schieten.")

with tab3:
    st.header("📊 Strategie Validatie")
    if os.path.exists(OPP_FILE):
        hist_df = pd.read_csv(OPP_FILE)
        hist_df['Virtueel_Resultaat'] = 1000 * (1 + (hist_df['Dag_PnL'] / 100))
        
        t_choice = st.selectbox("Bekijk geschiedenis voor:", TICKERS)
        t_data = hist_df[hist_df['Ticker'] == t_choice]
        
        st.line_chart(t_data.set_index('Datum')['Virtueel_Resultaat'])
        st.write(f"Dit overzicht laat zien wat er met €1000 gebeurt op basis van de dagelijkse beweging van {t_choice}.")
        
        st.subheader("Historisch Logboek")
        st.dataframe(hist_df.sort_values(by='Datum', ascending=False), use_container_width=True)
    else:
        st.warning("Nog geen historische data beschikbaar. Kom morgen terug voor de eerste analyse!")
