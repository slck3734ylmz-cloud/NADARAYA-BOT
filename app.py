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

# Grafikleri küresel olarak karanlık temaya (Dark Mode) ayarlıyoruz (Backtest sayfanız için gerekli)
plt.style.use('dark_background')

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
                        'price': ticker.get('last') or ticker.get('
