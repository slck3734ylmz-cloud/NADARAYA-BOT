import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import time
import requests
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
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
        user_password = st.text_input("Lütfen şahsi siber güvenlik şifrenizi girin:", type="password")
        if st.button("Giriş Yap"):
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

# Grafikleri küresel olarak karanlık temaya (Dark Mode) ayarlıyoruz
plt.style.use('dark_background')

# ================= ENTEGRE EDİLMİŞ TELEGRAM VE VERİTABANI AYARLARINIZ =================
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
                # 1. Hacim ve Değişim Verisi
                volume = ticker.get('quoteVolume')
                price = ticker.get('last') or ticker.get('close') or 0.0
                change = ticker.get('percentage') or 0.0
                
                if volume is None:
                    base_vol = ticker.get('baseVolume') or 0.0
                    volume = base_vol * price
                
                # 2. Fonlama Oranı Verisi
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
            
        # En Ekstrem 5 Fonlama Oranı
        funding_rates.sort(key=lambda x: abs(x['rate']), reverse=True)
        top_5_funding = funding_rates[:5]
        
        # En Çok Yükselenler (Top 5 Gainers)
        df_movers = pd.DataFrame(movers)
        df_gainers = df_movers.sort_values(by='Değişim (%)', ascending=False).head(5).copy()
        df_gainers['Değişim (%)'] = df_gainers['Değişim (%)'].apply(lambda x: f"+{x:.2f}%")
        df_gainers['Fonlama Oranı'] = df_gainers['Fonlama Oranı'].apply(lambda x: f"{x:+.4f}%")
        df_gainers['Fiyat (USDT)'] = df_gainers['Fiyat (USDT)'].apply(lambda x: f"${x:,.2f}")
        
        # En Çok Düşenler (Top 5 Losers)
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
        
        # LONG ve SHORT için fiyata en yakın olana göre sıralama optimizasyonu
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

# Streamlit Yan Panel (Sidebar) Tasarımı
st.sidebar.title("💳 Cüzdan Durumu")
st.sidebar.write("Başlangıç Bakiyesi: 100.00 USD")

# COİN SEÇİM KUTUSU
selected_display = st.sidebar.selectbox("🔥 Vadeli Coin Seçin (Hacim Sıralı 50)", display_options)
selected_symbol = [item['symbol'] for item in top_50_data if item['display'] == selected_display][0]

# ================= SOL PANEL (SIDEBAR) FONLAMA ORANLARI YAZDIRMA =================
st.sidebar.markdown("---")
st.sidebar.subheader("💸 En Ekstrem Fonlama Oranları (Top 5)")
extreme_rates_sb = get_extreme_funding_rates()
if extreme_rates_sb:
    for item in extreme_rates_sb:
        rate_str = f"{item['rate']:+.4f}%"
        if item['rate'] < 0:
            st.sidebar.markdown(f"**{item['symbol']}**: :green[{rate_str}]")
        else:
            st.sidebar.markdown(f"**{item['symbol']}**: :red[{rate_str}]")
else:
    st.sidebar.write("Fonlama oranları yükleniyor...")
st.sidebar.markdown("---")

# GERİ SAYIM SAYACI ALANI
st.sidebar.write("🔄 Sonraki Tarama İlerlemesi:")
countdown_placeholder = st.sidebar.progress(0)

# ================= VERİTABANINDAN DURUMU GERİ YÜKLEME (RESTORE) =================
state_prefix = f"{selected_symbol}_"

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

# Seçilen coinin fiyatına göre kademe adetlerini dinamik ölçeklendiriyoruz
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

# TELEGRAM BAĞLANTI TESTİ BUTONU
if st.sidebar.button("🔔 Telegram Bağlantısını Test Et"):
    send_telegram_msg(f"👋 *Bağlantı Testi:* Web siteniz üzerinden gönderilen test mesajı başarılı!")
    st.sidebar.success("Test mesajı gönderildi!")

