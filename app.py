import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import time
import requests
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import plotly.graph_objects as go
from supabase import create_client, Client

# ================= EN BAŞTA BORSA NESNESİNİN TANIMLANMASI =================
exchange = ccxt.gate({'options': {'defaultType': 'swap'}})

# ================= KİLİT EKRANI VE GÜVENLİK GİRİŞİ =================
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct: return True
    st.markdown("<h2 style='text-align: center; color: white; margin-top: 50px;'>🔒 DCA Terminal Güvenlik Girişi</h2>", unsafe_allow_html=True)
    col_login, _ = st.columns([1, 1.5])
    with col_login:
        user_password = st.text_input("Lütfen şahsi siber güvenlik şifrenizi girin:", type="password", key="login_pass_key_global")
        if st.button("Giriş Yap", key="login_btn_key_global"):
            if user_password == "dca2026": 
                st.session_state.password_correct = True
                st.rerun()
            else: st.error("❌ Hatalı Şifre! Erişim reddedildi.")
    return False

if not check_password(): st.stop()

st.set_page_config(page_title="DCA Live Hedging Terminal", layout="wide")

# ================= GELİŞMİŞ KARARMA VE DALGALANMA ÖNLEYİCİ (FLICKER-FREE CSS) =================
st.markdown(
    """
    <style>
    div[data-testid="stAppViewBlockContainer"], 
    div[data-testid="stVerticalBlock"], 
    [data-testid="stMain"],
    .stApp {
        opacity: 1.0 !important;
        filter: none !important;
        transition: none !important;
    }
    .element-container, .stPlotlyChart, .stMarkdown {
        opacity: 1.0 !important;
        transition: none !important;
    }
    div[data-testid="stStatusWidget"], [data-testid="stStatusWidget"] {
        display: none !important;
        visibility: hidden !important;
    }
    </style>
    """, 
    unsafe_allow_html=True
)

plt.style.use('dark_background')

telegram_token = "8736096328:AAH2_3BAIhbOxy9yo7v-L47h9KK3xCbALXE"
telegram_chat_id = "@kyounkripto"
supabase_url = "https://ahnwbxfghccotwnlhzgl.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFobndieFfnaGNjb3R3bmxoemdsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIwMTI3NzcsImV4cCI6MjA5NzU4ODc3N30.9cR5NBti19ddH7UivdcikYFoCRwk42mIkOkElYqT2Oc"
supabase: Client = create_client(supabase_url, supabase_key)

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def detect_rsi_divergence(closes, rsis):
    if len(closes) < 15 or len(rsis) < 15: return False, False
    c, r = closes[-15:], rsis[-15:]
    lows = [i for i in range(1, len(c)-1) if c[i] < c[i-1] and c[i] < c[i+1]]
    bull = len(lows) >= 2 and c[lows[-1]] < c[lows[-2]] and r[lows[-1]] > r[lows[-2]] and r[lows[-1]] < 45
    highs = [i for i in range(1, len(c)-1) if c[i] > c[i-1] and c[i] > c[i+1]]
    bear = len(highs) >= 2 and c[highs[-1]] > c[highs[-2]] and r[highs[-1]] < r[highs[-2]] and r[highs[-1]] > 55
    return bull, bear

@st.cache_data(ttl=300)
def get_top_50_volume_coins():
    try:
        tickers = exchange.fetch_tickers()
        usd = []
        for sym, t in tickers.items():
            if sym.endswith(':USDT'):
                v = t.get('quoteVolume') or (t.get('baseVolume', 0.0) * (t.get('last') or t.get('close') or 0.0))
                if v > 0: usd.append({'symbol': sym, 'volume': v, 'price': t.get('last') or t.get('close') or 0.0, 'change': t.get('percentage') or 0.0})
        usd.sort(key=lambda x: x['volume'], reverse=True)
        return [{'symbol': x['symbol'], 'display': f"{x['symbol'].split(':')[0]} (${x['price']:,.2f} | {x['change']:+.2f}%)"} for x in usd[:50]]
    except:
        return [{'symbol': "BTC/USDT:USDT", 'display': "BTC/USDT ($64,222.00 | +0.00%)"}]

@st.cache_data(ttl=300)
def get_market_movers_and_funding():
    try:
        tickers = exchange.fetch_tickers()
        movers, funding = [], []
        for sym, t in tickers.items():
            if sym.endswith(':USDT'):
                p, c = t.get('last') or t.get('close') or 0.0, t.get('percentage') or 0.0
                fr = float(t.get('info', {}).get('funding_rate', 0.0)) * 100.0
                clean = sym.split(":")[0]
                if p > 0:
                    movers.append({'Coin': clean, 'Fiyat (USDT)': p, 'Değişim (%)': c, 'Fonlama Oranı': fr})
                    funding.append({'symbol': clean, 'rate': fr})
        funding.sort(key=lambda x: abs(x['rate']), reverse=True)
        df_m = pd.DataFrame(movers)
        df_g = df_m.sort_values(by='Değişim (%)', ascending=False).head(5).copy()
        df_g['Değişim (%)'] = df_g['Değişim (%)'].apply(lambda x: f"{x:+.2f}%")
        df_g['Fonlama Oranı'] = df_g['Fonlama Oranı'].apply(lambda x: f"{x:+.4f}%")
        df_g['Fiyat (USDT)'] = df_g['Fiyat (USDT)'].apply(lambda x: f"${x:,.2f}")
        df_l = df_m.sort_values(by='Değişim (%)', ascending=True).head(5).copy()
        df_l['Değişim (%)'] = df_l['Değişim (%)'].apply(lambda x: f"{x:.2f}%")
        df_l['Fonlama Oranı'] = df_l['Fonlama Oranı'].apply(lambda x: f"{x:+.4f}%")
        df_l['Fiyat (USDT)'] = df_l['Fiyat (USDT)'].apply(lambda x: f"${x:,.2f}")
        return funding[:10], df_g, df_l
    except:
        return [], pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=300)
