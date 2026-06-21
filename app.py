import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import time
import requests
import plotly.graph_objects as go
from supabase import create_client, Client

# ================= KİLİT EKRANI VE GÜVENLİK GİRİŞİ =================
def check_password():
    """Doğru şifre girilmeden hiçbir veritabanı veya borsa verisi yüklenmez."""
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    
    if st.session_state.password_correct:
        return True
        
    st.markdown("<h2 style='text-align: center; color: white; margin-top: 50px;'>🔒 DCA Terminal Güvenlik Girişi</h2>", unsafe_allow_html=True)
    col_login, _ = st.columns([1, 1.5])
    with col_login:
        user_password = st.text_input("Lütfen şahsi siber güvenlik şifrenizi girin:", type="password", key="login_pass_key_global")
        if st.button("Giriş Yap", key="login_btn_key_global"):
            if user_password == "dca2026": 
                st.session_state.password_correct = True
                st.rerun()
            else:
                st.error("❌ Hatalı Şifre! Erişim reddedildi.")
    return False

if not check_password():
    st.stop()  # Şifre yanlışsa kodun geri kalanının çalışmasını durdurur
# =========================================================================

# Streamlit sayfa yapılandırması - Geniş Ekran Modu Aktif
st.set_page_config(page_title="DCA Live Hedging Terminal", layout="wide")