def nadaraya_watson_estimator(src, h=8):
    n = len(src)
    estimates = np.zeros(n)
    for i in range(n):
        weights = np.exp(-((np.arange(n) - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src * weights) / np.sum(weights)
    return estimates

def calculate_nw_bands(df, std_multiplier, col_suffix):
    df["NW_Merkez"] = nadaraya_watson_estimator(df["Kapanis"].values, h=8)
    df["Fark"] = df["Kapanis"] - df["NW_Merkez"]
    df["Sapma_Std"] = df["Fark"].rolling(window=20).std()
    df[f"NW_Ust{col_suffix}"] = df["NW_Merkez"] + (std_multiplier * df["Sapma_Std"])
    df[f"NW_Alt{col_suffix}"] = df["NW_Merkez"] - (std_multiplier * df["Sapma_Std"])
    return df

# Ekran Güncelleme Alanı (Grid Layout için Boşluklar)
main_container = st.empty()

# Canlı Taramayı Başlat
while True:
    try:
        # =================== 1. HATA GEÇİRMEZ KÜRESEL 4H TREND HESAPLAMASI (HER İKİ MOD İÇİN ORTAK) ===================
        raw_4h = exchange.fetch_ohlcv(selected_symbol, "4h", limit=210)
        df_4h = pd.DataFrame(raw_4h, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_4h["EMA_200"] = df_4h["Kapanis"].ewm(span=200, adjust=False).mean()
        
        latest_4h_close = df_4h.iloc[-1]["Kapanis"]
        latest_4h_ema = df_4h.iloc[-1]["EMA_200"]
        trend_4h = "YUKARI (BOĞA)" if latest_4h_close > latest_4h_ema else "AŞAĞI (AYI)"
        warning_msg = "SHORT açarken DİKKATLİ olun!" if trend_4h == "YUKARI (BOĞA)" else "LONG açarken DİKKATLİ olun!"

        # 2. ANLIK VOLATİLİTE ÖLÇÜMÜ (Tansiyon Algoritması)
        raw_vol = exchange.fetch_ohlcv(selected_symbol, "15m", limit=120)
        df_vol = pd.DataFrame(raw_vol, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_vol["std"] = df_vol["Kapanis"].rolling(20).std()
        
        current_std = df_vol.iloc[-1]["std"]
        historical_median_std = df_vol["std"].median()
        
        # Piyasa Durumu Kararı
        is_volatile = current_std > historical_median_std
        market_state_label = "⚡ VOLATİL (Trend / Sert Hareket)" if is_volatile else "💤 SAKİN (Yatay Salınım)"

        # 3. SEÇİLEN KODA GÖRE CANLI VERİLERİ VE RESAMPLE DİLİMLERİNİ HESAPLA
        if not is_volatile:
            # SAKİN PİYASA (Sistem A: 1m / 5m / 15m) -> 1m master veri çekilir
            raw_candles = exchange.fetch_ohlcv(selected_symbol, "1m", limit=1000)
            df = pd.DataFrame(raw_candles, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
            
            # K1 (1m), K2 (5m), K3 (15m) NW Hesaplamaları (Birebir 3.0 Std)
            df = calculate_nw_bands(df, 3.0, "_5m") # 1m master olduğu için sütun adları uyumluluğu
            df_1h = df.resample("5min", on="Zaman").last().ffill().reset_index()
            df_1h = calculate_nw_bands(df_1h, 3.0, "_1h")
            df = pd.merge_asof(df.sort_values("Zaman"), df_1h[["Zaman", "NW_Ust_1h", "NW_Alt_1h"]].sort_values("Zaman"), on="Zaman", direction="backward")
            
            df_4h_res = df.resample("15min", on="Zaman").last().ffill().reset_index()
            df_4h_res = calculate_nw_bands(df_4h_res, 3.0, "_4h")
            df = pd.merge_asof(df.sort_values("Zaman"), df_4h_res[["Zaman", "NW_Ust_4h", "NW_Alt_4h"]].sort_values("Zaman"), on="Zaman", direction="backward")
            
            # 1d yedek hesaplama
            raw_candles_1d = exchange.fetch_ohlcv(selected_symbol, "1d", limit=100)
            df_1d = pd.DataFrame(raw_candles_1d, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            df_1d["Zaman"] = pd.to_datetime(df_1d["Zaman"], unit="ms")
            df_1d = calculate_nw_bands(df_1d, 3.0, "_1d")
            
            # Dinamik Kriter İsimleri
            l1_lbl, l2_lbl, l3_lbl = "Kademe 1 (1m)", "Kademe 2 (5m)", "Kademe 3 (15m)"
            s1_lbl, s2_lbl, s3_lbl = "Kademe 1 (1m)", "Kademe 2 (5m)", "Kademe 3 (15m)"
            active_engine_name = "⏱️ SİSTEM A: ULTRA HIZLI SCALP (1m/5m/15m)"
        else:
            # VOLATİL PİYASA (Sistem B: 5m / 1h / 4h) -> 5m master veri çekilir
            raw_candles = exchange.fetch_ohlcv(selected_symbol, "5m", limit=1000)
            df = pd.DataFrame(raw_candles, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
            
            # K1 (5m), K2 (1h), K3 (4h) NW ve RSI Hesaplamaları
            df = calculate_nw_bands(df, 3.0, "_5m")
            delta = df["Kapanis"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            df["RSI_14"] = 100 - (100 / (1 + rs))

            df_1h = df.resample("60min", on="Zaman").last().ffill().reset_index()
            df_1h = calculate_nw_bands(df_1h, 3.0, "_1h")
            diff_1h = df_1h["Kapanis"].diff()
            up_1h = diff_1h.clip(lower=0)
            down_1h = -diff_1h.clip(upper=0)
            ma_up_1h = up_1h.rolling(14).mean()
            ma_down_1h = down_1h.rolling(14).mean()
            rs_1h = ma_up_1h / ma_down_1h
            df_1h["RSI_14_1h"] = 100 - (100 / (1 + rs_1h))
            df = pd.merge_asof(df.sort_values("Zaman"), df_1h[["Zaman", "NW_Ust_1h", "NW_Alt_1h", "RSI_14_1h"]].sort_values("Zaman"), on="Zaman", direction="backward")

            df_4h_res = df.resample("240min", on="Zaman").last().ffill().reset_index()
            df_4h_res = calculate_nw_bands(df_4h_res, 3.0, "_4h")
            diff_4h = df_4h_res["Kapanis"].diff()
            up_4h = diff_4h.clip(lower=0)
            # BUG FIX: 4h RSI matematiksel sapması giderildi (.clip eklendi)
            down_4h = -diff_4h.clip(upper=0)
            ma_up_4h = up_4h.rolling(14).mean()
            ma_down_4h = down_4h.rolling(14).mean()
            rs_4h = ma_up_4h / ma_down_4h
            df_4h_res["RSI_14_4h"] = 100 - (100 / (1 + rs_4h))
            df = pd.merge_asof(df.sort_values("Zaman"), df_4h_res[["Zaman", "NW_Ust_4h", "NW_Alt_4h", "RSI_14_4h"]].sort_values("Zaman"), on="Zaman", direction="backward")

            raw_candles_1d = exchange.fetch_ohlcv(selected_symbol, "1d", limit=100)
            df_1d = pd.DataFrame(raw_candles_1d, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            df_1d["Zaman"] = pd.to_datetime(df_1d["Zaman"], unit="ms")
            df_1d = calculate_nw_bands(df_1d, 3.0, "_1d")

            l1_lbl, l2_lbl, l3_lbl = "Kademe 1 (5m)", "Kademe 2 (1h)", "Kademe 3 (4h)"
            s1_lbl, s2_lbl, s3_lbl = "Kademe 1 (5m)", "Kademe 2 (1h)", "Kademe 3 (4h)"
            active_engine_name = "🌎 SİSTEM B: MAKRO TREND (5m/1h/4h)"

        # Seçilen Coin için 3 Günlük Likidasyon Havuzlarını Tahmin Et
        df_long_liq, df_short_liq = estimate_liquidation_pools(selected_symbol)

        latest_row = df.iloc[-1]
        current_price = latest_row["Kapanis"]
        nw_alt_5m = latest_row["NW_Alt_5m"]
        nw_alt_1h = latest_row["NW_Alt_1h"]
        nw_alt_4h = latest_row["NW_Alt_4h"]
        nw_ust_5m = latest_row["NW_Ust_5m"]
        nw_ust_1h = latest_row["NW_Ust_1h"]
        nw_ust_4h = latest_row["NW_Ust_4h"]
        
        rsi_5m = latest_row["RSI_14"] if "RSI_14" in latest_row else 50.0
        rsi_1h = latest_row["RSI_14_1h"] if "RSI_14_1h" in latest_row else 50.0
        rsi_4h = latest_row["RSI_14_4h"] if "RSI_14_4h" in latest_row else 50.0

        # Canlı Iraksama Analizini Yapıyoruz
        bull_div_5m, bear_div_5m = detect_rsi_divergence(df["Kapanis"].values, df["RSI_14"].values) if "RSI_14" in df else (False, False)
        bull_div_1h, bear_div_1h = detect_rsi_divergence(df_1h["Kapanis"].values, df_1h["RSI_14_1h"].values) if "RSI_14_1h" in df_1h else (False, False)
        bull_div_4h, bear_div_4h = detect_rsi_divergence(df_4h_res["Kapanis"].values, df_4h_res["RSI_14_4h"].values) if "RSI_14_4h" in df_4h_res else (False, False)

        # =================== LONG POZİSYON ÇIKIŞLARI ===================
        if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
            l_tp = st.session_state[f"{state_prefix}l_avg_price"] * (1 + target_profit_ratio)
            
            # Kural: Stop-loss yalnızca 3. kademe alındıysa aktifleşir ve son alım fiyatının (NW_Alt_4h) %1 aşağısıdır
            if st.session_state[f"{state_prefix}l_status"][2]:
                l_stop = nw_alt_4h * (1 - stop_loss_ratio)
                if current_price <= l_stop:
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                    msg = f"🔴 *LONG STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f} (Son Alımın %1 Altı)"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}l_crypto"] = 0.0
                    st.session_state[f"{state_prefix}l_usd_spent"] = 0.0
                    st.session_state[f"{state_prefix}l_avg_price"] = 0.0
                    st.session_state[f"{state_prefix}l_status"] = [False, False, False]
                    save_state_to_db()

            elif current_price >= l_tp:
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                msg = f"🟢 *LONG KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}l_crypto"] = 0.0
                st.session_state[f"{state_prefix}l_usd_spent"] = 0.0
                st.session_state[f"{state_prefix}l_avg_price"] = 0.0
                st.session_state[f"{state_prefix}l_status"] = [False, False, False]
                save_state_to_db()

        # =================== SHORT POZİSYON ÇIKIŞLARI ===================
        if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
            s_stop = st.session_state[f"{state_prefix}s_avg_price"] * (1 + stop_loss_ratio)
            s_tp = st.session_state[f"{state_prefix}s_avg_price"] * (1 - target_profit_ratio)

            if st.session_state[f"{state_prefix}s_status"][2] and current_price >= s_stop:
                pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                msg = f"🔴 *SHORT STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f} (Son Alımın %1 Üstü)"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}s_crypto"] = 0.0
                st.session_state[f"{state_prefix}s_usd_spent"] = 0.0
                st.session_state[f"{state_prefix}s_avg_price"] = 0.0
                st.session_state[f"{state_prefix}s_status"] = [False, False, False]
                save_state_to_db()

            elif current_price <= s_tp:
                pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                msg = f"🟢 *SHORT KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}s_crypto"] = 0.0
                st.session_state[f"{state_prefix}s_usd_spent"] = 0.0
                st.session_state[f"{state_prefix}s_avg_price"] = 0.0
                st.session_state[f"{state_prefix}s_status"] = [False, False, False]
                save_state_to_db()

        # =================== LONG GİRİŞLERİ ===================
        if current_price <= nw_alt_5m and not st.session_state[f"{state_prefix}l_status"][0]:
            buy_amt = layer_sizes[0]
            st.session_state[f"{state_prefix}balance_usd"] -= buy_amt * current_price
            st.session_state[f"{state_prefix}l_crypto"] += buy_amt
            st.session_state[f"{state_prefix}l_usd_spent"] += buy_amt * current_price
            st.session_state[f"{state_prefix}l_status"][0] = True
            st.session_state[f"{state_prefix}l_avg_price"] = st.session_state[f"{state_prefix}l_usd_spent"] / st.session_state[f"{state_prefix}l_crypto"]
            msg = f"📈 *LONG K1 SATIN ALINDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)
            save_state_to_db()

        if current_price <= nw_alt_1h and not st.session_state[f"{state_prefix}l_status"][1]:
            buy_amt = layer_sizes[1]
            st.session_state[f"{state_prefix}balance_usd"] -= buy_amt * current_price
            st.session_state[f"{state_prefix}l_crypto"] += buy_amt
            st.session_state[f"{state_prefix}l_usd_spent"] += buy_amt * current_price
            st.session_state[f"{state_prefix}l_status"][1] = True
            st.session_state[f"{state_prefix}l_avg_price"] = st.session_state[f"{state_prefix}l_usd_spent"] / st.session_state[f"{state_prefix}l_crypto"]
            msg = f"📈 *LONG K2 SATIN ALINDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)
            save_state_to_db()

        if current_price <= nw_alt_4h and not st.session_state[f"{state_prefix}l_status"][2]:
            buy_amt = layer_sizes[2]
            st.session_state[f"{state_prefix}balance_usd"] -= buy_amt * current_price
            st.session_state[f"{state_prefix}l_crypto"] += buy_amt
            st.session_state[f"{state_prefix}l_usd_spent"] += buy_amt * current_price
            st.session_state[f"{state_prefix}l_status"][2] = True
            st.session_state[f"{state_prefix}l_avg_price"] = st.session_state[f"{state_prefix}l_usd_spent"] / st.session_state[f"{state_prefix}l_crypto"]
            msg = f"📈 *LONG K3 SATIN ALINDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)
            save_state_to_db()

        # =================== SHORT GİRİŞLERİ ===================
        if current_price >= nw_ust_5m and not st.session_state[f"{state_prefix}s_status"][0]:
            sell_amt = layer_sizes[0]
            st.session_state[f"{state_prefix}balance_usd"] -= sell_amt * current_price
            st.session_state[f"{state_prefix}s_crypto"] += sell_amt
            st.session_state[f"{state_prefix}s_usd_spent"] += sell_amt * current_price
            st.session_state[f"{state_prefix}s_status"][0] = True
            st.session_state[f"{state_prefix}s_avg_price"] = st.session_state[f"{state_prefix}s_usd_spent"] / st.session_state[f"{state_prefix}s_crypto"]
            msg = f"📉 *SHORT K1 AÇILDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)
            save_state_to_db()

        if current_price >= nw_ust_1h and not st.session_state[f"{state_prefix}s_status"][1]:
            sell_amt = layer_sizes[1]
            st.session_state[f"{state_prefix}balance_usd"] -= sell_amt * current_price
            st.session_state[f"{state_prefix}s_crypto"] += sell_amt
            st.session_state[f"{state_prefix}s_usd_spent"] += sell_amt * current_price
            st.session_state[f"{state_prefix}s_status"][1] = True
            st.session_state[f"{state_prefix}s_avg_price"] = st.session_state[f"{state_prefix}s_usd_spent"] / st.session_state[f"{state_prefix}s_crypto"]
            msg = f"📉 *SHORT K2 AÇILDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)
            save_state_to_db()

        if current_price >= nw_ust_4h and not st.session_state[f"{state_prefix}s_status"][2]:
            sell_amt = layer_sizes[2]
            st.session_state[f"{state_prefix}balance_usd"] -= sell_amt * current_price
            st.session_state[f"{state_prefix}s_crypto"] += sell_amt
            st.session_state[f"{state_prefix}s_usd_spent"] += sell_amt * current_price
            st.session_state[f"{state_prefix}s_status"][2] = True
            st.session_state[f"{state_prefix}s_avg_price"] = st.session_state[f"{state_prefix}s_usd_spent"] / st.session_state[f"{state_prefix}s_crypto"]
            msg = f"📉 *SHORT K3 AÇILDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)
            save_state_to_db()

        # =================== EKRAN GÜNCELLEMELERİ (WEB UI - PRO GRID TASARIM) ===================
        with main_container.container():
            col_left, col_right = st.columns([1.6, 1])
            
            # --- SOL SÜTUN (GRAFİKLER VE LİKİDASYON HARİTASI) ---
            with col_left:
                st.subheader("📈 Canlı Fiyat ve Nadaraya-Watson Zarf Grafikleri")
                tab_5m, tab_1h, tab_4h, tab_1d = st.tabs(["⏱️ 5 Dakikalık Grafik", "⏱️ 1 Saatlik Grafik", "⏱️ 4 Saatlik Grafik", "🌎 1 Günlük Grafik"])
                df_subset = df.tail(100)
                
                # 5m Sekmesi (Karanlık Tema)
                with tab_5m:
                    fig1, ax1 = plt.subplots(figsize=(15, 6), facecolor='#0e1117')
                    ax1.set_facecolor('#0e1117')
                    ax1.plot(df_subset["Zaman"], df_subset["Kapanis"], label="Anlık Fiyat (5m)", color="royalblue", linewidth=2.5)
                    ax1.plot(df_subset["Zaman"], df_subset["NW_Alt_5m"], label="Alt Band (5m - 3.0 Std)", color="limegreen", linestyle="--")
                    ax1.plot(df_subset["Zaman"], df_subset["NW_Ust_5m"], label="Üst Band (5m - 3.0 Std)", color="crimson", linestyle="--")
                    
                    if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                        ax1.axhline(y=st.session_state[f"{state_prefix}l_avg_price"], color="green", linestyle="-", alpha=0.6, label="Long Ort.")
                    if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                        ax1.axhline(y=st.session_state[f"{state_prefix}s_avg_price"], color="red", linestyle="-", alpha=0.6, label="Short Ort.")
                    
                    ax1.legend(loc="upper left")
                    ax1.grid(True, color='white', alpha=0.03)
                    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                    st.pyplot(fig1)
                    plt.close(fig1)
                    
                # 1h Sekmesi (Karanlık Tema)
                with tab_1h:
                    fig2, ax2 = plt.subplots(figsize=(15, 6), facecolor='#0e1117')
                    ax2.set_facecolor('#0e1117')
                    ax2.plot(df_subset["Zaman"], df_subset["Kapanis"], label="Anlık Fiyat (5m)", color="royalblue", linewidth=2)
                    ax2.plot(df_subset["Zaman"], df_subset["NW_Alt_1h"], label="Alt Band (1h - 3.0 Std)", color="forestgreen", linestyle="--")
                    ax2.plot(df_subset["Zaman"], df_subset["NW_Ust_1h"], label="Üst Band (1h - 3.0 Std)", color="firebrick", linestyle="--")
                    
                    if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                        ax2.axhline(y=st.session_state[f"{state_prefix}l_avg_price"], color="green", linestyle="-", alpha=0.6, label="Long Ort.")
                    if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                        ax2.axhline(y=st.session_state[f"{state_prefix}s_avg_price"], color="red", linestyle="-", alpha=0.6, label="Short Ort.")
                    
                    ax2.legend(loc="upper left")
                    ax2.grid(True, color='white', alpha=0.03)
                    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                    st.pyplot(fig2)
                    plt.close(fig2)
                    
                # 4h Sekmesi (Karanlık Tema)
                with tab_4h:
                    fig3, ax3 = plt.subplots(figsize=(15, 6), facecolor='#0e1117')
                    ax3.set_facecolor('#0e1117')
                    ax3.plot(df_subset["Zaman"], df_subset["Kapanis"], label="Anlık Fiyat (5m)", color="royalblue", linewidth=2)
                    ax3.plot(df_subset["Zaman"], df_subset["NW_Alt_4h"], label="Alt Band (4h - 3.0 Std)", color="darkgreen", linestyle="-")
                    ax3.plot(df_subset["Zaman"], df_subset["NW_Ust_4h"], label="Üst Band (4h - 3.0 Std)", color="darkred", linestyle="-")
                    
                    if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                        ax3.axhline(y=st.session_state[f"{state_prefix}l_avg_price"], color="green", linestyle="-", alpha=0.6, label="Long Ort.")
                    if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                        ax3.axhline(y=st.session_state[f"{state_prefix}s_avg_price"], color="red", linestyle="-", alpha=0.6, label="Short Ort.")
                    
                    ax3.legend(loc="upper left")
                    ax3.grid(True, color='white', alpha=0.03)
                    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                    st.pyplot(fig3)
                    plt.close(fig3)
                    
                # 1d Sekmesi (Karanlık Tema)
                with tab_1d:
                    fig4, ax4 = plt.subplots(figsize=(15, 6), facecolor='#0e1117')
                    ax4.set_facecolor('#0e1117')
                    df_1d_subset = df_1d.tail(30)
                    ax4.plot(df_1d_subset["Zaman"], df_1d_subset["Kapanis"], label="Günlük Kapanış Fiyatı", color="royalblue", linewidth=2.5)
                    ax4.plot(df_1d_subset["Zaman"], df_1d_subset["NW_Alt_1d"], label="Alt Band (1d - 3.0 Std)", color="limegreen", linestyle="-")
                    ax4.plot(df_1d_subset["Zaman"], df_1d_subset["NW_Ust_1d"], label="Üst Band (1d - 3.0 Std)", color="crimson", linestyle="-")
                    
                    ax4.legend(loc="upper left")
                    ax4.grid(True, color='white', alpha=0.03)
                    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
                    st.pyplot(fig4)
                    plt.close(fig4)

                # --- LİKİDASYON HARİTASI (SOL SÜTUNDA - SIFIR KAYDIRMA) ---
                st.markdown("---")
                st.subheader(f"🎯 3 Günlük {selected_symbol.split('/')[0]} Tahmini Likidasyon Yoğunluk Haritası")
                st.write("Fiyat hareketleri ve hacim birikimlerine göre kaldıraçlı pozisyonların (25x, 50x, 100x) tahmini likidasyon seviyeleri.")
                col_liq_l, col_liq_s = st.columns(2)
                
                with col_liq_l:
                    st.info("🔴 LONG LİKİDASYON HAVUZLARI")
                    if not df_long_liq.empty:
                        st.table(df_long_liq.reset_index(drop=True))
                    else:
                        st.write("Likidasyon verileri yükleniyor...")
                        
                with col_liq_s:
                    st.error("🟢 SHORT LİKİDASYON HAVUZLARI")
                    if not df_short_liq.empty:
                        st.table(df_short_liq.reset_index(drop=True))
                    else:
                        st.write("Likidasyon verileri yükleniyor...")

            # --- SAĞ SÜTUN (KONTROL MASASI VE GÖSTERGELER) ---
            with col_right:
                st.subheader(f"📊 {selected_symbol.split(':')[0]} Canlı Terminal")
                # Dinamik Vites / Aktif Sistem Adı Yazdırılıyor
                st.write(f"Mevcut Durum: **{market_state_label}**")
                st.write(f"Aktif Motor  : **{active_engine_name}**")
                
                # Trend Kartı
                st.markdown("---")
                col_t1, col_t2 = st.columns([1, 1.2])
                col_t1.metric(label="4h Genel Trend", value=trend_4h)
                if trend_4h == "YUKARI (BOĞA)":
                    col_t2.success(f"🛡️ Emniyet: {warning_msg}")
                else:
                    col_t2.error(f"🛡️ Emniyet: {warning_msg}")
                
                # RSI & Iraksama Kartı
                st.markdown("---")
                st.write("⚡ **RSI & Momentum Süzgeci**")
                col_r1, col_r2, col_r3 = st.columns(3)
                
                with col_r1:
                    st.write("**5m (Skalp)**")
                    rsi_5m_state = f"{rsi_5m:.1f} (UCUZ 🟢)" if rsi_5m < 30 else (f"{rsi_5m:.1f} (PAHALI 🔴)" if rsi_5m > 70 else f"{rsi_5m:.1f} (NÖTR)")
                    st.write(rsi_5m_state)
                    if bull_div_5m:
                        st.success("📈 BOĞA IRAKSAMASI!")
                    elif bear_div_5m:
                        st.error("📉 AYI IRAKSAMASI!")
                    else:
                        st.write("Iraksama: *Yok*")
                        
                with col_r2:
                    st.write("**1h (Orta)**")
                    rsi_1h_state = f"{rsi_1h:.1f} (UCUZ 🟢)" if rsi_1h < 30 else (f"{rsi_1h:.1f} (PAHALI 🔴)" if rsi_1h > 70 else f"{rsi_1h:.1f} (NÖTR)")
                    st.write(rsi_1h_state)
                    if bull_div_1h:
                        st.success("📈 BOĞA IRAKSAMASI!")
                    elif bear_div_1h:
                        st.error("📉 AYI IRAKSAMASI!")
                    else:
                        st.write("Iraksama: *Yok*")
                        
                with col_r3:
                    st.write("**4h (Makro)**")
                    rsi_4h_state = f"{rsi_4h:.1f} (UCUZ 🟢)" if rsi_4h < 30 else (f"{rsi_4h:.1f} (PAHALI 🔴)" if rsi_4h > 70 else f"{rsi_4h:.1f} (NÖTR)")
                    st.write(rsi_4h_state)
                    if bull_div_4h:
                        st.success("📈 BOĞA IRAKSAMASI!")
                    elif bear_div_4h:
                        st.error("📉 AYI IRAKSAMASI!")
                    else:
                        st.write("Iraksama: *Yok*")
                
                # DCA Sinyal Takip ve Yönetim Kartı
                st.markdown("---")
                st.write("🎯 **Canlı Sinyal Takip ve DCA Yönetim Kartı**")
                col_l, col_s = st.columns(2)
                
                with col_l:
                    st.info("📈 LONG KADEMELERİ")
                    k1_status = f"✅ Alındı ({st.session_state[f'{state_prefix}l_avg_price']:.2f} USDT)" if st.session_state[f"{state_prefix}l_status"][0] else f"⏳ Bekliyor ({nw_alt_5m:.2f} | {layer_sizes[0]:.4f} {selected_symbol.split('/')[0]})"
                    k2_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][1] else f"⏳ Bekliyor ({nw_alt_1h:.2f} | {layer_sizes[1]:.4f} {selected_symbol.split('/')[0]})"
                    k3_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][2] else f"⏳ Bekliyor ({nw_alt_4h:.2f} | {layer_sizes[2]:.4f} {selected_symbol.split('/')[0]})"
                    st.write(f"**{l1_lbl}:** {k1_status}")
                    st.write(f"**{l2_lbl}:** {k2_status}")
                    st.write(f"**{l3_lbl}:** {k3_status}")
                    if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                        l_tp = st.session_state[f"{state_prefix}l_avg_price"] * 1.01
                        l_sl = nw_alt_4h * 0.99
                        st.markdown(f"**Maliyet Ort :** `{st.session_state[f'{state_prefix}l_avg_price']:.2f} USDT`")
                        st.success(f"🟢 **KAR-AL (%1):** `{l_tp:.2f} USDT` (Sinyal gelince karla satın!)")
                        if st.session_state[f"{state_prefix}l_status"][2]:
                            st.error(f"🚨 **ACİL STOP (%2):** `{l_sl:.2f} USDT` (Son Alımın %1 Altı!)")
                        else:
                            st.warning(f"🛡️ **Emniyet (Stop):** `PASİF` (3. Kademeden Sonra)")

                with col_s:
                    st.error("📉 SHORT KADEMELERİ")
                    s_k1_status = f"✅ Açıldı ({st.session_state[f'{state_prefix}s_avg_price']:.2f} USDT)" if st.session_state[f"{state_prefix}s_status"][0] else f"⏳ Bekliyor ({nw_ust_5m:.2f} | {layer_sizes[0]:.4f} {selected_symbol.split('/')[0]})"
                    s_k2_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][1] else f"⏳ Bekliyor ({nw_ust_1h:.2f} | {layer_sizes[1]:.4f} {selected_symbol.split('/')[0]})"
                    s_k3_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][2] else f"⏳ Bekliyor ({nw_ust_4h:.2f} | {layer_sizes[2]:.4f} {selected_symbol.split('/')[0]})"
                    st.write(f"**{s1_lbl}:** {s_k1_status}")
                    st.write(f"**{s2_lbl}:** {s_k2_status}")
                    st.write(f"**{s3_lbl}:** {s_k3_status}")
                    if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                        s_tp = st.session_state[f"{state_prefix}s_avg_price"] * 0.99
                        s_sl = nw_ust_4h * 1.02
                        st.markdown(f"**Maliyet Ort :** `{st.session_state[f'{state_prefix}s_avg_price']:.2f} USDT`")
                        st.success(f"🟢 **KAR-AL (%1):** `{s_tp:.2f} USDT` (Sinyal gelince karla kapatın!)")
                        if st.session_state[f"{state_prefix}s_status"][2]:
                            st.error(f"🚨 **ACİL STOP (%2):** `{s_sl:.2f} USDT` (Son Alımın %1 Üstü!)")
                        else:
                            st.warning(f"🛡️ **Emniyet (Stop):** `PASİF` (3. Kademeden Sonra)")
                
                # Son Sinyaller
                st.markdown("---")
                if st.session_state[f"{state_prefix}log_history"]:
                    st.write("📜 **Son Sinyaller (Log)**")
                    for log in reversed(st.session_state[f"{state_prefix}log_history"][-3:]):
                        st.write(log)

            # --- GÜNLÜK PİYASA LİDERLERİ TABLOLARI ---
            st.markdown("---")
            st.subheader("🌎 Günlük Piyasa Liderleri (Top 5 Yükselen & Düşen)")
            col_g, col_lo = st.columns(2)
            
            with col_g:
                st.success("📈 EN ÇOK YÜKSELENLER (TOP 5 GAINERS)")
                if not df_gainers.empty:
                    st.table(df_gainers.reset_index(drop=True))
                else:
                    st.write("Veriler yükleniyor...")
                    
            with col_lo:
                st.error("📉 EN ÇOK DÜŞENLER (TOP 5 LOSERS)")
                if not df_losers.empty:
                    st.table(df_losers.reset_index(drop=True))
                else:
                    st.write("Veriler yükleniyor...")

    except Exception as e:
        st.sidebar.error(f"Hata oluştu, 5s sonra denenecek: {e}")
        
    # ================= ANLIK GERİ SAYIM SAYACI =================
    for remaining in range(10, 0, -1):
        countdown_placeholder.write(f"🔄 Sonraki taramaya: **{remaining}** saniye...")
        time.sleep(1)
    countdown_placeholder.write("🔄 Taranıyor...")