def estimate_liquidation_pools(symbol):
    try:
        raw_3d = exchange.fetch_ohlcv(symbol, "1h", limit=72)
        df_3d = pd.DataFrame(raw_3d, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        highs = df_3d["Yuksek"].values
        lows = df_3d["Dusuk"].values
        volumes = df_3d["Hacim"].values
        current_p = df_3d.iloc[-1]["Kapanis"]
        round_step = 50.0 if current_p > 10000 else (1.0 if current_p > 100 else (0.1 if current_p > 1 else 0.01))
        long_l, short_l = {}, {}
        for i, row in df_3d.iterrows():
            for m in [0.99, 0.98, 0.96]:
                p = round((lows[i] * m) / round_step) * round_step
                long_l[p] = long_l.get(p, 0.0) + volumes[i]
            for m in [1.01, 1.02, 1.04]:
                p = round((highs[i] * m) / round_step) * round_step
                short_l[p] = short_l.get(p, 0.0) + volumes[i]
        sl, ss = sorted(long_l.items(), key=lambda x: x[1], reverse=True)[:3], sorted(short_l.items(), key=lambda x: x[1], reverse=True)[:3]
        sl.sort(key=lambda x: x[0], reverse=True)
        ss.sort(key=lambda x: x[0], reverse=False)
        return (
            pd.DataFrame([{"Likidasyon Fiyatı": f"${p:,.2f}", "Yoğunluk Derecesi": "🔴🔴🔴 YÜKSEK" if v > df_3d["Hacim"].mean()*1.5 else "🔴🔴 ORTA"} for p, v in sl]),
            pd.DataFrame([{"Likidasyon Fiyatı": f"${p:,.2f}", "Yoğunluk Derecesi": "🟢🟢🟢 YÜKSEK" if v > df_3d["Hacim"].mean()*1.5 else "🟢🟢 ORTA"} for p, v in ss])
        )
    except:
        return pd.DataFrame(), pd.DataFrame()

# Non-Repainting Nadaraya-Watson Filtresi ve Grafik Çizimi
def nadaraya_watson_estimator(src, h=8):
    n = len(src)
    estimates = np.zeros(n)
    for i in range(n):
        past_indices = np.arange(i + 1)
        weights = np.exp(-((past_indices - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src[:i+1] * weights) / np.sum(weights)
    return estimates

def calculate_nw_bands(df, std_multiplier, col_suffix):
    df["NW_Merkez"] = nadaraya_watson_estimator(df["Kapanis"].values, h=8)
    df["Fark"] = df["Kapanis"] - df["NW_Merkez"]
    df["Sapma_Std"] = df["Fark"].rolling(window=20).std()
    df[f"NW_Ust{col_suffix}"] = df["NW_Merkez"] + (std_multiplier * df["Sapma_Std"])
    df[f"NW_Alt{col_suffix}"] = df["NW_Merkez"] - (std_multiplier * df["Sapma_Std"])
    return df

# ================= PROFESYONEL BORSA-STİLİ GRAFİK ÇİZİCİ =================
def draw_plotly_chart(df_subset, price_col, alt_band_col, ust_band_col, title, l_avg=0.0, s_avg=0.0):
    fig = go.Figure()

    # --- Üst/Alt zarf bandı + kanal dolgusu (TradingView tarzı ince neon çizgiler) ---
    fig.add_trace(go.Scatter(
        x=df_subset["Zaman"], y=df_subset[alt_band_col], name="Alt Band (Alış)",
        line=dict(color='rgba(0, 230, 118, 0.85)', width=1.6, dash='dot'),
        showlegend=True
    ))
    fig.add_trace(go.Scatter(
        x=df_subset["Zaman"], y=df_subset[ust_band_col], name="Üst Band (Satış)",
        line=dict(color='rgba(255, 61, 87, 0.85)', width=1.6, dash='dot'),
        fill='tonexty', fillcolor='rgba(120, 130, 255, 0.045)',
        showlegend=True
    ))

    # --- Profesyonel mum grafiği (Binance/TradingView renk paleti, ince fitil çizgileri) ---
    fig.add_trace(go.Candlestick(
        x=df_subset["Zaman"],
        open=df_subset["Acilis"], high=df_subset["Yuksek"],
        low=df_subset["Dusuk"], close=df_subset[price_col],
        name="Fiyat (OHLC)",
        increasing=dict(line=dict(color='#0ECB81', width=1), fillcolor='#0ECB81'),
        decreasing=dict(line=dict(color='#F6465D', width=1), fillcolor='#F6465D'),
        whiskerwidth=0.4
    ))

    # --- Ortalama maliyet çizgileri ---
    if l_avg > 0:
        fig.add_trace(go.Scatter(
            x=df_subset["Zaman"], y=[l_avg]*len(df_subset), name="Long Maliyet Ort.",
            line=dict(color='#00E676', width=1.3, dash='longdash')
        ))
    if s_avg > 0:
        fig.add_trace(go.Scatter(
            x=df_subset["Zaman"], y=[s_avg]*len(df_subset), name="Short Maliyet Ort.",
            line=dict(color='#FF5252', width=1.3, dash='longdash')
        ))

    # --- Son fiyat için sağ kenarda etiketli referans çizgisi ---
    last_price = df_subset[price_col].iloc[-1]
    fig.add_hline(
        y=last_price, line=dict(color='rgba(255,255,255,0.35)', width=1, dash='dot'),
        annotation_text=f" {last_price:,.2f} ", annotation_position="right",
        annotation_font=dict(color='#0B0E11', size=11, family="Arial Black"),
        annotation_bgcolor='#F0B90B', annotation_borderpad=4
    )

    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", font=dict(size=15, color='#E8EAED', family="Arial"), x=0.01, xanchor='left'),
        template="plotly_dark",
        plot_bgcolor='#0B0E11',
        paper_bgcolor='#0B0E11',
        font=dict(color='#B7BDC6', family="Arial"),
        margin=dict(l=10, r=60, t=45, b=10),
        height=440,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        hoverlabel=dict(bgcolor='#1E2329', font_size=12, font_family="Arial", bordercolor='#2B3139'),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0.0,
            bgcolor='rgba(0,0,0,0)', font=dict(size=11, color='#B7BDC6')
        ),
        dragmode='pan'
    )

    fig.update_xaxes(
        showgrid=True, gridcolor='rgba(240, 185, 11, 0.06)', gridwidth=1,
        showline=True, linewidth=1, linecolor='#2B3139', mirror=True,
        rangeslider_visible=False, showspikes=True, spikecolor='#F0B90B',
        spikethickness=1, spikedash='dot', spikemode='across'
    )
    fig.update_yaxes(
        showgrid=True, gridcolor='rgba(240, 185, 11, 0.06)', gridwidth=1,
        showline=True, linewidth=1, linecolor='#2B3139', mirror=True,
        side='right', showspikes=True, spikecolor='#F0B90B',
        spikethickness=1, spikedash='dot'
    )

    return fig

# Global veriler
extreme_rates, df_gainers, df_losers = get_market_movers_and_funding()
top_50_data = get_top_50_volume_coins()

# ================= YAN PANEL AYARLARI VE NAVİGASYON =================
st.sidebar.title("💳 Cüzdan Durumu")
st.sidebar.write("Başlangıç Bakiyesi: 100.00 USD")

selected_display = st.sidebar.selectbox("🔥 Vadeli Coin Seçin", [x['display'] for x in top_50_data], key="sidebar_coin_selectbox_global")
selected_symbol = [x['symbol'] for x in top_50_data if x['display'] == selected_display][0]
coin_title = selected_symbol.split(':')[0]
state_prefix = f"{selected_symbol}_"

# ================= YAN PANEL FONLAMA ORANLARI YAZDIRMA =================
st.sidebar.markdown("---")
st.sidebar.subheader("💸 En Ekstrem Fonlama Oranları (Top 10)")
if extreme_rates:
    for item in extreme_rates:
        rate_str = f"{item['rate']:+.4f}%"
        if item['rate'] < 0:
            st.sidebar.markdown(f"**{item['symbol']}**: :green[{rate_str}]")
        else:
            st.sidebar.markdown(f"**{item['symbol']}**: :red[{rate_str}]")
else:
    st.sidebar.write("Fonlama oranları yükleniyor...")

# ================= DURUM (STATE) GÜVENLİ YÜKLEME =================
if f"{state_prefix}balance_usd" not in st.session_state:
    loaded_from_db = False
    try:
        db_query = supabase.table("bot_state").select("*").eq("coin_symbol", selected_symbol).order("id", descending=True).limit(1).execute()
        if db_query.data:
            db_data = db_query.data[0]
            st.session_state[f"{state_prefix}balance_usd"] = db_data.get("balance_usd", 100.0)
            st.session_state[f"{state_prefix}l_crypto"] = db_data.get("l_crypto", 0.0)
            st.session_state[f"{state_prefix}l_usd_spent"] = db_data.get("l_usd_spent", 0.0)
            st.session_state[f"{state_prefix}l_avg_price"] = db_data.get("l_avg_price", 0.0)
            st.session_state[f"{state_prefix}s_crypto"] = db_data.get("s_crypto", 0.0)
            st.session_state[f"{state_prefix}s_usd_spent"] = db_data.get("s_usd_spent", 0.0)
            st.session_state[f"{state_prefix}s_avg_price"] = db_data.get("s_avg_price", 0.0)
            st.session_state[f"{state_prefix}log_history"] = db_data.get("log_history") or []

            st.session_state[f"{state_prefix}l_status"] = [
                db_data.get("l_status_0", False),
                db_data.get("l_status_1", False),
                db_data.get("l_status_2", False)
            ]
            st.session_state[f"{state_prefix}s_status"] = [
                db_data.get("s_status_0", False),
                db_data.get("s_status_1", False),
                db_data.get("s_status_2", False)
            ]

            st.session_state[f"{state_prefix}l_entry_prices"] = [
                db_data.get("l_entry_0", 0.0) if "l_entry_0" in db_data else 0.0,
                db_data.get("l_entry_1", 0.0) if "l_entry_1" in db_data else 0.0,
                db_data.get("l_entry_2", 0.0) if "l_entry_2" in db_data else 0.0
            ]
            st.session_state[f"{state_prefix}s_entry_prices"] = [
                db_data.get("s_entry_0", 0.0) if "s_entry_0" in db_data else 0.0,
                db_data.get("s_entry_1", 0.0) if "s_entry_1" in db_data else 0.0,
                db_data.get("s_entry_2", 0.0) if "s_entry_2" in db_data else 0.0
            ]
            loaded_from_db = True
    except:
        pass

    if not loaded_from_db:
        st.session_state[f"{state_prefix}balance_usd"] = 100.0
        st.session_state[f"{state_prefix}l_status"] = [False, False, False]
        st.session_state[f"{state_prefix}s_status"] = [False, False, False]
        st.session_state[f"{state_prefix}l_entry_prices"] = [0.0, 0.0, 0.0]
        st.session_state[f"{state_prefix}s_entry_prices"] = [0.0, 0.0, 0.0]
        st.session_state[f"{state_prefix}l_crypto"] = 0.0
        st.session_state[f"{state_prefix}l_usd_spent"] = 0.0
        st.session_state[f"{state_prefix}l_avg_price"] = 0.0
        st.session_state[f"{state_prefix}s_crypto"] = 0.0
        st.session_state[f"{state_prefix}s_usd_spent"] = 0.0
        st.session_state[f"{state_prefix}s_avg_price"] = 0.0
        st.session_state[f"{state_prefix}log_history"] = []

if f"{state_prefix}locked_prices" not in st.session_state: 
    st.session_state[f"{state_prefix}locked_prices"] = None

def save_state_to_db():
    try:
        data = {
            "coin_symbol": selected_symbol, 
            "balance_usd": st.session_state[f"{state_prefix}balance_usd"],
            "l_status_0": st.session_state[f"{state_prefix}l_status"][0], 
            "l_status_1": st.session_state[f"{state_prefix}l_status"][1], 
            "l_status_2": st.session_state[f"{state_prefix}l_status"][2],
            "s_status_0": st.session_state[f"{state_prefix}s_status"][0], 
            "s_status_1": st.session_state[f"{state_prefix}s_status"][1], 
            "s_status_2": st.session_state[f"{state_prefix}s_status"][2],
            "l_entry_0": st.session_state[f"{state_prefix}l_entry_prices"][0],
            "l_entry_1": st.session_state[f"{state_prefix}l_entry_prices"][1],
            "l_entry_2": st.session_state[f"{state_prefix}l_entry_prices"][2],
            "s_entry_0": st.session_state[f"{state_prefix}s_entry_prices"][0],
            "s_entry_1": st.session_state[f"{state_prefix}s_entry_prices"][1],
            "s_entry_2": st.session_state[f"{state_prefix}s_entry_prices"][2],
            "l_crypto": st.session_state[f"{state_prefix}l_crypto"], 
            "l_usd_spent": st.session_state[f"{state_prefix}l_usd_spent"], 
            "l_avg_price": st.session_state[f"{state_prefix}l_avg_price"],
            "s_crypto": st.session_state[f"{state_prefix}s_crypto"], 
            "s_usd_spent": st.session_state[f"{state_prefix}s_usd_spent"], 
            "s_avg_price": st.session_state[f"{state_prefix}s_avg_price"],
            "log_history": st.session_state[f"{state_prefix}log_history"]
        }
        supabase.table("bot_state").upsert(data).execute()
    except Exception as e: st.error(f"Veritabanı kaydı başarısız: {type(e).__name__}: {str(e)[:200]}")

try:
    ticker_info = exchange.fetch_ticker(selected_symbol)
    coin_price = ticker_info.get('last') or ticker_info.get('close') or 63000.0
    scale = 63000.0 / coin_price
    layer_sizes = [0.0001 * scale, 0.0002 * scale, 0.0012 * scale]
except:
    layer_sizes = [0.0001, 0.0002, 0.0012]

target_profit_ratio, stop_loss_ratio = 0.01, 0.02
def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": message, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload)
    except: pass

# ================= MASAÜSTÜ CANLI DCA TERMINALİ =================
manual_lock = st.sidebar.toggle("🔒 Bekleyen Seviyeleri Dondur (El İle)", value=False, key="live_manual_lock_toggle")

if st.sidebar.button("🔔 Telegram Bağlantısını Test Et", key="live_telegram_test_button_unique"):
    send_telegram_msg(f"👋 *Bağlantı Testi:* Web siteniz üzerinden gönderilen test mesajı başarılı!")
    st.sidebar.success("Test mesajı gönderildi!")

if st.sidebar.button("🔴 Tüm Kademeleri Manuel Sıfırla", key="live_reset_all_positions_button"):
    st.session_state[f"{state_prefix}l_status"] = [False, False, False]
    st.session_state[f"{state_prefix}s_status"] = [False, False, False]
    st.session_state[f"{state_prefix}l_entry_prices"] = [0.0, 0.0, 0.0]
    st.session_state[f"{state_prefix}s_entry_prices"] = [0.0, 0.0, 0.0]
    st.session_state[f"{state_prefix}l_crypto"], st.session_state[f"{state_prefix}l_usd_spent"], st.session_state[f"{state_prefix}l_avg_price"] = 0.0, 0.0, 0.0
    st.session_state[f"{state_prefix}s_crypto"], st.session_state[f"{state_prefix}s_usd_spent"], st.session_state[f"{state_prefix}s_avg_price"] = 0.0, 0.0, 0.0
    st.session_state[f"{state_prefix}balance_usd"] = 100.0
    st.session_state[f"{state_prefix}locked_prices"] = None
    save_state_to_db()
    st.rerun()

st.sidebar.write("🔄 Sonraki Tarama İlerlemesi:")
countdown_placeholder = st.sidebar.empty()
main_container = st.empty()

@st.fragment(run_every="10s")
def live_dca_fragment():
    try:
        live_ticker = exchange.fetch_ticker(selected_symbol)
        current_price = live_ticker.get('last') or live_ticker.get('close') or 0.0
        price_change_24h = live_ticker.get('percentage') or 0.0

        raw_4h = exchange.fetch_ohlcv(selected_symbol, "4h", limit=120)
        df_4h_trend = pd.DataFrame(raw_4h, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_4h_trend["EMA_200"] = df_4h_trend["Kapanis"].ewm(span=200, adjust=False).mean()
        trend_4h = "YUKARI (BOĞA)" if df_4h_trend.iloc[-1]["Kapanis"] > df_4h_trend.iloc[-1]["EMA_200"] else "AŞAĞI (AYI)"
        warning_msg = "SHORT açarken DİKKATLİ olun!" if trend_4h == "YUKARI (BOĞA)" else "LONG açarken DİKKATLİ olun!"

        raw_vol = exchange.fetch_ohlcv(selected_symbol, "15m", limit=120)
        df_vol = pd.DataFrame(raw_vol, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        is_volatile = df_vol["Kapanis"].rolling(20).std().iloc[-1] > df_vol["Kapanis"].rolling(20).std().median()
        market_state_label = "⚡ VOLATİL (Trend / Sert Hareket)" if is_volatile else "💤 SAKİN (Yatay Salınım)"

        raw_1m = exchange.fetch_ohlcv(selected_symbol, "1m", limit=120)
        df_1m = pd.DataFrame(raw_1m, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_1m["Zaman"] = pd.to_datetime(df_1m["Zaman"], unit="ms")
        df_1m = calculate_nw_bands(df_1m, 3.0, "_1m")
        df_1m["RSI"] = calculate_rsi(df_1m["Kapanis"])

        raw_5m = exchange.fetch_ohlcv(selected_symbol, "5m", limit=120)
        df_5m = pd.DataFrame(raw_5m, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_5m["Zaman"] = pd.to_datetime(df_5m["Zaman"], unit="ms")
        df_5m = calculate_nw_bands(df_5m, 3.0, "_5m")
        df_5m["RSI"] = calculate_rsi(df_5m["Kapanis"])

        raw_15m = exchange.fetch_ohlcv(selected_symbol, "15m", limit=120)
        df_15m = pd.DataFrame(raw_15m, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_15m["Zaman"] = pd.to_datetime(df_15m["Zaman"], unit="ms")
        df_15m = calculate_nw_bands(df_15m, 3.0, "_15m")
        df_15m["RSI"] = calculate_rsi(df_15m["Kapanis"])

        raw_1h = exchange.fetch_ohlcv(selected_symbol, "1h", limit=120)
        df_1h = pd.DataFrame(raw_1h, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_1h["Zaman"] = pd.to_datetime(df_1h["Zaman"], unit="ms")
        df_1h = calculate_nw_bands(df_1h, 3.0, "_1h")
        df_1h["RSI"] = calculate_rsi(df_1h["Kapanis"])

        raw_4h = exchange.fetch_ohlcv(selected_symbol, "4h", limit=120)
        df_4h = pd.DataFrame(raw_4h, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_4h["Zaman"] = pd.to_datetime(df_4h["Zaman"], unit="ms")
        df_4h = calculate_nw_bands(df_4h, 3.0, "_4h")
        df_4h["RSI"] = calculate_rsi(df_4h["Kapanis"])

        raw_candles_1d = exchange.fetch_ohlcv(selected_symbol, "1d", limit=120)
        df_1d = pd.DataFrame(raw_candles_1d, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_1d["Zaman"] = pd.to_datetime(df_1d["Zaman"], unit="ms")
        df_1d = calculate_nw_bands(df_1d, 3.0, "_1d")
        df_1d["RSI"] = calculate_rsi(df_1d["Kapanis"])

        df_long_liq, df_short_liq = estimate_liquidation_pools(selected_symbol)
        extreme_rates, df_gainers, df_losers = get_market_movers_and_funding()

        raw_k1_alt = df_5m.iloc[-2]["NW_Alt_5m"]
        raw_k2_alt = df_1h.iloc[-2]["NW_Alt_1h"]
        raw_k3_alt = df_4h.iloc[-2]["NW_Alt_4h"]

        raw_k1_ust = df_5m.iloc[-2]["NW_Ust_5m"]
        raw_k2_ust = df_1h.iloc[-2]["NW_Ust_1h"]
        raw_k3_ust = df_4h.iloc[-2]["NW_Ust_4h"]

        k1_alt_base = raw_k1_alt
        k2_alt_base = min(raw_k2_alt, k1_alt_base * 0.997)
        k3_alt_base = min(raw_k3_alt, k2_alt_base * 0.997)

        k1_ust_base = raw_k1_ust
        k2_ust_base = max(raw_k2_ust, k1_ust_base * 1.003)
        k3_ust_base = max(raw_k3_ust, k2_ust_base * 1.003)

        nw_alt_5m = st.session_state[f"{state_prefix}l_entry_prices"][0] if st.session_state[f"{state_prefix}l_status"][0] else k1_alt_base
        nw_alt_1h = st.session_state[f"{state_prefix}l_entry_prices"][1] if st.session_state[f"{state_prefix}l_status"][1] else k2_alt_base
        nw_alt_4h = st.session_state[f"{state_prefix}l_entry_prices"][2] if st.session_state[f"{state_prefix}l_status"][2] else k3_alt_base

        nw_ust_5m = st.session_state[f"{state_prefix}s_entry_prices"][0] if st.session_state[f"{state_prefix}s_status"][0] else k1_ust_base
        nw_ust_1h = st.session_state[f"{state_prefix}s_entry_prices"][1] if st.session_state[f"{state_prefix}s_status"][1] else k2_ust_base
        nw_ust_4h = st.session_state[f"{state_prefix}s_entry_prices"][2] if st.session_state[f"{state_prefix}s_status"][2] else k3_ust_base

        l1_lbl, l2_lbl, l3_lbl = "Kademe 1 (5m)", "Kademe 2 (1h)", "Kademe 3 (4h)"
        s1_lbl, s2_lbl, s3_lbl = "Kademe 1 (5m)", "Kademe 2 (1h)", "Kademe 3 (4h)"
        active_engine_name = "⏱️ SABİT MOTOR (5m / 1h / 4h Hiyerarşisi)"

        if manual_lock:
            if st.session_state[f"{state_prefix}locked_prices"] is None:
                st.session_state[f"{state_prefix}locked_prices"] = {"nw_alt_5m": nw_alt_5m, "nw_alt_1h": nw_alt_1h, "nw_alt_4h": nw_alt_4h, "nw_ust_5m": nw_ust_5m, "nw_ust_1h": nw_ust_1h, "nw_ust_4h": nw_ust_4h}
            nw_alt_5m, nw_alt_1h, nw_alt_4h = st.session_state[f"{state_prefix}locked_prices"]["nw_alt_5m"], st.session_state[f"{state_prefix}locked_prices"]["nw_alt_1h"], st.session_state[f"{state_prefix}locked_prices"]["nw_alt_4h"]
            nw_ust_5m, nw_ust_1h, nw_ust_4h = st.session_state[f"{state_prefix}locked_prices"]["nw_ust_5m"], st.session_state[f"{state_prefix}locked_prices"]["nw_ust_1h"], st.session_state[f"{state_prefix}locked_prices"]["nw_ust_4h"]
        else:
            st.session_state[f"{state_prefix}locked_prices"] = None

        rsi_1m_val, rsi_5m_val, rsi_15m_val, rsi_1h_val, rsi_4h_val, rsi_1d_val = df_1m.iloc[-1]["RSI"], df_5m.iloc[-1]["RSI"], df_15m.iloc[-1]["RSI"], df_1h.iloc[-1]["RSI"], df_4h.iloc[-1]["RSI"], df_1d.iloc[-1]["RSI"]

        if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
            l_tp = st.session_state[f"{state_prefix}l_avg_price"] * (1 + target_profit_ratio)
            if st.session_state[f"{state_prefix}l_status"][2] and current_price <= (nw_alt_4h * (1 - stop_loss_ratio)):
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                msg = f"🔴 *LONG STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}l_crypto"], st.session_state[f"{state_prefix}l_usd_spent"], st.session_state[f"{state_prefix}l_avg_price"] = 0.0, 0.0, 0.0
                st.session_state[f"{state_prefix}l_status"] = [False, False, False]
                st.session_state[f"{state_prefix}l_entry_prices"] = [0.0, 0.0, 0.0]
                save_state_to_db()
            elif current_price >= l_tp:
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                msg = f"🟢 *LONG KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}l_crypto"], st.session_state[f"{state_prefix}l_usd_spent"], st.session_state[f"{state_prefix}l_avg_price"] = 0.0, 0.0, 0.0
                st.session_state[f"{state_prefix}l_status"] = [False, False, False]
                st.session_state[f"{state_prefix}l_entry_prices"] = [0.0, 0.0, 0.0]
                save_state_to_db()

        if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
            s_stop = st.session_state[f"{state_prefix}s_avg_price"] * (1 + stop_loss_ratio)
            s_tp = st.session_state[f"{state_prefix}s_avg_price"] * (1 - target_profit_ratio)
            if st.session_state[f"{state_prefix}s_status"][2] and current_price >= s_stop:
                pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                msg = f"🔴 *SHORT STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}s_crypto"], st.session_state[f"{state_prefix}s_usd_spent"], st.session_state[f"{state_prefix}s_avg_price"] = 0.0, 0.0, 0.0
                st.session_state[f"{state_prefix}s_status"] = [False, False, False]
                st.session_state[f"{state_prefix}s_entry_prices"] = [0.0, 0.0, 0.0]
                save_state_to_db()
            elif current_price <= s_tp:
                pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                msg = f"🟢 *SHORT KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}s_crypto"], st.session_state[f"{state_prefix}s_usd_spent"], st.session_state[f"{state_prefix}s_avg_price"] = 0.0, 0.0, 0.0
                st.session_state[f"{state_prefix}s_status"] = [False, False, False]
                st.session_state[f"{state_prefix}s_entry_prices"] = [0.0, 0.0, 0.0]
                save_state_to_db()

        for idx, th, val in zip([0, 1, 2], [nw_alt_5m, nw_alt_1h, nw_alt_4h], layer_sizes):
            if current_price <= th and (idx == 0 or st.session_state[f"{state_prefix}l_status"][idx-1]) and not st.session_state[f"{state_prefix}l_status"][idx]:
                st.session_state[f"{state_prefix}balance_usd"] -= val * current_price
                st.session_state[f"{state_prefix}l_crypto"] += val
                st.session_state[f"{state_prefix}l_usd_spent"] += val * current_price
                st.session_state[f"{state_prefix}l_status"][idx] = True
                st.session_state[f"{state_prefix}l_entry_prices"][idx] = current_price
                st.session_state[f"{state_prefix}l_avg_price"] = st.session_state[f"{state_prefix}l_usd_spent"] / st.session_state[f"{state_prefix}l_crypto"]
                msg = f"📈 *LONG K{idx+1} SATIN ALINDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                save_state_to_db()
                break

        for idx, th, val in zip([0, 1, 2], [nw_ust_5m, nw_ust_1h, nw_ust_4h], layer_sizes):
            if current_price >= th and (idx == 0 or st.session_state[f"{state_prefix}s_status"][idx-1]) and not st.session_state[f"{state_prefix}s_status"][idx]:
                st.session_state[f"{state_prefix}balance_usd"] -= val * current_price
                st.session_state[f"{state_prefix}s_crypto"] += val
                st.session_state[f"{state_prefix}s_usd_spent"] += val * current_price
                st.session_state[f"{state_prefix}s_status"][idx] = True
                st.session_state[f"{state_prefix}s_entry_prices"][idx] = current_price
                st.session_state[f"{state_prefix}s_avg_price"] = st.session_state[f"{state_prefix}s_usd_spent"] / st.session_state[f"{state_prefix}s_crypto"]
                msg = f"📈 *SHORT K{idx+1} AÇILDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                save_state_to_db()
                break

        col_left, col_right = st.columns([1.6, 1])
    
        with col_left:
            st.subheader("📈 Canlı Fiyat ve Nadaraya-Watson Zarf Grafikleri")
            tab_1m, tab_5m, tab_15m, tab_1h, tab_4h, tab_1d = st.tabs(["⏱️ 1m", "⏱️ 5m", "⏱️ 15m", "⏱️ 1h", "⏱️ 4h", "🌎 1d"])
        
            with tab_1m:
                df_subset = df_1m.tail(100)
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1m", "NW_Ust_1m", f"{coin_title} - 1m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key=f"{state_prefix}chart_1m")
            with tab_5m:
                df_subset = df_5m.tail(100)
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_5m", "NW_Ust_5m", f"{coin_title} - 5m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key=f"{state_prefix}chart_5m")
            with tab_15m:
                df_subset = df_15m.tail(100)
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_15m", "NW_Ust_15m", f"{coin_title} - 15m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key=f"{state_prefix}chart_15m")
            with tab_1h:
                df_subset = df_1h.tail(100)
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1h", "NW_Ust_1h", f"{coin_title} - 1h Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key=f"{state_prefix}chart_1h")
            with tab_4h:
                df_subset = df_4h.tail(100)
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_4h", "NW_Ust_4h", f"{coin_title} - 4h Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key=f"{state_prefix}chart_4h")
            with tab_1d:
                df_subset = df_1d.tail(30)
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1d", "NW_Ust_1d", f"{coin_title} - 1d Grafik"), use_container_width=True, key=f"{state_prefix}chart_1d")

            st.markdown("---")
            st.write("🎯 **Canlı Sinyal DCA Yönetim Kartı**")
            col_l, col_s = st.columns(2)
            with col_l:
                st.info("📈 LONG KADEMELERİ")
                k1_status = f"✅ Alındı ({st.session_state[f'{state_prefix}l_avg_price']:.2f})" if st.session_state[f"{state_prefix}l_status"][0] else f"⏳ Bekliyor ({nw_alt_5m:.2f})"
                k2_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][1] else f"⏳ Bekliyor ({nw_alt_1h:.2f})"
                k3_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][2] else f"⏳ Bekliyor ({nw_alt_4h:.2f})"
                st.write(f"**{l1_lbl}:** {k1_status}"); st.write(f"**{l2_lbl}:** {k2_status}"); st.write(f"**{l3_lbl}:** {k3_status}")
                if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                    st.success(f"🟢 **KAR-AL (%1):** `{st.session_state[f'{state_prefix}l_avg_price'] * 1.01:.2f}`")

            with col_s:
                st.error("📉 SHORT KADEMELERİ")
                s_k1_status = f"✅ Açıldı ({st.session_state[f'{state_prefix}s_avg_price']:.2f})" if st.session_state[f"{state_prefix}s_status"][0] else f"⏳ Bekliyor ({nw_ust_5m:.2f})"
                s_k2_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][1] else f"⏳ Bekliyor ({nw_ust_1h:.2f})"
                s_k3_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][2] else f"⏳ Bekliyor ({nw_ust_4h:.2f})"
                st.write(f"**{s1_lbl}:** {s_k1_status}"); st.write(f"**{s2_lbl}:** {s_k2_status}"); st.write(f"**{s3_lbl}:** {s_k3_status}")
                if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                    st.success(f"🟢 **KAR-AL (%1):** `{st.session_state[f'{state_prefix}s_avg_price'] * 0.99:.2f}`")

            st.markdown("---")
            st.subheader(f"🎯 3 Günlük {selected_symbol.split('/')[0]} Tahmini Likidasyon Yoğunluk Haritası")
            col_liq_l, col_liq_s = st.columns(2)
            with col_liq_l:
                st.info("🔴 LONG LİKİDASYON HAVUZLARI")
                if not df_long_liq.empty: st.table(df_long_liq.reset_index(drop=True))
            with col_liq_s:
                st.error("🟢 SHORT LİKİDASYON HAVUZLARI")
                if not df_short_liq.empty: st.table(df_short_liq.reset_index(drop=True))

        with col_right:
            st.subheader(f"📊 {coin_title} Canlı Terminal")
            st.caption(f"🕒 Son veri güncellemesi: {time.strftime('%H:%M:%S')}")
            col_live_p, col_live_c = st.columns(2)
            col_live_p.metric(label="Anlık Fiyat (USDT)", value=f"${current_price:,.2f}")
            col_live_c.metric(label="24 Saatlik Değişim", value=f"{price_change_24h:+.2f}%")

            if manual_lock:
                st.warning("🔒 SEVİYELER DONDURULDU: Kademeler el ile kilitlendi.")
            else:
                st.success("🔓 CANLI TAKİP AKTİF: Seviyeler anlık güncelleniyor.")

            st.write(f"Mevcut Durum: **{market_state_label}**")
            st.write(f"Aktif Motor  : **{active_engine_name}**")
        
            st.markdown("---")
            col_t1, col_t2 = st.columns([1, 1.2])
            col_t1.metric(label="4h Genel Trend", value=trend_4h)
            if trend_4h == "YUKARI (BOĞA)": st.success(f"🛡️ Emniyet: {warning_msg}")
            else: st.error(f"🛡️ Emniyet: {warning_msg}")
        
            st.markdown("---")
            st.write("⚡ **RSI & Momentum Süzgeci (Tüm Zaman Dilimleri)**")
            col_rsi_a, col_rsi_b, col_rsi_c = st.columns(3)
            with col_rsi_a:
                st.write("**1m (Skalp)**"); st.code(f"{rsi_1m_val:.1f}")
                st.write("**1h (Orta)**"); st.code(f"{rsi_1h_val:.1f}")
            with col_rsi_b:
                st.write("**5m (Hızlı)**"); st.code(f"{rsi_5m_val:.1f}")
                st.write("**4h (Makro)**"); st.code(f"{rsi_4h_val:.1f}")
            with col_rsi_c:
                st.write("**15m (Normal)**"); st.code(f"{rsi_15m_val:.1f}")
                st.write("**1d (Ana Trend)**"); st.code(f"{rsi_1d_val:.1f}")

        st.markdown("---")
        st.subheader("🌎 Günlük Piyasa Liderleri (Top 5 Yükselen & Düşen)")
        col_g, col_lo = st.columns(2)
        with col_g:
            st.success("📈 EN ÇOK YÜKSELENLER")
            if not df_gainers.empty: st.table(df_gainers.reset_index(drop=True))
        with col_lo:
            st.error("📉 EN ÇOK DÜŞENLER")
            if not df_losers.empty: st.table(df_losers.reset_index(drop=True))

        st.markdown("---")
        if st.session_state[f"{state_prefix}log_history"]:
            st.write("📜 **Son Sinyaller (Log)**")
            for log in reversed(st.session_state[f"{state_prefix}log_history"][-3:]): st.write(log)

    except Exception as e:
        st.error(f"Hata oluştu, 10s sonra tekrar denenecek: {type(e).__name__}: {str(e)[:200]}")
        time.sleep(5)

@st.fragment(run_every="1s")
def countdown_fragment():
    if "scan_start_time" not in st.session_state:
        st.session_state.scan_start_time = time.time()
    elapsed = time.time() - st.session_state.scan_start_time
    remaining = max(0, 10 - int(elapsed))
    if remaining > 0:
        st.write(f"🔄 Sonraki taramaya: **{remaining}** saniye...")
    else:
        st.write("🔄 Taranıyor...")
        st.session_state.scan_start_time = time.time()

live_dca_fragment()
with st.sidebar:
    countdown_fragment()