# ================= FLICKER-FREE (KIPIRDAMASIZ) CSS ENJEKSİYONU =================
st.markdown(
    """
    <style>
    div[data-testid="stAppViewBlockContainer"] {
        opacity: 1.0 !important;
        transition: none !important;
    }
    div[data-testid="stStatusWidget"] {
        display: none !important;
        visibility: hidden !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Telegram ve Supabase Ayarları
telegram_token = "8736096328:AAH2_3BAIhbOxy9yo7v-L47h9KK3xCbALXE"
telegram_chat_id = "@kyounkripto"

supabase_url = "https://ahnwbxfghccotwnlhzgl.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFobndieGZnaGNjb3R3bmxoemdsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIwMTI3NzcsImV4cCI6MjA5NzU4ODc3N30.9cR5NBti19ddH7UivdcikYFoCRwk42mIkOkElYqT2Oc"

# Bulut veritabanı istemcisini başlatıyoruz
supabase: Client = create_client(supabase_url, supabase_key)
# ======================================================================================

# GATE.IO FUTURES BAĞLANTISI (Vadeli Modu Aktif)
exchange = ccxt.gate({
    'options': {
        'defaultType': 'swap',
    }
})

# ================= MATEMATİKSEL RSI HESAPLAMA ALGORİTMASI =================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

# ================= MATEMATİKSEL RSI IRAKSAMA TESPİT ALGORİTMASI =================
def detect_rsi_divergence(closes, rsis):
    if len(closes) < 15 or len(rsis) < 15:
        return False, False
        
    c_sub = closes[-15:]
    r_sub = rsis[-15:]
    
    # Yerel dipleri bul (Boğa Iraksaması)
    lows_idx = []
    for i in range(1, len(c_sub)-1):
        if c_sub[i] < c_sub[i-1] and c_sub[i] < c_sub[i+1]:
            lows_idx.append(i)
            
    bull_div = False
    if len(lows_idx) >= 2:
        i1, i2 = lows_idx[-2], lows_idx[-1]
        if c_sub[i2] < c_sub[i1] and r_sub[i2] > r_sub[i1]:
            if r_sub[i2] < 45:
                bull_div = True
                
    # Yerel tepeleri bul (Ayı Iraksaması)
    highs_idx = []
    for i in range(1, len(c_sub)-1):
        if c_sub[i] > c_sub[i-1] and c_sub[i] > c_sub[i+1]:
            highs_idx.append(i)
            
    bear_div = False
    if len(highs_idx) >= 2:
        i1, i2 = highs_idx[-2], highs_idx[-1]
        if c_sub[i2] > c_sub[i1] and r_sub[i2] < r_sub[i1]:
            if r_sub[i2] > 55:
                bear_div = True
                
    return bull_div, bear_div

# ================= GÖMÜLÜ CANLI FİYAT VE YÜZDELİKLİ TARAYICI =================
@st.cache_data(ttl=300)
def get_top_50_volume_coins():
    try:
        tickers = exchange.fetch_tickers()
        usd_tickers = []
        for symbol, ticker in tickers.items():
            if symbol.endswith(':USDT'):
                quote_vol = ticker.get('quoteVolume')
                if quote_vol is None:
                    base_vol = ticker.get('baseVolume') or 0.0
                    last_price = ticker.get('last') or ticker.get('close') or 0.0
                    quote_vol = base_vol * last_price
                
                if quote_vol is not None and quote_vol > 0:
                    usd_tickers.append({
                        'symbol': symbol, 
                        'volume': quote_vol, 
                        'price': ticker.get('last') or ticker.get('close') or 0.0, 
                        'change': ticker.get('percentage') or 0.0
                    })
        
        if len(usd_tickers) == 0:
            return [
                {'symbol': "BTC/USDT:USDT", 'display': "BTC/USDT ($64,222.00 | +0.00%)"},
                {'symbol': "ETH/USDT:USDT", 'display': "ETH/USDT ($3,500.00 | +0.00%)"}
            ]
            
        usd_tickers.sort(key=lambda x: x['volume'], reverse=True)
        top_50_data = []
        for item in usd_tickers[:50]:
            clean_sym = item['symbol'].split(":")[0]
            display_name = f"{clean_sym} (${item['price']:,.2f} | {item['change']:+.2f}%)"
            top_50_data.append({
                'symbol': item['symbol'],
                'display': display_name
            })
        return top_50_data
    except Exception as e:
        return [
            {'symbol': "BTC/USDT:USDT", 'display': "BTC/USDT ($64,222.00 | +0.00%)"},
            {'symbol': "ETH/USDT:USDT", 'display': "ETH/USDT ($3,500.00 | +0.00%)"}
        ]

# ================= EN EKSTREM FONLAMA ORANLARI VE EN ÇOK YÜKSELEN/DÜŞENLER GÜÇLÜ TARAYICI =================
@st.cache_data(ttl=300)
def get_market_movers_and_funding():
    try:
        tickers = exchange.fetch_tickers()
        movers = []
        funding_rates = []
        
        for symbol, ticker in tickers.items():
            if symbol.endswith(':USDT'):
                volume = ticker.get('quoteVolume')
                price = ticker.get('last') or ticker.get('close') or 0.0
                change = ticker.get('percentage') or 0.0
                
                if volume is None:
                    base_vol = ticker.get('baseVolume') or 0.0
                    volume = base_vol * price
                
                raw_info = ticker.get('info', {})
                funding_val = raw_info.get('funding_rate')
                fr_val = float(funding_val) * 100.0 if funding_val is not None else 0.0
                
                clean_sym = symbol.split(":")[0]
                
                if price > 0 and volume > 0:
                    movers.append({
                        'Coin': clean_sym,
                        'Fiyat (USDT)': price,
                        'Değişim (%)': change,
                        'Fonlama Oranı': fr_val
                    })
                    
                if funding_val is not None:
                    funding_rates.append({
                        'symbol': clean_sym,
                        'rate': fr_val
                    })
        
        if len(movers) == 0:
            return [], pd.DataFrame(), pd.DataFrame()
            
        funding_rates.sort(key=lambda x: abs(x['rate']), reverse=True)
        top_5_funding = funding_rates[:5]
        
        df_movers = pd.DataFrame(movers)
        df_gainers = df_movers.sort_values(by='Değişim (%)', ascending=False).head(5).copy()
        df_gainers['Değişim (%)'] = df_gainers['Değişim (%)'].apply(lambda x: f"+{x:.2f}%")
        df_gainers['Fonlama Oranı'] = df_gainers['Fonlama Oranı'].apply(lambda x: f"{x:+.4f}%")
        df_gainers['Fiyat (USDT)'] = df_gainers['Fiyat (USDT)'].apply(lambda x: f"${x:,.2f}")
        
        df_losers = df_movers.sort_values(by='Değişim (%)', ascending=True).head(5).copy()
        df_losers['Değişim (%)'] = df_losers['Değişim (%)'].apply(lambda x: f"{x:.2f}%")
        df_losers['Fonlama Oranı'] = df_losers['Fonlama Oranı'].apply(lambda x: f"{x:+.4f}%")
        df_losers['Fiyat (USDT)'] = df_losers['Fiyat (USDT)'].apply(lambda x: f"${x:,.2f}")
        
        return top_5_funding, df_gainers[['Coin', 'Fiyat (USDT)', 'Değişim (%)', 'Fonlama Oranı']], df_losers[['Coin', 'Fiyat (USDT)', 'Değişim (%)', 'Fonlama Oranı']]
    except Exception as e:
        return [], pd.DataFrame(), pd.DataFrame()

# ================= 3 GÜNLÜK SANAL LİKİDASYON HARİTASI HESAPLAMA =================
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
        
        long_liq_bins = {}
        short_liq_bins = {}
        
        for i in range(len(df_3d)):
            h = highs[i]
            l = lows[i]
            vol = volumes[i]
            
            for lev_mult in [0.99, 0.98, 0.96]:
                liq_p = l * lev_mult
                bin_p = round(liq_p / round_step) * round_step
                long_liq_bins[bin_p] = long_liq_bins.get(bin_p, 0.0) + vol
                
            for lev_mult in [1.01, 1.02, 1.04]:
                liq_p = h * lev_mult
                bin_p = round(liq_p / round_step) * round_step
                short_liq_bins[bin_p] = short_liq_bins.get(bin_p, 0.0) + vol
                
        sorted_long = sorted(long_liq_bins.items(), key=lambda x: x[1], reverse=True)[:3]
        sorted_short = sorted(short_liq_bins.items(), key=lambda x: x[1], reverse=True)[:3]
        
        sorted_long.sort(key=lambda x: x[0], reverse=True)
        sorted_short.sort(key=lambda x: x[0], reverse=False)
        
        long_pools = []
        for p, v in sorted_long:
            density = "🔴🔴🔴 YÜKSEK" if v > np.mean(volumes)*1.5 else "🔴🔴 ORTA"
            long_pools.append({"Likidasyon Fiyatı": f"${p:,.2f}", "Yoğunluk Derecesi": density})
            
        short_pools = []
        for p, v in sorted_short:
            density = "🟢🟢🟢 YÜKSEK" if v > np.mean(volumes)*1.5 else "🟢🟢 ORTA"
            short_pools.append({"Likidasyon Fiyatı": f"${p:,.2f}", "Yoğunluk Derecesi": density})
            
        return pd.DataFrame(long_pools), pd.DataFrame(short_pools)
    except:
        return pd.DataFrame(), pd.DataFrame()

# Veritabanını yormamak için toplu borsa analizi tek seferde çekilir
extreme_rates, df_gainers, df_losers = get_market_movers_and_funding()

# Canlı Fiyatlı ve Yüzdelikli 50 coini çekiyoruz
top_50_data = get_top_50_volume_coins()
display_options = [item['display'] for item in top_50_data]

# ================= YAN PANEL NAVİGASYON SEÇİMİ =================
st.sidebar.title("🧭 Terminal Navigasyon")
app_mode = st.sidebar.radio("Mod Seçin:", ["🖥️ Canlı DCA Terminal", "📊 Geriye Dönük Test (Backtest)"], key="global_app_mode_radio")

st.sidebar.markdown("---")
st.sidebar.title("💳 Cüzdan Durumu")
st.sidebar.write("Başlangıç Bakiyesi: 100.00 USD")

# COİN SEÇİM KUTUSU
selected_display = st.sidebar.selectbox("🔥 Vadeli Coin Seçin", display_options, key="sidebar_coin_selectbox_global")
selected_symbol = [item['symbol'] for item in top_50_data if item['display'] == selected_display][0]

# HATA GİDERİCİ: coin_title değişkeni küresel olarak tanımlandı
coin_title = selected_symbol.split(':')[0]
state_prefix = f"{selected_symbol}_"

# ================= VERİTABANINDAN DURUMU GERİ YÜKLEME (RESTORE) =================
try:
    db_query = supabase.table("bot_state").select("*").eq("coin_symbol", selected_symbol).execute()
    if db_query.data:
        db_data = db_query.data[0]
        st.session_state[f"{state_prefix}balance_usd"] = db_data["balance_usd"]
        st.session_state[f"{state_prefix}l_status"] = [db_data["l_status_0"], db_data["l_status_1"], db_data["l_status_2"]]
        st.session_state[f"{state_prefix}l_crypto"] = db_data["l_crypto"]
        st.session_state[f"{state_prefix}l_usd_spent"] = db_data["l_usd_spent"]
        st.session_state[f"{state_prefix}l_avg_price"] = db_data["l_avg_price"]
        st.session_state[f"{state_prefix}s_status"] = [db_data["s_status_0"], db_data["s_status_1"], db_data["s_status_2"]]
        st.session_state[f"{state_prefix}s_crypto"] = db_data["s_crypto"]
        st.session_state[f"{state_prefix}s_usd_spent"] = db_data["s_usd_spent"]
        st.session_state[f"{state_prefix}s_avg_price"] = db_data["s_avg_price"]
        st.session_state[f"{state_prefix}log_history"] = db_data["log_history"] or []
except:
    pass

if f"{state_prefix}balance_usd" not in st.session_state:
    st.session_state[f"{state_prefix}balance_usd"] = 100.0
    st.session_state[f"{state_prefix}initial_balance"] = 100.0
    st.session_state[f"{state_prefix}l_status"] = [False, False, False]
    st.session_state[f"{state_prefix}l_crypto"] = 0.0
    st.session_state[f"{state_prefix}l_usd_spent"] = 0.0
    st.session_state[f"{state_prefix}l_avg_price"] = 0.0
    st.session_state[f"{state_prefix}s_status"] = [False, False, False]
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
            "l_crypto": st.session_state[f"{state_prefix}l_crypto"],
            "l_usd_spent": st.session_state[f"{state_prefix}l_usd_spent"],
            "l_avg_price": st.session_state[f"{state_prefix}l_avg_price"],
            "s_status_0": st.session_state[f"{state_prefix}s_status"][0],
            "s_status_1": st.session_state[f"{state_prefix}s_status"][1],
            "s_status_2": st.session_state[f"{state_prefix}s_status"][2],
            "s_crypto": st.session_state[f"{state_prefix}s_crypto"],
            "s_usd_spent": st.session_state[f"{state_prefix}s_usd_spent"],
            "s_avg_price": st.session_state[f"{state_prefix}s_avg_price"],
            "log_history": st.session_state[f"{state_prefix}log_history"]
        }
        supabase.table("bot_state").upsert(data).execute()
    except Exception as e:
        st.sidebar.error(f"Veritabanı kaydı başarısız: {e}")

# ===============================================================================

try:
    ticker_info = exchange.fetch_ticker(selected_symbol)
    coin_price = ticker_info.get('last') or ticker_info.get('close') or 63000.0
    scale_factor = 63000.0 / coin_price
    layer_sizes = [0.0001 * scale_factor, 0.0002 * scale_factor, 0.0012 * scale_factor]
except:
    layer_sizes = [0.0001, 0.0002, 0.0012]

target_profit_ratio = 0.01
stop_loss_ratio = 0.02

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except:
        pass

# NON-REPAINTING NADARAYA-WATSON FİLTRESİ
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

# ================= ENTEGRE EDİLMİŞ ETKİLEŞİMLİ GÖSTERİM FONKSİYONU (PLOTLY) =================
def draw_plotly_chart(df_subset, price_col, alt_band_col, ust_band_col, title, l_avg=0.0, s_avg=0.0):
    fig = go.Figure()
    # Ana anlık fiyat çizgisi
    fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=df_subset[price_col], name="Anlık Fiyat", line=dict(color='royalblue', width=2)))
    # Üst direnç bandı
    fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=df_subset[ust_band_col], name="Üst Band (Satış)", line=dict(color='crimson', width=1.5, dash='dash')))
    # Alt destek bandı
    fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=df_subset[alt_band_col], name="Alt Band (Alış)", line=dict(color='limegreen', width=1.5, dash='dash')))
    
    # Ortalama pozisyon maliyet çizgileri
    if l_avg > 0:
        fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=[l_avg]*len(df_subset), name="Long Maliyet Ort.", line=dict(color='green', width=1.5)))
    if s_avg > 0:
        fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=[s_avg]*len(df_subset), name="Short Maliyet Ort.", line=dict(color='red', width=1.5)))
        
    fig.update_layout(
        title=title,
        template="plotly_dark",
        xaxis_title="Zaman",
        yaxis_title="Fiyat (USDT)",
        hovermode="x unified",  # İmlecin fiyata göre koordinatları canlı takip etmesini sağlar
        margin=dict(l=20, r=20, t=40, b=20),
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

# ================= MOD 1: GERİYE DÖNÜK TEST (BACKTEST) MODU =================
if app_mode == "📊 Geriye Dönük Test (Backtest)":
    st.title("📊 Geriye Dönük Test (Backtest) Masası")
    st.write("Bu modül, seçtiğiniz borsa çifti için geçmiş fiyat mumlarını çekerek 3 kademeli DCA nedensel (non-repainting) zarf stratejisini simüle eder.")
    
    col_bt1, col_bt2, col_bt3 = st.columns(3)
    bt_tf = col_bt1.selectbox("Test Zaman Dilimi", ["5m", "15m", "1h", "4h"], index=2, key="backtest_tf_selector_unique")
    bt_limit = col_bt2.number_input("Test Edilecek Mum Sayısı", min_value=100, max_value=3000, value=1000, step=100, key="backtest_limit_unique")
    bt_std = col_bt3.number_input("Nadaraya-Watson Std Sapma (Sapma Seviyesi)", min_value=1.5, max_value=4.0, value=3.0, step=0.1, key="backtest_std_input")
    
    col_bt4, col_bt5 = st.columns(2)
    bt_tp = col_bt4.slider("Hedef Kar-Al Oranı (%)", min_value=0.2, max_value=5.0, value=1.0, step=0.1, key="backtest_tp_slider") / 100.0
    bt_sl = col_bt5.slider("3. Kademe Stop-Loss Oranı (%)", min_value=0.5, max_value=10.0, value=2.0, step=0.1, key="backtest_sl_slider") / 100.0
    
    if st.button("▶️ Geriye Dönük Testi Çalıştır", key="backtest_run_button"):
        with st.spinner("Geçmiş veriler çekiliyor ve analiz ediliyor..."):
            try:
                bt_raw = exchange.fetch_ohlcv(selected_symbol, bt_tf, limit=int(bt_limit))
                df_bt = pd.DataFrame(bt_raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
                df_bt["Zaman"] = pd.to_datetime(df_bt["Zaman"], unit="ms")
                
                df_bt = calculate_nw_bands(df_bt, bt_std * 0.7, "_K1")
                df_bt = calculate_nw_bands(df_bt, bt_std * 0.85, "_K2")
                df_bt = calculate_nw_bands(df_bt, bt_std, "_K3")
                
                initial_balance = 1000.0
                balance = initial_balance
                
                l_status = [False, False, False]
                l_crypto = 0.0
                l_usd_spent = 0.0
                l_avg_price = 0.0
                
                equity_curve = []
                trade_logs = []
                
                for i, row in df_bt.iterrows():
                    close = row["Kapanis"]
                    t_time = row["Zaman"]
                    
                    if sum(l_status) > 0:
                        l_tp_target = l_avg_price * (1 + bt_tp)
                        if l_status[2]:
                            l_stop_target = df_bt.at[i, "NW_Alt_K3"] * (1 - bt_sl)
                            if close <= l_stop_target:
                                pnl_usd = (l_crypto * close) - l_usd_spent
                                balance += l_crypto * close
                                trade_logs.append({
                                    "Tür": "LONG STOP-LOSS", "Kapanış Zamanı": t_time, 
                                    "Giriş Fiyatı": l_avg_price, "Kapanış Fiyatı": close, 
                                    "Kar/Zarar ($)": pnl_usd, "Kalan Bakiye": balance
                                })
                                l_crypto, l_usd_spent, l_avg_price = 0.0, 0.0, 0.0
                                l_status = [False, False, False]
                        elif close >= l_tp_target:
                            pnl_usd = (l_crypto * close) - l_usd_spent
                            balance += l_crypto * close
                            trade_logs.append({
                                "Tür": "LONG KAR-AL", "Kapanış Zamanı": t_time, 
                                "Giriş Fiyatı": l_avg_price, "Kapanış Fiyatı": close, 
                                "Kar/Zarar ($)": pnl_usd, "Kalan Bakiye": balance
                            })
                            l_crypto, l_usd_spent, l_avg_price = 0.0, 0.0, 0.0
                            l_status = [False, False, False]
                            
                    if close <= row["NW_Alt_K1"] and not l_status[0]:
                        buy_usd = initial_balance * 0.05
                        if balance >= buy_usd:
                            balance -= buy_usd
                            l_crypto += buy_usd / close
                            l_usd_spent += buy_usd
                            l_status[0] = True
                            l_avg_price = l_usd_spent / l_crypto
                            
                    if close <= row["NW_Alt_K2"] and l_status[0] and not l_status[1]:
                        buy_usd = initial_balance * 0.10
                        if balance >= buy_usd:
                            balance -= buy_usd
                            l_crypto += buy_usd / close
                            l_usd_spent += buy_usd
                            l_status[1] = True
                            l_avg_price = l_usd_spent / l_crypto
                            
                    if close <= row["NW_Alt_K3"] and l_status[1] and not l_status[2]:
                        buy_usd = initial_balance * 0.25
                        if balance >= buy_usd:
                            balance -= buy_usd
                            l_crypto += buy_usd / close
                            l_usd_spent += buy_usd
                            l_status[2] = True
                            l_avg_price = l_usd_spent / l_crypto
                            
                    current_equity = balance + (l_crypto * close)
                    equity_curve.append(current_equity)
                    
                df_equity = pd.DataFrame({"Zaman": df_bt["Zaman"], "Bakiye": equity_curve})
                df_trades = pd.DataFrame(trade_logs)
                
                st.markdown("---")
                st.write("📈 **Simülasyon Sonuçları**")
                
                if not df_trades.empty:
                    win_trades = df_trades[df_trades["Kar/Zarar ($)"] > 0]
                    win_rate = (len(win_trades) / len(df_trades)) * 100.0
                    
                    col_r1, col_r2, col_r3, col_r4 = st.columns(4)
                    col_r1.metric("Başlangıç Bakiyesi", f"${initial_balance:,.2f}")
                    col_r2.metric("Son Bakiye", f"${balance + (l_crypto * close):,.2f}")
                    col_r3.metric("Win Rate (Kazanma Oranı)", f"%{win_rate:.1f}")
                    col_r4.metric("Toplam İşlem", f"{len(df_trades)}")
                    
                    fig_bt = go.Figure()
                    fig_bt.add_trace(go.Scatter(x=df_equity["Zaman"], y=df_equity["Bakiye"], name="Bakiye Gelişimi (Equity)", line=dict(color="gold", width=2.5)))
                    fig_bt.add_hline(y=initial_balance, line=dict(color="white", width=1, dash="dash"))
                    fig_bt.update_layout(
                        title="Bakiye Gelişim Grafiği (Equity Curve)",
                        template="plotly_dark",
                        xaxis_title="Zaman",
                        yaxis_title="Bakiye (USD)",
                        margin=dict(l=20, r=20, t=40, b=20),
                        height=400,
                        hovermode="x unified"
                    )
                    st.plotly_chart(fig_bt, use_container_width=True, key="backtest_plotly_equity_chart_unique")
                    
                    st.write("📜 **Gerçekleşen Geçmiş İşlem Detayları**")
                    st.dataframe(df_trades)
                else:
                    st.warning("Seçilen dönemde test kriterlerine uygun işlem gerçekleşmedi.")
                    
            except Exception as ex:
                st.error(f"Test sırasında hata meydana geldi: {ex}")

# ================= MOD 2: CANLI DCA TERMINAL MODU =================
elif app_mode == "🖥️ Canlı DCA Terminal":
    # Yan panel kilit kontrol butonları
    manual_lock = st.sidebar.toggle("🔒 Bekleyen Seviyeleri Dondur (El İle)", value=False, key="live_manual_lock_toggle")
    
    if st.sidebar.button("🔔 Telegram Bağlantısını Test Et", key="live_telegram_test_button_unique"):
        send_telegram_msg(f"👋 *Bağlantı Testi:* Web siteniz üzerinden gönderilen test mesajı başarılı!")
        st.sidebar.success("Test mesajı gönderildi!")

    if st.sidebar.button("🔴 Tüm Kademeleri Manuel Sıfırla", key="live_reset_all_positions_button"):
        st.session_state[f"{state_prefix}l_status"] = [False, False, False]
        st.session_state[f"{state_prefix}s_status"] = [False, False, False]
        st.session_state[f"{state_prefix}l_crypto"] = 0.0
        st.session_state[f"{state_prefix}l_usd_spent"] = 0.0
        st.session_state[f"{state_prefix}l_avg_price"] = 0.0
        st.session_state[f"{state_prefix}s_crypto"] = 0.0
        st.session_state[f"{state_prefix}s_usd_spent"] = 0.0
        st.session_state[f"{state_prefix}s_avg_price"] = 0.0
        st.session_state[f"{state_prefix}balance_usd"] = 100.0
        st.session_state[f"{state_prefix}locked_prices"] = None
        save_state_to_db()
        st.rerun()

    st.sidebar.write("🔄 Sonraki Tarama İlerlemesi:")
    countdown_placeholder = st.sidebar.empty()

    main_container = st.empty()

    # Orijinal kıpırdamasız ve kararmasız while True döngüsü geri yüklendi (st.rerun silindi)
    while True:
        try:
            # 1. ANLIK BORSA TICKER VERİSİ SORGULAMA
            live_ticker = exchange.fetch_ticker(selected_symbol)
            current_price = live_ticker.get('last') or live_ticker.get('close') or 0.0
            price_change_24h = live_ticker.get('percentage') or 0.0

            # 2. KÜRESEL 4H TREND HESAPLAMASI
            raw_4h = exchange.fetch_ohlcv(selected_symbol, "4h", limit=210)
            df_4h = pd.DataFrame(raw_4h, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            df_4h["EMA_200"] = df_4h["Kapanis"].ewm(span=200, adjust=False).mean()
            
            latest_4h_close = df_4h.iloc[-1]["Kapanis"]
            latest_4h_ema = df_4h.iloc[-1]["EMA_200"]
            trend_4h = "YUKARI (BOĞA)" if latest_4h_close > latest_4h_ema else "AŞAĞI (AYI)"
            warning_msg = "SHORT açarken DİKKATLİ olun!" if trend_4h == "YUKARI (BOĞA)" else "LONG açarken DİKKATLİ olun!"

            # 3. ANLIK VOLATİLİTE ÖLÇÜMÜ (Tansiyon Algoritması)
            raw_vol = exchange.fetch_ohlcv(selected_symbol, "15m", limit=120)
            df_vol = pd.DataFrame(raw_vol, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            df_vol["std"] = df_vol["Kapanis"].rolling(20).std()
            
            current_std = df_vol.iloc[-1]["std"]
            historical_median_std = df_vol["std"].median()
            
            is_volatile = current_std > historical_median_std
            market_state_label = "⚡ VOLATİL (Trend / Sert Hareket)" if is_volatile else "💤 SAKİN (Yatay Salınım)"

            # =================== 4. YENİ GELİŞMİŞ VERİ VE RESAMPLE YAPISI (TÜM ZAMAN DİLİMLERİ İÇİN) ===================
            # 1 Dakikalık veriler (Master veri)
            raw_candles = exchange.fetch_ohlcv(selected_symbol, "1m", limit=1000)
            df_1m = pd.DataFrame(raw_candles, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            df_1m["Zaman"] = pd.to_datetime(df_1m["Zaman"], unit="ms")
            df_1m = calculate_nw_bands(df_1m, 3.0, "_1m")
            df_1m["RSI"] = calculate_rsi(df_1m["Kapanis"])

            # 5 Dakikalık resample ve hesaplamalar
            df_5m = df_1m.resample('5min', on='Zaman').agg({'Acilis':'first', 'Yuksek':'max', 'Dusuk':'min', 'Kapanis':'last', 'Hacim':'sum'}).reset_index()
            df_5m = calculate_nw_bands(df_5m, 3.0, "_5m")
            df_5m["RSI"] = calculate_rsi(df_5m["Kapanis"])

            # 15 Dakikalık resample ve hesaplamalar
            df_15m = df_1m.resample('15min', on='Zaman').agg({'Acilis':'first', 'Yuksek':'max', 'Dusuk':'min', 'Kapanis':'last', 'Hacim':'sum'}).reset_index()
            df_15m = calculate_nw_bands(df_15m, 3.0, "_15m")
            df_15m["RSI"] = calculate_rsi(df_15m["Kapanis"])

            # 1 Saatlik resample ve hesaplamalar
            df_1h = df_1m.resample('60min', on='Zaman').agg({'Acilis':'first', 'Yuksek':'max', 'Dusuk':'min', 'Kapanis':'last', 'Hacim':'sum'}).reset_index()
            df_1h = calculate_nw_bands(df_1h, 3.0, "_1h")
            df_1h["RSI"] = calculate_rsi(df_1h["Kapanis"])

            # 4 Saatlik resample ve hesaplamalar
            df_4h = df_1m.resample('240min', on='Zaman').agg({'Acilis':'first', 'Yuksek':'max', 'Dusuk':'min', 'Kapanis':'last', 'Hacim':'sum'}).reset_index()
            df_4h = calculate_nw_bands(df_4h, 3.0, "_4h")
            df_4h["RSI"] = calculate_rsi(df_4h["Kapanis"])

            # 1 Günlük veriler
            raw_candles_1d = exchange.fetch_ohlcv(selected_symbol, "1d", limit=100)
            df_1d = pd.DataFrame(raw_candles_1d, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            df_1d["Zaman"] = pd.to_datetime(df_1d["Zaman"], unit="ms")
            df_1d = calculate_nw_bands(df_1d, 3.0, "_1d")

            df_long_liq, df_short_liq = estimate_liquidation_pools(selected_symbol)

            # Dinamik bandlar hangi sisteme göre seçilecek?
            if not is_volatile:
                dyn_alt_5m = df_1m.iloc[-1]["NW_Alt_1m"]
                dyn_alt_1h = df_5m.iloc[-1]["NW_Alt_5m"]
                dyn_alt_4h = df_15m.iloc[-1]["NW_Alt_15m"]
                dyn_ust_5m = df_1m.iloc[-1]["NW_Ust_1m"]
                dyn_ust_1h = df_5m.iloc[-1]["NW_Ust_5m"]
                dyn_ust_4h = df_15m.iloc[-1]["NW_Ust_15m"]
                l1_lbl, l2_lbl, l3_lbl = "Kademe 1 (1m)", "Kademe 2 (5m)", "Kademe 3 (15m)"
                s1_lbl, s2_lbl, s3_lbl = "Kademe 1 (1m)", "Kademe 2 (5m)", "Kademe 3 (15m)"
                active_engine_name = "⏱️ SİSTEM A: ULTRA HIZLI SCALP (1m/5m/15m)"
            else:
                dyn_alt_5m = df_5m.iloc[-1]["NW_Alt_5m"]
                dyn_alt_1h = df_1h.iloc[-1]["NW_Alt_1h"]
                dyn_alt_4h = df_4h.iloc[-1]["NW_Alt_4h"]
                dyn_ust_5m = df_5m.iloc[-1]["NW_Ust_5m"]
                dyn_ust_1h = df_1h.iloc[-1]["NW_Ust_1h"]
                dyn_ust_4h = df_4h.iloc[-1]["NW_Ust_4h"]
                l1_lbl, l2_lbl, l3_lbl = "Kademe 1 (5m)", "Kademe 2 (1h)", "Kademe 3 (4h)"
                s1_lbl, s2_lbl, s3_lbl = "Kademe 1 (5m)", "Kademe 2 (1h)", "Kademe 3 (4h)"
                active_engine_name = "🌎 SİSTEM B: MAKRO TREND (5m/1h/4h)"

            if manual_lock:
                if st.session_state[f"{state_prefix}locked_prices"] is None:
                    st.session_state[f"{state_prefix}locked_prices"] = {"nw_alt_5m": dyn_alt_5m, "nw_alt_1h": dyn_alt_1h, "nw_alt_4h": dyn_alt_4h, "nw_ust_5m": dyn_ust_5m, "nw_ust_1h": dyn_ust_1h, "nw_ust_4h": dyn_ust_4h}
                nw_alt_5m, nw_alt_1h, nw_alt_4h = st.session_state[f"{state_prefix}locked_prices"]["nw_alt_5m"], st.session_state[f"{state_prefix}locked_prices"]["nw_alt_1h"], st.session_state[f"{state_prefix}locked_prices"]["nw_alt_4h"]
                nw_ust_5m, nw_ust_1h, nw_ust_4h = st.session_state[f"{state_prefix}locked_prices"]["nw_ust_5m"], st.session_state[f"{state_prefix}locked_prices"]["nw_ust_1h"], st.session_state[f"{state_prefix}locked_prices"]["nw_ust_4h"]
            else:
                st.session_state[f"{state_prefix}locked_prices"] = None
                nw_alt_5m, nw_alt_1h, nw_alt_4h = dyn_alt_5m, dyn_alt_1h, dyn_alt_4h
                nw_ust_5m, nw_ust_1h, nw_ust_4h = dyn_ust_5m, dyn_ust_1h, dyn_ust_4h
            
            rsi_1m_val = df_1m.iloc[-1]["RSI"]
            rsi_5m_val = df_5m.iloc[-1]["RSI"]
            rsi_15m_val = df_15m.iloc[-1]["RSI"]
            rsi_1h_val = df_1h.iloc[-1]["RSI"]
            rsi_4h_val = df_4h.iloc[-1]["RSI"]
            rsi_1d_val = df_1d.iloc[-1]["RSI"]

            bull_div_5m, bear_div_5m = detect_rsi_divergence(df_5m["Kapanis"].values, df_5m["RSI"].values)
            bull_div_1h, bear_div_1h = detect_rsi_divergence(df_1h["Kapanis"].values, df_1h["RSI"].values)
            bull_div_4h, bear_div_4h = detect_rsi_divergence(df_4h_res["Kapanis"].values, df_4h_res["RSI_14_4h"].values) if "RSI_14_4h" in df_4h_res else (False, False)

            # LONG ÇIKIŞLARI
            if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                l_tp = st.session_state[f"{state_prefix}l_avg_price"] * (1 + target_profit_ratio)
                
                if st.session_state[f"{state_prefix}l_status"][2]:
                    l_stop = nw_alt_4h * (1 - stop_loss_ratio)
                    if current_price <= l_stop:
                        st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                        msg = f"🔴 *LONG STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f}"
                        send_telegram_msg(msg)
                        st.session_state[f"{state_prefix}log_history"].append(msg)
                        st.session_state[f"{state_prefix}l_crypto"], st.session_state[f"{state_prefix}l_usd_spent"], st.session_state[f"{state_prefix}l_avg_price"], st.session_state[f"{state_prefix}l_status"] = 0.0, 0.0, 0.0, [False, False, False]
                        save_state_to_db()

                elif current_price >= l_tp:
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                    msg = f"🟢 *LONG KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}l_crypto"], st.session_state[f"{state_prefix}l_usd_spent"], st.session_state[f"{state_prefix}l_avg_price"], st.session_state[f"{state_prefix}l_status"] = 0.0, 0.0, 0.0, [False, False, False]
                    save_state_to_db()

            # SHORT POZİSYON ÇIKIŞLARI
            if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                s_stop = st.session_state[f"{state_prefix}s_avg_price"] * (1 + stop_loss_ratio)
                s_tp = st.session_state[f"{state_prefix}s_avg_price"] * (1 - target_profit_ratio)

                if st.session_state[f"{state_prefix}s_status"][2] and current_price >= s_stop:
                    pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                    msg = f"🔴 *SHORT STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}s_crypto"], st.session_state[f"{state_prefix}s_usd_spent"], st.session_state[f"{state_prefix}s_avg_price"], st.session_state[f"{state_prefix}s_status"] = 0.0, 0.0, 0.0, [False, False, False]
                    save_state_to_db()

                elif current_price <= s_tp:
                    pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                    msg = f"🟢 *SHORT KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}s_crypto"], st.session_state[f"{state_prefix}s_usd_spent"], st.session_state[f"{state_prefix}s_avg_price"], st.session_state[f"{state_prefix}s_status"] = 0.0, 0.0, 0.0, [False, False, False]
                    save_state_to_db()

            # LONG GİRİŞLERİ
            for idx, th, val in zip([0, 1, 2], [nw_alt_5m, nw_alt_1h, nw_alt_4h], layer_sizes):
                if current_price <= th and (idx == 0 or st.session_state[f"{state_prefix}l_status"][idx-1]) and not st.session_state[f"{state_prefix}l_status"][idx]:
                    st.session_state[f"{state_prefix}balance_usd"] -= val * current_price
                    st.session_state[f"{state_prefix}l_crypto"] += val
                    st.session_state[f"{state_prefix}l_usd_spent"] += val * current_price
                    st.session_state[f"{state_prefix}l_status"][idx] = True
                    st.session_state[f"{state_prefix}l_avg_price"] = st.session_state[f"{state_prefix}l_usd_spent"] / st.session_state[f"{state_prefix}l_crypto"]
                    msg = f"📈 *LONG K{idx+1} SATIN ALINDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    save_state_to_db()

            # SHORT GİRİŞLERİ
            for idx, th, val in zip([0, 1, 2], [nw_ust_5m, nw_ust_1h, nw_ust_4h], layer_sizes):
                if current_price >= th and (idx == 0 or st.session_state[f"{state_prefix}s_status"][idx-1]) and not st.session_state[f"{state_prefix}s_status"][idx]:
                    st.session_state[f"{state_prefix}balance_usd"] -= val * current_price
                    st.session_state[f"{state_prefix}s_crypto"] += val
                    st.session_state[f"{state_prefix}s_usd_spent"] += val * current_price
                    st.session_state[f"{state_prefix}s_status"][idx] = True
                    st.session_state[f"{state_prefix}s_avg_price"] = st.session_state[f"{state_prefix}s_usd_spent"] / st.session_state[f"{state_prefix}s_crypto"]
                    msg = f"📈 *SHORT K{idx+1} AÇILDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    save_state_to_db()

            # ARAYÜZÜ DOĞRUDAN ÇİZİYORUZ
            with main_container.container():
                col_left, col_right = st.columns([1.6, 1])
                
                with col_left:
                    st.subheader("📈 Canlı Fiyat ve Nadaraya-Watson Zarf Grafikleri")
                    tab_1m, tab_5m, tab_15m, tab_1h, tab_4h, tab_1d = st.tabs(["⏱️ 1m", "⏱️ 5m", "⏱️ 15m", "⏱️ 1h", "⏱️ 4h", "🌎 1d"])
                    
                    # HATA GİDERİCİ: df_subset değişkenleri her sekmenin kendi verisini (df_1m, df_5m, df_15m, df_1h, df_4h) çizecek şekilde güncellendi (df NameError hatası giderildi)
                    with tab_1m:
                        df_subset = df_1m.tail(100)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1m", "NW_Ust_1m", f"{coin_title} - 1m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key="live_plotly_1m_uq")
                    with tab_5m:
                        df_subset = df_5m.tail(100)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_5m", "NW_Ust_5m", f"{coin_title} - 5m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key="live_plotly_5m_uq")
                    with tab_15m:
                        df_subset = df_15m.tail(100)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_15m", "NW_Ust_15m", f"{coin_title} - 15m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key="live_plotly_15m_uq")
                    with tab_1h:
                        df_subset = df_1h.tail(100)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1h", "NW_Ust_1h", f"{coin_title} - 1h Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key="live_plotly_1h_uq")
                    with tab_4h:
                        df_subset = df_4h.tail(100)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_4h", "NW_Ust_4h", f"{coin_title} - 4h Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key="live_plotly_4h_uq")
                    with tab_1d:
                        df_subset = df_1d.tail(30)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1d", "NW_Ust_1d", f"{coin_title} - 1d Grafik"), use_container_width=True, key="live_plotly_1d_uq")

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

            # Günlük Piyasa Liderleri (Yığılmayı önlemek için main_container içerisine alındı)
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

            # SIFIRLAMA BUTONU
            st.markdown("---")
            if st.button("🔴 Tüm Kademeleri Manuel Sıfırla", key="reset_all_positions_button"):
                st.session_state[f"{state_prefix}l_status"] = [False, False, False]
                st.session_state[f"{state_prefix}s_status"] = [False, False, False]
                st.session_state[f"{state_prefix}l_crypto"] = 0.0
                st.session_state[f"{state_prefix}l_usd_spent"] = 0.0
                st.session_state[f"{state_prefix}l_avg_price"] = 0.0
                st.session_state[f"{state_prefix}s_crypto"] = 0.0
                st.session_state[f"{state_prefix}s_usd_spent"] = 0.0
                st.session_state[f"{state_prefix}s_avg_price"] = 0.0
                st.session_state[f"{state_prefix}balance_usd"] = 100.0
                st.session_state[f"{state_prefix}locked_prices"] = None
                save_state_to_db()
                st.rerun()

        except Exception as e:
            st.sidebar.error(f"Hata oluştu, 5s sonra denenecek: {e}")
            time.sleep(5)  # Hata durumunda CPU yorulmasını önlemek için bekleme eklendi
            
        # ================= GERİ SAYIM SAYACI =================
        for remaining in range(10, 0, -1):
            countdown_placeholder.write(f"🔄 Sonraki taramaya: **{remaining}** saniye...")
            time.sleep(1)
        countdown_placeholder.write("🔄 Taranıyor...")
