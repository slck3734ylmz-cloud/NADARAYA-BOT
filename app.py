import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import time
import datetime
import requests
import plotly.graph_objects as go
from supabase import create_client, Client

# ================= EN BAŞTA BORSA NESNESİNİN TANIMLANMASI =================
# MEXC Futures (Vadeli) bağlantısı. API key/secret st.secrets üzerinden okunur,
# kod içine asla yazılmaz. Anahtarlar olmadan da fiyat/grafik verisi okunabilir;
# sadece gerçek emir gönderme (canlı mod) ve bakiye sorgulama için gereklidir.
MEXC_API_KEY = st.secrets.get("MEXC_API_KEY", "")
MEXC_API_SECRET = st.secrets.get("MEXC_API_SECRET", "")

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}  # MEXC Futures/Vadeli (USDT-M) modu
})

BOT_LEVERAGE = 200  # MEXC BTC/USDT futures için kullanılacak kaldıraç (cross margin)

# MEXC USDT-M futures taker komisyon oranı (market emirleri her zaman taker sayılır).
# Komisyon, MARJİN üzerinden değil POZİSYON DEĞERİ üzerinden kesilir - kaldıraç arttıkça
# marjine oranla komisyon etkisi de büyür. Round-trip (aç+kapat) = 2x bu oran.
MEXC_TAKER_FEE_PCT = 0.0002  # %0.02
MIN_PROFIT_SAFETY_MULT = 3.0  # Kar-al mesafesi, round-trip komisyonun en az bu katı olmalı

# ================= ZAMAN DİLİMİNE ÖZEL NW / RSI PARAMETRELERİ =================
# Her zaman diliminin kendi "doğal" penceresine göre ayarlanmış parametreler.
# limit       : çekilecek mum sayısı (her TF için gerçekçi bir geçmiş süreye denk gelir)
# h           : Nadaraya-Watson bandwidth (yumuşatma derecesi)
# rsi_period  : o zaman diliminde kullanılacak RSI periyodu
# std_window  : NW bandı için rolling standart sapma penceresi
TF_PARAMS = {
    "1m":  {"limit": 90,  "h": 6, "rsi_period": 7,  "std_window": 15},
    "5m":  {"limit": 100, "h": 7, "rsi_period": 9,  "std_window": 18},
    "15m": {"limit": 110, "h": 8, "rsi_period": 9,  "std_window": 20},
    "1h":  {"limit": 120, "h": 8, "rsi_period": 14, "std_window": 20},
    "4h":  {"limit": 90,  "h": 7, "rsi_period": 14, "std_window": 18},
    "1d":  {"limit": 60,  "h": 6, "rsi_period": 14, "std_window": 14},
}

# ================= KİLİT EKRANI VE GÜVENLİK GİRİŞİ =================
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct: return True

    st.markdown(
        """
        <style>
        @keyframes sheepBounce {
            0%, 100% { transform: translateY(0) rotate(-4deg); }
            50% { transform: translateY(-6px) rotate(4deg); }
        }
        .sheep-emoji { display: inline-block; animation: sheepBounce 2.2s ease-in-out infinite; }
        /* Giriş formunu (text_input + button) görselle aynı 380px genişliğe ve ortaya hizalar */
        div[data-testid="stForm"], 
        div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stForm"]) {
            max-width: 380px;
            margin: 0 auto;
        }
        </style>
        <div style="display:flex; align-items:center; justify-content:center; padding:2.5rem 0 1rem; font-family: -apple-system, sans-serif;">
          <div style="width:380px; text-align:center;">
            <div style="position:relative; width:112px; height:112px; margin:0 auto 8px;">
              <svg width="112" height="112" viewBox="0 0 112 112" style="position:absolute; top:0; left:0;">
                <defs>
                  <radialGradient id="badgeGlow" cx="50%" cy="38%" r="65%">
                    <stop offset="0%" stop-color="#30386B"/>
                    <stop offset="100%" stop-color="#161B33"/>
                  </radialGradient>
                </defs>
                <circle cx="56" cy="56" r="54" fill="url(#badgeGlow)" stroke="#9A8BF0" stroke-width="1"/>
                <circle cx="56" cy="56" r="45" fill="none" stroke="#4A4F7A" stroke-width="0.6"/>
              </svg>
              <div class="sheep-emoji" style="position:absolute; top:0; left:0; width:112px; height:112px; display:flex; align-items:center; justify-content:center; font-size:46px;">🐑</div>
            </div>
            <div style="color:#9A8BF0; font-size:10px; letter-spacing:2px; margin-bottom:14px;">幸運の羊</div>
            <div style="color:#E8E9F5; font-size:28px; font-weight:600; letter-spacing:3px; margin-bottom:6px;">KYOUN</div>
            <div style="color:#6E72A0; font-size:11px; letter-spacing:2px; text-transform:uppercase; margin-bottom:8px;">şanslı koyun terminali</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    _, col_login, _ = st.columns([1, 1.4, 1])
    with col_login:
        with st.form(key="login_form"):
            user_password = st.text_input("Şifre", type="password", key="login_pass_key_global", label_visibility="collapsed", placeholder="Şifrenizi girin")
            submitted = st.form_submit_button("Giriş Yap", use_container_width=True)
            if submitted:
                if user_password == "dca2026":
                    st.session_state.password_correct = True
                    st.rerun()
                else:
                    st.error("❌ Hatalı Şifre! Erişim reddedildi.")
    return False

if not check_password(): st.stop()

st.set_page_config(page_title="Kyoun | DCA Hedging Terminal", layout="wide")

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
    /* ===== Tipografi tutarlılığı ===== */
    /* st.metric değer boyutunu dengele (varsayılan çok büyük, görsel dengesizlik yaratıyor) */
    div[data-testid="stMetricValue"] {
        font-size: 1.4rem !important;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.78rem !important;
        opacity: 0.75;
    }
    /* st.code (RSI değerleri) için sabit, okunaklı punto */
    .stCodeBlock, .stCodeBlock code {
        font-size: 0.82rem !important;
        padding: 2px 6px !important;
    }
    /* st.caption tutarlı, küçük ama okunabilir punto */
    [data-testid="stCaptionContainer"], .stCaption {
        font-size: 0.75rem !important;
    }
    /* Sidebar genel yazı boyutu sıkışmasın, tutarlı kalsın */
    section[data-testid="stSidebar"] p, 
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] .stMarkdown {
        font-size: 0.85rem !important;
    }
    section[data-testid="stSidebar"] h2, 
    section[data-testid="stSidebar"] h3 {
        font-size: 1.05rem !important;
        margin-top: 0.4rem !important;
        margin-bottom: 0.3rem !important;
    }
    /* Buton yazıları tutarlı punto */
    .stButton button, .stRadio label {
        font-size: 0.85rem !important;
    }
    /* Sidebar içindeki bölümler arası boşluğu sıkılaştır (gereksiz boşluk azaltma) */
    section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
        gap: 0.3rem !important;
    }
    /* Ana panel başlıkları (subheader) tutarlı punto */
    [data-testid="stMain"] h3 {
        font-size: 1.1rem !important;
        margin-top: 0.6rem !important;
        margin-bottom: 0.3rem !important;
    }
    /* st.write içindeki kalın metinler (bold) çok büyük görünmesin */
    [data-testid="stMain"] .stMarkdown p {
        font-size: 0.88rem !important;
        line-height: 1.4 !important;
    }
    /* Sidebar radio/toggle seçenekleri arası boşluk */
    section[data-testid="stSidebar"] .stRadio > div {
        gap: 0.15rem !important;
    }
    /* Expander başlığı tutarlı punto */
    [data-testid="stExpander"] summary {
        font-size: 0.82rem !important;
    }
    </style>
    """, 
    unsafe_allow_html=True
)

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

def calculate_atr(df, period=14):
    """
    ATR (Average True Range) - standart Wilder yöntemiyle hesaplanır.
    True Range = max(Yüksek-Düşük, |Yüksek-ÖncekiKapanış|, |Düşük-ÖncekiKapanış|)
    ATR, bu True Range değerlerinin üstel (smoothed) ortalamasıdır.
    Piyasanın o anki gerçek oynaklığını (gap'leri de dahil ederek) ölçer.
    """
    high, low, close = df["Yuksek"], df["Dusuk"], df["Kapanis"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return atr

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
def get_btc_funding_rate():
    """BTC/USDT futures için anlık fonlama oranını ve bir sonraki ödeme zamanını getirir."""
    try:
        fr_data = exchange.fetch_funding_rate("BTC/USDT:USDT")
        return {
            "rate": fr_data.get("fundingRate"),
            "next_rate": fr_data.get("nextFundingRate"),
            "next_time": fr_data.get("nextFundingTimestamp") or fr_data.get("fundingTimestamp"),
            "mark_price": fr_data.get("markPrice"),
            "index_price": fr_data.get("indexPrice"),
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:150]}"}

@st.cache_data(ttl=300)
def estimate_liquidation_pools(symbol, is_volatile=False):
    """
    NOT: MEXC ve genel olarak borsalar, piyasa-geneli gerçek likidasyon/açık pozisyon
    verisini herkese açık API üzerinden sunmuyor (sadece kullanıcının kendi pozisyonu
    görülebilir). Bu fonksiyon bu yüzden TAHMİNİ bir yöntem kullanır: geçmiş mumların
    her birinin en düşük/en yüksek noktasından, piyasada yaygın kullanılan kaldıraç
    seviyelerine (10x, 25x, 50x, 100x) göre olası likidasyon fiyatlarını hesaplar.
    Birden fazla kaldıraç seviyesinin ve yüksek hacmin ÇAKIŞTIĞI fiyat noktaları
    "yoğun" kabul edilir - bu, gerçek likidasyon kümelenmesinin olası göstergesidir,
    ama kesin/gerçek veri değildir.

    Geriye bakış penceresi piyasa durumuna göre dinamiktir: sakin piyasada 3 gün
    (72x 1h mum), volatil piyasada 7 gün (168x 1h mum) - kademe sisteminin volatil
    modda daha uzun zaman dilimlerine (1d) kadar çıkmasıyla tutarlı olması için.
    """
    try:
        lookback_hours = 168 if is_volatile else 72  # 7 gün : 3 gün
        raw_lb = exchange.fetch_ohlcv(symbol, "1h", limit=lookback_hours)
        df_3d = pd.DataFrame(raw_lb, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        highs = df_3d["Yuksek"].values
        lows = df_3d["Dusuk"].values
        volumes = df_3d["Hacim"].values
        current_p = df_3d.iloc[-1]["Kapanis"]
        round_step = 50.0 if current_p > 10000 else (1.0 if current_p > 100 else (0.1 if current_p > 1 else 0.01))

        # Yaygın kaldıraç seviyeleri ve bunlara karşılık gelen yaklaşık likidasyon
        # mesafesi (maintenance margin oranına göre kabaca): 10x->%5, 25x->%2, 50x->%1, 100x->%0.5
        leverage_levels = {10: 0.05, 25: 0.02, 50: 0.01, 100: 0.005}

        long_pools, short_pools = {}, {}
        for i in range(len(df_3d)):
            for lev, pct in leverage_levels.items():
                p_long = round((lows[i] * (1 - pct)) / round_step) * round_step
                if p_long not in long_pools:
                    long_pools[p_long] = {"volume": 0.0, "leverages": set()}
                long_pools[p_long]["volume"] += volumes[i]
                long_pools[p_long]["leverages"].add(lev)

                p_short = round((highs[i] * (1 + pct)) / round_step) * round_step
                if p_short not in short_pools:
                    short_pools[p_short] = {"volume": 0.0, "leverages": set()}
                short_pools[p_short]["volume"] += volumes[i]
                short_pools[p_short]["leverages"].add(lev)

        # Yoğunluk skoru: hacim VE çakışan kaldıraç seviyesi sayısı birlikte değerlendirilir.
        def score(pool_data):
            return pool_data["volume"] * len(pool_data["leverages"])

        sl = sorted(long_pools.items(), key=lambda x: score(x[1]), reverse=True)[:4]
        ss = sorted(short_pools.items(), key=lambda x: score(x[1]), reverse=True)[:4]
        sl.sort(key=lambda x: x[0], reverse=True)
        ss.sort(key=lambda x: x[0], reverse=False)

        avg_vol = df_3d["Hacim"].mean()

        def yogunluk_etiketi(pool_data):
            n_lev = len(pool_data["leverages"])
            yuksek_hacim = pool_data["volume"] > avg_vol * 1.5
            if n_lev >= 3 and yuksek_hacim:
                return "🔴🔴🔴 ÇOK YÜKSEK"
            elif n_lev >= 2 or yuksek_hacim:
                return "🔴🔴 YÜKSEK"
            else:
                return "🔴 ORTA"

        def yogunluk_etiketi_short(pool_data):
            n_lev = len(pool_data["leverages"])
            yuksek_hacim = pool_data["volume"] > avg_vol * 1.5
            if n_lev >= 3 and yuksek_hacim:
                return "🟢🟢🟢 ÇOK YÜKSEK"
            elif n_lev >= 2 or yuksek_hacim:
                return "🟢🟢 YÜKSEK"
            else:
                return "🟢 ORTA"

        return (
            pd.DataFrame([{"Likidasyon Fiyatı": f"${p:,.2f}", "Çakışan Kaldıraç": "/".join(f"{l}x" for l in sorted(d["leverages"])), "Yoğunluk": yogunluk_etiketi(d)} for p, d in sl]),
            pd.DataFrame([{"Likidasyon Fiyatı": f"${p:,.2f}", "Çakışan Kaldıraç": "/".join(f"{l}x" for l in sorted(d["leverages"])), "Yoğunluk": yogunluk_etiketi_short(d)} for p, d in ss])
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

def calculate_nw_bands(df, std_multiplier, col_suffix, h=8, std_window=20):
    df["NW_Merkez"] = nadaraya_watson_estimator(df["Kapanis"].values, h=h)
    df["Fark"] = df["Kapanis"] - df["NW_Merkez"]
    df["Sapma_Std"] = df["Fark"].rolling(window=std_window).std()
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
        annotation_bgcolor='#F0B90B', annotation_borderpad=3,
        annotation_xshift=38
    )

    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", font=dict(size=15, color='#E8EAED', family="Arial"), x=0.01, xanchor='left', y=0.99, yanchor='top'),
        template="plotly_dark",
        plot_bgcolor='#0B0E11',
        paper_bgcolor='#0B0E11',
        font=dict(color='#B7BDC6', family="Arial"),
        margin=dict(l=10, r=85, t=85, b=10),
        height=460,
        bargap=0.25,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        hoverlabel=dict(bgcolor='#1E2329', font_size=12, font_family="Arial", bordercolor='#2B3139'),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0.0,
            bgcolor='rgba(0,0,0,0)', font=dict(size=11, color='#B7BDC6')
        ),
        dragmode='pan'
    )

    fig.update_xaxes(
        showgrid=True, gridcolor='rgba(240, 185, 11, 0.06)', gridwidth=1,
        showline=True, linewidth=1, linecolor='#2B3139', mirror=True,
        rangeslider_visible=False, showspikes=True, spikecolor='#F0B90B',
        spikethickness=1, spikedash='dot', spikemode='across',
        tickfont=dict(color='#9098A1', size=11)
    )
    fig.update_yaxes(
        showgrid=True, gridcolor='rgba(240, 185, 11, 0.06)', gridwidth=1,
        showline=True, linewidth=1, linecolor='#2B3139', mirror=True,
        side='right', showspikes=True, spikecolor='#F0B90B',
        spikethickness=1, spikedash='dot',
        tickfont=dict(color='#D1D4DC', size=12),
        automargin=True
    )

    return fig

# ================= YAN PANEL AYARLARI VE NAVİGASYON =================
st.sidebar.markdown("## 🐑 Kyoun")
st.sidebar.caption("BTC/USDT Futures Hedging Terminal")
st.sidebar.markdown("---")
st.sidebar.subheader("💳 Cüzdan Durumu")

# Bot sadece BTC/USDT futures üzerinde sabit çalışır (coin seçimi kaldırıldı).
selected_symbol = "BTC/USDT:USDT"
coin_title = selected_symbol.split(':')[0]
state_prefix = f"{selected_symbol}_"

col_s1, col_s2 = st.sidebar.columns(2)
col_s1.metric("Bakiye", "$100.00")
col_s2.metric("Kaldıraç", f"{BOT_LEVERAGE}x")
st.sidebar.caption(f"🔥 {coin_title} · Cross Margin")

# ================= YAN PANEL FONLAMA ORANI (BTC) =================
st.sidebar.markdown("---")
btc_funding = get_btc_funding_rate()

if "error" in btc_funding:
    st.sidebar.warning(f"Fonlama oranı alınamadı: {btc_funding['error']}")
elif btc_funding.get("rate") is not None:
    rate_pct = btc_funding["rate"] * 100.0
    rate_str = f"{rate_pct:+.4f}%"
    fr_color = "green" if rate_pct < 0 else "red"
    st.sidebar.markdown(f"💸 **Fonlama Oranı:** :{fr_color}[{rate_str}]")
    with st.sidebar.expander("Fonlama detayları"):
        st.caption("Negatif: Short→Long öder. Pozitif: Long→Short öder.")
        if btc_funding.get("next_rate") is not None:
            next_pct = btc_funding["next_rate"] * 100.0
            st.write(f"Tahmini Sonraki Oran: {next_pct:+.4f}%")
        if btc_funding.get("next_time"):
            try:
                next_dt = datetime.datetime.fromtimestamp(btc_funding["next_time"] / 1000, tz=datetime.timezone.utc)
                st.write(f"Sonraki Ödeme: {next_dt.strftime('%H:%M UTC')}")
            except Exception:
                pass
        if btc_funding.get("mark_price"):
            st.write(f"Mark Fiyat: ${btc_funding['mark_price']:,.2f}")
else:
    st.sidebar.write("Fonlama oranı yükleniyor...")

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

# Kademe miktarları sabit BTC değerleridir (bot sadece BTC/USDT üzerinde çalışır):
# K1=0.0001 BTC, K2=0.0004 BTC, K3=0.0012 BTC. LONG ve SHORT için aynı miktarlar kullanılır.
layer_sizes = [0.0001, 0.0004, 0.0012]

def send_telegram_msg(message):
    signed_message = f"🐑 *Kyoun*\n{message}"
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": signed_message, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload)
    except: pass

def place_futures_order(symbol, side, amount, leverage=None, is_live=False, reduce_only=False):
    """
    MEXC Futures (vadeli) emir gönderme yardımcı fonksiyonu.
    - is_live=False (Kağıt Mod): Hiçbir gerçek emir göndermez, sadece sonucu simüle edip
      başarı durumu döner. Sinyal/log/Telegram akışı normal şekilde devam eder.
    - is_live=True (Canlı Mod): MEXC'e gerçek bir piyasa emri gönderir.
    side: 'buy' (long aç/short kapat) veya 'sell' (short aç/long kapat)
    reduce_only: pozisyon kapatma (stop-loss/kar-al) emirlerinde True gönderilir.
    leverage: belirtilmezse BOT_LEVERAGE (200x) kullanılır.
    """
    if leverage is None:
        leverage = BOT_LEVERAGE
    if not is_live:
        return {"paper": True, "symbol": symbol, "side": side, "amount": amount, "status": "simulated"}

    try:
        params = {
            "leverage": leverage,
            "marginMode": "cross",
        }
        if reduce_only:
            params["reduceOnly"] = True
        order = exchange.create_order(symbol, "market", side, amount, None, params)
        return {"paper": False, "status": "success", "order": order}
    except Exception as e:
        return {"paper": False, "status": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}

# ================= MASAÜSTÜ CANLI DCA TERMINALİ =================
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ İşlem Modu (MEXC Futures)")

api_keys_present = bool(MEXC_API_KEY and MEXC_API_SECRET)
if not api_keys_present:
    st.sidebar.warning("⚠️ MEXC API anahtarı tanımlı değil. Sadece Kağıt Mod kullanılabilir.")

trading_mode = st.sidebar.radio(
    "Mod Seçimi",
    options=["📝 Kağıt Mod (Emir Gönderilmez)", "🔴 CANLI MOD (Gerçek Emir Gönderilir)"],
    index=0,
    key="trading_mode_radio",
    disabled=not api_keys_present
)
live_trading_enabled = trading_mode.startswith("🔴") and api_keys_present

if live_trading_enabled:
    st.sidebar.error("🔴 CANLI MOD AKTİF — Bu bot gerçek MEXC futures hesabınızda gerçek emir gönderecek!")
    live_confirm = st.sidebar.checkbox("Riskleri anladım, gerçek emir gönderilmesini onaylıyorum", key="live_trading_confirm_checkbox")
    if not live_confirm:
        live_trading_enabled = False
        st.sidebar.info("Onay kutusu işaretlenmeden canlı emir gönderilmeyecek (kağıt mod gibi çalışır).")
else:
    st.sidebar.success("📝 Kağıt Mod: Sinyaller hesaplanır, hiçbir gerçek emir gönderilmez.")

manual_lock = st.sidebar.toggle("🔒 Bekleyen Seviyeleri Dondur", value=False, key="live_manual_lock_toggle")

col_b1, col_b2 = st.sidebar.columns(2)
if col_b1.button("🔔 Telegram Test", key="live_telegram_test_button_unique", use_container_width=True):
    send_telegram_msg(f"👋 *Bağlantı Testi:* Web siteniz üzerinden gönderilen test mesajı başarılı!")
    st.sidebar.success("Mesaj gönderildi!")

if col_b2.button("🔴 Sıfırla", key="live_reset_all_positions_button", use_container_width=True):
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

@st.fragment(run_every="10s")
def live_dca_fragment():
    try:
        live_ticker = exchange.fetch_ticker(selected_symbol)
        current_price = live_ticker.get('last') or live_ticker.get('close') or 0.0
        price_change_24h = live_ticker.get('percentage') or 0.0

        p1m = TF_PARAMS["1m"]
        raw_1m = exchange.fetch_ohlcv(selected_symbol, "1m", limit=p1m["limit"])
        df_1m = pd.DataFrame(raw_1m, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_1m["Zaman"] = pd.to_datetime(df_1m["Zaman"], unit="ms")
        df_1m = calculate_nw_bands(df_1m, 3.0, "_1m", h=p1m["h"], std_window=p1m["std_window"])
        df_1m["RSI"] = calculate_rsi(df_1m["Kapanis"], period=p1m["rsi_period"])
        df_1m["ATR"] = calculate_atr(df_1m, period=14)

        p5m = TF_PARAMS["5m"]
        raw_5m = exchange.fetch_ohlcv(selected_symbol, "5m", limit=p5m["limit"])
        df_5m = pd.DataFrame(raw_5m, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_5m["Zaman"] = pd.to_datetime(df_5m["Zaman"], unit="ms")
        df_5m = calculate_nw_bands(df_5m, 3.0, "_5m", h=p5m["h"], std_window=p5m["std_window"])
        df_5m["RSI"] = calculate_rsi(df_5m["Kapanis"], period=p5m["rsi_period"])
        df_5m["ATR"] = calculate_atr(df_5m, period=14)

        # 15m verisi hem volatilite ölçümü hem de kademe hesaplaması için kullanılır,
        # tek seferde çekilir (önceden iki ayrı API çağrısı yapılıyordu).
        p15m = TF_PARAMS["15m"]
        raw_15m = exchange.fetch_ohlcv(selected_symbol, "15m", limit=p15m["limit"])
        df_15m = pd.DataFrame(raw_15m, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_15m["Zaman"] = pd.to_datetime(df_15m["Zaman"], unit="ms")
        df_15m = calculate_nw_bands(df_15m, 3.0, "_15m", h=p15m["h"], std_window=p15m["std_window"])
        df_15m["RSI"] = calculate_rsi(df_15m["Kapanis"], period=p15m["rsi_period"])
        df_15m["ATR"] = calculate_atr(df_15m, period=14)

        # Volatilite tespiti: HEM fiyat std'si HEM hacim onayı birlikte gerekir.
        # Sadece fiyat std'sinin kendi medyanına göre yüksek olması yeterli değil
        # (göreceli bir ölçüm, mutlak piyasa durumunu yansıtmaz); hacim de
        # ortalamasının üzerinde olmalı ki "gerçek" bir volatilite patlaması sayılsın.
        price_std_now = df_15m["Kapanis"].rolling(20).std().iloc[-1]
        price_std_median = df_15m["Kapanis"].rolling(20).std().median()
        vol_now = df_15m["Hacim"].rolling(20).mean().iloc[-1]
        vol_median = df_15m["Hacim"].rolling(20).mean().median()

        price_is_volatile = price_std_now > price_std_median
        volume_confirms = vol_now > vol_median
        is_volatile = price_is_volatile and volume_confirms

        if is_volatile:
            market_state_label = "⚡ VOLATİL (Trend / Sert Hareket — Hacim Onaylı)"
        elif price_is_volatile and not volume_confirms:
            market_state_label = "⚠️ FİYAT OYNAK AMA HACİM DÜŞÜK (Sakin Sayılır)"
        else:
            market_state_label = "💤 SAKİN (Yatay Salınım)"

        p1h = TF_PARAMS["1h"]
        raw_1h = exchange.fetch_ohlcv(selected_symbol, "1h", limit=p1h["limit"])
        df_1h = pd.DataFrame(raw_1h, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_1h["Zaman"] = pd.to_datetime(df_1h["Zaman"], unit="ms")
        df_1h = calculate_nw_bands(df_1h, 3.0, "_1h", h=p1h["h"], std_window=p1h["std_window"])
        df_1h["RSI"] = calculate_rsi(df_1h["Kapanis"], period=p1h["rsi_period"])
        df_1h["ATR"] = calculate_atr(df_1h, period=14)

        # 4h: NW/RSI için kısa pencere (p4h["limit"]), EMA_200 (genel trend) için ise
        # ayrı ve daha uzun bir veri çekişi (250 mum) yapılır; EMA_200 kısa pencerede
        # istatistiksel olarak stabilize olamaz.
        p4h = TF_PARAMS["4h"]
        raw_4h = exchange.fetch_ohlcv(selected_symbol, "4h", limit=p4h["limit"])
        df_4h = pd.DataFrame(raw_4h, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_4h["Zaman"] = pd.to_datetime(df_4h["Zaman"], unit="ms")
        df_4h = calculate_nw_bands(df_4h, 3.0, "_4h", h=p4h["h"], std_window=p4h["std_window"])
        df_4h["RSI"] = calculate_rsi(df_4h["Kapanis"], period=p4h["rsi_period"])
        df_4h["ATR"] = calculate_atr(df_4h, period=14)

        raw_4h_trend = exchange.fetch_ohlcv(selected_symbol, "4h", limit=250)
        df_4h_trend = pd.DataFrame(raw_4h_trend, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_4h_trend["EMA_200"] = df_4h_trend["Kapanis"].ewm(span=200, adjust=False).mean()
        trend_4h = "YUKARI (BOĞA)" if df_4h_trend.iloc[-1]["Kapanis"] > df_4h_trend.iloc[-1]["EMA_200"] else "AŞAĞI (AYI)"
        warning_msg = "SHORT açarken DİKKATLİ olun!" if trend_4h == "YUKARI (BOĞA)" else "LONG açarken DİKKATLİ olun!"

        p1d = TF_PARAMS["1d"]
        raw_candles_1d = exchange.fetch_ohlcv(selected_symbol, "1d", limit=p1d["limit"])
        df_1d = pd.DataFrame(raw_candles_1d, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_1d["Zaman"] = pd.to_datetime(df_1d["Zaman"], unit="ms")
        df_1d = calculate_nw_bands(df_1d, 3.0, "_1d", h=p1d["h"], std_window=p1d["std_window"])
        df_1d["RSI"] = calculate_rsi(df_1d["Kapanis"], period=p1d["rsi_period"])
        df_1d["ATR"] = calculate_atr(df_1d, period=14)

        df_long_liq, df_short_liq = estimate_liquidation_pools(selected_symbol, is_volatile=is_volatile)

        # =================== DİNAMİK KADEME SİSTEMİ (Volatilite Bazlı) ===================
        # Yatay (sakin) piyasa : Kademe 1=1m, Kademe 2=5m, Kademe 3=15m
        # Volatil piyasa       : Kademe 1=15m, Kademe 2=1h, Kademe 3=1d
        if is_volatile:
            df_k1, df_k2, df_k3 = df_15m, df_1h, df_1d
            suf_k1, suf_k2, suf_k3 = "_15m", "_1h", "_1d"
            l1_lbl, l2_lbl, l3_lbl = "Kademe 1 (15m)", "Kademe 2 (1h)", "Kademe 3 (1d)"
            s1_lbl, s2_lbl, s3_lbl = "Kademe 1 (15m)", "Kademe 2 (1h)", "Kademe 3 (1d)"
            active_engine_name = "⚡ VOLATİL MOTOR (15m / 1h / 1d Hiyerarşisi)"
        else:
            df_k1, df_k2, df_k3 = df_1m, df_5m, df_15m
            suf_k1, suf_k2, suf_k3 = "_1m", "_5m", "_15m"
            l1_lbl, l2_lbl, l3_lbl = "Kademe 1 (1m)", "Kademe 2 (5m)", "Kademe 3 (15m)"
            s1_lbl, s2_lbl, s3_lbl = "Kademe 1 (1m)", "Kademe 2 (5m)", "Kademe 3 (15m)"
            active_engine_name = "💤 SAKİN MOTOR (1m / 5m / 15m Hiyerarşisi)"

        raw_k1_alt = df_k1.iloc[-2][f"NW_Alt{suf_k1}"]
        raw_k2_alt = df_k2.iloc[-2][f"NW_Alt{suf_k2}"]
        raw_k3_alt = df_k3.iloc[-2][f"NW_Alt{suf_k3}"]

        raw_k1_ust = df_k1.iloc[-2][f"NW_Ust{suf_k1}"]
        raw_k2_ust = df_k2.iloc[-2][f"NW_Ust{suf_k2}"]
        raw_k3_ust = df_k3.iloc[-2][f"NW_Ust{suf_k3}"]

        # Her kademenin kendi zaman diliminin RSI değeri (filtre/onay için kullanılacak).
        # NW bandı gibi "son kapanmış mum" (iloc[-2]) bazında hesaplanır - henüz
        # tamamlanmamış anlık mumun RSI'sini kullanmak geçici/yanıltıcı sinyal üretebilir.
        rsi_k1 = df_k1.iloc[-2]["RSI"]
        rsi_k2 = df_k2.iloc[-2]["RSI"]
        rsi_k3 = df_k3.iloc[-2]["RSI"]
        # Önceki kapanmış bar RSI değerleri - "dönüş" (crossover) tespiti için gerekli.
        rsi_k1_prev = df_k1.iloc[-3]["RSI"]
        rsi_k2_prev = df_k2.iloc[-3]["RSI"]
        rsi_k3_prev = df_k3.iloc[-3]["RSI"]
        RSI_OVERSOLD, RSI_OVERBOUGHT = 30, 70

        # Her kademenin kendi zaman diliminin ATR değeri - kar-al/stop-loss mesafelerini
        # piyasanın o anki gerçek oynaklığına göre ölçeklemek için kullanılır.
        # Kar-al = 1x ATR, Stop-loss = 1.5x ATR (kademe 3'ün ATR'si, en son/ana kademe).
        atr_k1 = df_k1.iloc[-2]["ATR"]
        atr_k2 = df_k2.iloc[-2]["ATR"]
        atr_k3 = df_k3.iloc[-2]["ATR"]
        ATR_TP_MULT, ATR_SL_MULT = 1.0, 1.5

        # KOMİSYON GÜVENLİĞİ: ATR çok küçükse (sakin piyasa), 1x ATR mesafesi MEXC'in
        # round-trip taker komisyonunu (%0.04) bile karşılamayabilir - bu durumda
        # "kar-al" tetiklendiğinde komisyon kesintisi sonrası gerçekte ZARAR edilir.
        # Bu yüzden kar-al mesafesi her zaman round-trip komisyonun en az
        # MIN_PROFIT_SAFETY_MULT katı olacak şekilde garanti edilir.
        round_trip_fee_pct = 2 * MEXC_TAKER_FEE_PCT
        min_tp_distance = current_price * round_trip_fee_pct * MIN_PROFIT_SAFETY_MULT
        atr_tp_distance = max(ATR_TP_MULT * atr_k3, min_tp_distance)

        # Iraksama (divergence) tespiti - her kademenin kendi zaman diliminde,
        # son kapanmış mumlar üzerinden (anlık/oluşmakta olan mum hariç).
        div_k1_bull, div_k1_bear = detect_rsi_divergence(df_k1["Kapanis"].values[:-1], df_k1["RSI"].values[:-1])
        div_k2_bull, div_k2_bear = detect_rsi_divergence(df_k2["Kapanis"].values[:-1], df_k2["RSI"].values[:-1])
        div_k3_bull, div_k3_bear = detect_rsi_divergence(df_k3["Kapanis"].values[:-1], df_k3["RSI"].values[:-1])

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

        if manual_lock:
            if st.session_state[f"{state_prefix}locked_prices"] is None:
                st.session_state[f"{state_prefix}locked_prices"] = {"nw_alt_5m": nw_alt_5m, "nw_alt_1h": nw_alt_1h, "nw_alt_4h": nw_alt_4h, "nw_ust_5m": nw_ust_5m, "nw_ust_1h": nw_ust_1h, "nw_ust_4h": nw_ust_4h}
            nw_alt_5m, nw_alt_1h, nw_alt_4h = st.session_state[f"{state_prefix}locked_prices"]["nw_alt_5m"], st.session_state[f"{state_prefix}locked_prices"]["nw_alt_1h"], st.session_state[f"{state_prefix}locked_prices"]["nw_alt_4h"]
            nw_ust_5m, nw_ust_1h, nw_ust_4h = st.session_state[f"{state_prefix}locked_prices"]["nw_ust_5m"], st.session_state[f"{state_prefix}locked_prices"]["nw_ust_1h"], st.session_state[f"{state_prefix}locked_prices"]["nw_ust_4h"]
        else:
            st.session_state[f"{state_prefix}locked_prices"] = None

        if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
            l_avg_price = st.session_state[f"{state_prefix}l_avg_price"]
            l_tp = l_avg_price + atr_tp_distance
            l_sl = l_avg_price - (ATR_SL_MULT * atr_k3)
            if st.session_state[f"{state_prefix}l_status"][2] and current_price <= l_sl:
                order_result = place_futures_order(selected_symbol, "sell", st.session_state[f"{state_prefix}l_crypto"], is_live=live_trading_enabled, reduce_only=True)
                l_avg_for_msg = st.session_state[f"{state_prefix}l_avg_price"]
                l_crypto_for_msg = st.session_state[f"{state_prefix}l_crypto"]
                l_pnl_usd = (current_price - l_avg_for_msg) * l_crypto_for_msg
                l_pnl_pct = ((current_price / l_avg_for_msg) - 1) * 100 if l_avg_for_msg > 0 else 0.0
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                mode_tag = "🔴 CANLI" if live_trading_enabled else "📝 KAĞIT"
                order_note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
                msg = f"🔴 *[{mode_tag}] LONG STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nMaliyet Ort.: {l_avg_for_msg:.2f}\nSatış: {current_price:.2f}\nKapatılan Miktar: {l_crypto_for_msg:.6f} {coin_title.split('/')[0]}\nATR Mesafe: {ATR_SL_MULT}x{atr_k3:.2f}\nK/Z: {l_pnl_usd:+.2f} USDT ({l_pnl_pct:+.2f}%){order_note}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}l_crypto"], st.session_state[f"{state_prefix}l_usd_spent"], st.session_state[f"{state_prefix}l_avg_price"] = 0.0, 0.0, 0.0
                st.session_state[f"{state_prefix}l_status"] = [False, False, False]
                st.session_state[f"{state_prefix}l_entry_prices"] = [0.0, 0.0, 0.0]
                save_state_to_db()
            elif current_price >= l_tp:
                order_result = place_futures_order(selected_symbol, "sell", st.session_state[f"{state_prefix}l_crypto"], is_live=live_trading_enabled, reduce_only=True)
                l_avg_for_msg = st.session_state[f"{state_prefix}l_avg_price"]
                l_crypto_for_msg = st.session_state[f"{state_prefix}l_crypto"]
                l_pnl_usd = (current_price - l_avg_for_msg) * l_crypto_for_msg
                l_pnl_pct = ((current_price / l_avg_for_msg) - 1) * 100 if l_avg_for_msg > 0 else 0.0
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                mode_tag = "🔴 CANLI" if live_trading_enabled else "📝 KAĞIT"
                order_note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
                msg = f"🟢 *[{mode_tag}] LONG KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nMaliyet Ort.: {l_avg_for_msg:.2f}\nSatış: {current_price:.2f}\nKapatılan Miktar: {l_crypto_for_msg:.6f} {coin_title.split('/')[0]}\nKar-Al Mesafesi: {atr_tp_distance:.2f}\nK/Z: {l_pnl_usd:+.2f} USDT ({l_pnl_pct:+.2f}%){order_note}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}l_crypto"], st.session_state[f"{state_prefix}l_usd_spent"], st.session_state[f"{state_prefix}l_avg_price"] = 0.0, 0.0, 0.0
                st.session_state[f"{state_prefix}l_status"] = [False, False, False]
                st.session_state[f"{state_prefix}l_entry_prices"] = [0.0, 0.0, 0.0]
                save_state_to_db()


        if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
            s_avg_price = st.session_state[f"{state_prefix}s_avg_price"]
            s_stop = s_avg_price + (ATR_SL_MULT * atr_k3)
            s_tp = s_avg_price - atr_tp_distance
            if st.session_state[f"{state_prefix}s_status"][2] and current_price >= s_stop:
                order_result = place_futures_order(selected_symbol, "buy", st.session_state[f"{state_prefix}s_crypto"], is_live=live_trading_enabled, reduce_only=True)
                s_avg_for_msg = st.session_state[f"{state_prefix}s_avg_price"]
                s_crypto_for_msg = st.session_state[f"{state_prefix}s_crypto"]
                pnl = (s_avg_for_msg - current_price) / s_avg_for_msg if s_avg_for_msg > 0 else 0.0
                s_pnl_usd = st.session_state[f"{state_prefix}s_usd_spent"] * pnl
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                mode_tag = "🔴 CANLI" if live_trading_enabled else "📝 KAĞIT"
                order_note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
                msg = f"🔴 *[{mode_tag}] SHORT STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nMaliyet Ort.: {s_avg_for_msg:.2f}\nKapanış: {current_price:.2f}\nKapatılan Miktar: {s_crypto_for_msg:.6f} {coin_title.split('/')[0]}\nATR Mesafe: {ATR_SL_MULT}x{atr_k3:.2f}\nK/Z: {s_pnl_usd:+.2f} USDT ({pnl*100:+.2f}%){order_note}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}s_crypto"], st.session_state[f"{state_prefix}s_usd_spent"], st.session_state[f"{state_prefix}s_avg_price"] = 0.0, 0.0, 0.0
                st.session_state[f"{state_prefix}s_status"] = [False, False, False]
                st.session_state[f"{state_prefix}s_entry_prices"] = [0.0, 0.0, 0.0]
                save_state_to_db()
            elif current_price <= s_tp:
                order_result = place_futures_order(selected_symbol, "buy", st.session_state[f"{state_prefix}s_crypto"], is_live=live_trading_enabled, reduce_only=True)
                s_avg_for_msg = st.session_state[f"{state_prefix}s_avg_price"]
                s_crypto_for_msg = st.session_state[f"{state_prefix}s_crypto"]
                pnl = (s_avg_for_msg - current_price) / s_avg_for_msg if s_avg_for_msg > 0 else 0.0
                s_pnl_usd = st.session_state[f"{state_prefix}s_usd_spent"] * pnl
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                mode_tag = "🔴 CANLI" if live_trading_enabled else "📝 KAĞIT"
                order_note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
                msg = f"🟢 *[{mode_tag}] SHORT KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nMaliyet Ort.: {s_avg_for_msg:.2f}\nKapanış: {current_price:.2f}\nKapatılan Miktar: {s_crypto_for_msg:.6f} {coin_title.split('/')[0]}\nKar-Al Mesafesi: {atr_tp_distance:.2f}\nK/Z: {s_pnl_usd:+.2f} USDT ({pnl*100:+.2f}%){order_note}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}s_crypto"], st.session_state[f"{state_prefix}s_usd_spent"], st.session_state[f"{state_prefix}s_avg_price"] = 0.0, 0.0, 0.0
                st.session_state[f"{state_prefix}s_status"] = [False, False, False]
                st.session_state[f"{state_prefix}s_entry_prices"] = [0.0, 0.0, 0.0]
                save_state_to_db()

        rsi_per_kademe = [rsi_k1, rsi_k2, rsi_k3]
        rsi_prev_per_kademe = [rsi_k1_prev, rsi_k2_prev, rsi_k3_prev]
        div_bull_per_kademe = [div_k1_bull, div_k2_bull, div_k3_bull]
        div_bear_per_kademe = [div_k1_bear, div_k2_bear, div_k3_bear]

        # ================= LONG ALIM DÖNGÜSÜ (RSI ONAYI DEVRE DIŞI) =================
        for idx, th, val, rsi_val, rsi_prev, div_bull in zip([0, 1, 2], [nw_alt_5m, nw_alt_1h, nw_alt_4h], layer_sizes, rsi_per_kademe, rsi_prev_per_kademe, div_bull_per_kademe):
            nw_signal = current_price <= th and (idx == 0 or st.session_state[f"{state_prefix}l_status"][idx-1]) and not st.session_state[f"{state_prefix}l_status"][idx]
            
            # RSI kontrolü olmadan sadece NW sinyali ile doğrudan alım tetiklenir
            if nw_signal:
                order_result = place_futures_order(selected_symbol, "buy", val, is_live=live_trading_enabled)
                st.session_state[f"{state_prefix}balance_usd"] -= val * current_price
                st.session_state[f"{state_prefix}l_crypto"] += val
                st.session_state[f"{state_prefix}l_usd_spent"] += val * current_price
                st.session_state[f"{state_prefix}l_status"][idx] = True
                st.session_state[f"{state_prefix}l_entry_prices"][idx] = current_price
                st.session_state[f"{state_prefix}l_avg_price"] = st.session_state[f"{state_prefix}l_usd_spent"] / st.session_state[f"{state_prefix}l_crypto"]
                mode_tag = "🔴 CANLI" if live_trading_enabled else "📝 KAĞIT"
                order_note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
                div_note = "\n🔁 Bullish Iraksama: ✅ (ekstra güven sinyali)" if div_bull else ""
                
                # Bilgi amaçlı anlık RSI loglanır ancak tetikleme üzerinde etkisi yoktur
                msg = f"📈 *[{mode_tag}] LONG K{idx+1} SATIN ALINDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}\nMiktar: {val:.6f} {coin_title.split('/')[0]}\nAnlık RSI: {rsi_val:.1f}{div_note}{order_note}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                save_state_to_db()
                break

        # ================= SHORT GİRİŞ DÖNGÜSÜ (RSI ONAYI DEVREDE) =================
        for idx, th, val, rsi_val, rsi_prev, div_bear in zip([0, 1, 2], [nw_ust_5m, nw_ust_1h, nw_ust_4h], layer_sizes, rsi_per_kademe, rsi_prev_per_kademe, div_bear_per_kademe):
            nw_signal = current_price >= th and (idx == 0 or st.session_state[f"{state_prefix}s_status"][idx-1]) and not st.session_state[f"{state_prefix}s_status"][idx]
            
            # SHORT için momentum dönüş/tükeniş kontrolü (RSI Onayı) devam etmektedir.
            rsi_confirms_short = rsi_prev > RSI_OVERBOUGHT and rsi_val <= RSI_OVERBOUGHT
            if nw_signal and not rsi_confirms_short:
                continue
            if nw_signal:
                order_result = place_futures_order(selected_symbol, "sell", val, is_live=live_trading_enabled)
                st.session_state[f"{state_prefix}balance_usd"] -= val * current_price
                st.session_state[f"{state_prefix}s_crypto"] += val
                st.session_state[f"{state_prefix}s_usd_spent"] += val * current_price
                st.session_state[f"{state_prefix}s_status"][idx] = True
                st.session_state[f"{state_prefix}s_entry_prices"][idx] = current_price
                st.session_state[f"{state_prefix}s_avg_price"] = st.session_state[f"{state_prefix}s_usd_spent"] / st.session_state[f"{state_prefix}s_crypto"]
                mode_tag = "🔴 CANLI" if live_trading_enabled else "📝 KAĞIT"
                order_note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
                div_note = "\n🔁 Bearish Iraksama: ✅ (ekstra güven sinyali)" if div_bear else ""
                msg = f"📈 *[{mode_tag}] SHORT K{idx+1} AÇILDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}\nMiktar: {val:.6f} {coin_title.split('/')[0]}\nRSI Dönüşü: {rsi_prev:.1f} → {rsi_val:.1f} (overbought'tan çıkış){div_note}{order_note}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                save_state_to_db()
                break

        col_left, col_right = st.columns([1.6, 1])
    
        with col_left:
            st.subheader("📈 Canlı Fiyat ve Nadaraya-Watson Zarf Grafikleri")
            tab_1m, tab_5m, tab_15m, tab_1h, tab_4h, tab_1d = st.tabs(["⏱️ 1m", "⏱️ 5m", "⏱️ 15m", "⏱️ 1h", "⏱️ 4h", "🌎 1d"])
        
            with tab_1m:
                df_subset = df_1m.tail(TF_PARAMS["1m"]["limit"])
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1m", "NW_Ust_1m", f"{coin_title} - 1m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key=f"{state_prefix}chart_1m")
            with tab_5m:
                df_subset = df_5m.tail(TF_PARAMS["5m"]["limit"])
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_5m", "NW_Ust_5m", f"{coin_title} - 5m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key=f"{state_prefix}chart_5m")
            with tab_15m:
                df_subset = df_15m.tail(TF_PARAMS["15m"]["limit"])
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_15m", "NW_Ust_15m", f"{coin_title} - 15m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key=f"{state_prefix}chart_15m")
            with tab_1h:
                df_subset = df_1h.tail(TF_PARAMS["1h"]["limit"])
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1h", "NW_Ust_1h", f"{coin_title} - 1h Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key=f"{state_prefix}chart_1h")
            with tab_4h:
                df_subset = df_4h.tail(TF_PARAMS["4h"]["limit"])
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_4h", "NW_Ust_4h", f"{coin_title} - 4h Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True, key=f"{state_prefix}chart_4h")
            with tab_1d:
                df_subset = df_1d.tail(TF_PARAMS["1d"]["limit"])
                st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1d", "NW_Ust_1d", f"{coin_title} - 1d Grafik"), use_container_width=True, key=f"{state_prefix}chart_1d")

            st.markdown("---")
            st.write("🎯 **Canlı Sinyal DCA Yönetim Kartı**")
            fee_protected = atr_tp_distance > (ATR_TP_MULT * atr_k3)
            tp_note = " (komisyon koruması devrede)" if fee_protected else ""
            st.caption(f"Kar-Al: {atr_tp_distance:.2f} mesafe{tp_note} · Stop-Loss: {ATR_SL_MULT}x ATR (Kademe 3, ATR: {atr_k3:.2f})")
            col_l, col_s = st.columns(2)
            with col_l:
                st.info("📈 LONG KADEMELERİ")
                k1_status = f"✅ Alındı ({st.session_state[f'{state_prefix}l_avg_price']:.2f})" if st.session_state[f"{state_prefix}l_status"][0] else f"⏳ Bekliyor ({nw_alt_5m:.2f})"
                k2_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][1] else f"⏳ Bekliyor ({nw_alt_1h:.2f})"
                k3_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][2] else f"⏳ Bekliyor ({nw_alt_4h:.2f})"
                st.write(f"**{l1_lbl}:** {k1_status}"); st.write(f"**{l2_lbl}:** {k2_status}"); st.write(f"**{l3_lbl}:** {k3_status}")
                if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                    l_avg_disp = st.session_state[f'{state_prefix}l_avg_price']
                    st.success(f"🟢 **KAR-AL:** `{l_avg_disp + atr_tp_distance:.2f}`")
                    if st.session_state[f"{state_prefix}l_status"][2]:
                        st.error(f"🔴 **STOP-LOSS:** `{l_avg_disp - (ATR_SL_MULT * atr_k3):.2f}`")

            with col_s:
                st.error("📉 SHORT KADEMELERİ")
                s_k1_status = f"✅ Açıldı ({st.session_state[f'{state_prefix}s_avg_price']:.2f})" if st.session_state[f"{state_prefix}s_status"][0] else f"⏳ Bekliyor ({nw_ust_5m:.2f})"
                s_k2_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][1] else f"⏳ Bekliyor ({nw_ust_1h:.2f})"
                s_k3_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][2] else f"⏳ Bekliyor ({nw_ust_4h:.2f})"
                st.write(f"**{s1_lbl}:** {s_k1_status}"); st.write(f"**{s2_lbl}:** {s_k2_status}"); st.write(f"**{s3_lbl}:** {s_k3_status}")
                if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                    s_avg_disp = st.session_state[f'{state_prefix}s_avg_price']
                    st.success(f"🟢 **KAR-AL:** `{s_avg_disp - atr_tp_distance:.2f}`")
                    if st.session_state[f"{state_prefix}s_status"][2]:
                        st.error(f"🔴 **STOP-LOSS:** `{s_avg_disp + (ATR_SL_MULT * atr_k3):.2f}`")

            st.markdown("---")
            liq_days = 7 if is_volatile else 3
            st.subheader(f"🎯 {liq_days} Günlük {selected_symbol.split('/')[0]} Tahmini Likidasyon Yoğunluk Haritası")
            st.caption(f"⚠️ Gerçek borsa likidasyon verisi değildir. Son {liq_days * 24} saatin mum verisine göre, yaygın kaldıraç seviyelerinin (10x/25x/50x/100x) çakıştığı olası yoğunlaşma noktalarının tahminidir.")
            col_liq_l, col_liq_s = st.columns(2)
            with col_liq_l:
                st.info("🔴 LONG LİKİDASYON HAVUZLARI")
                if not df_long_liq.empty: st.table(df_long_liq.reset_index(drop=True))
            with col_liq_s:
                st.error("🟢 SHORT LİKİDASYON HAVUZLARI")
                if not df_short_liq.empty: st.table(df_short_liq.reset_index(drop=True))

        with col_right:
            st.subheader(f"📊 Kyoun · {coin_title} Canlı Terminal")
            tr_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)
            st.caption(f"🕒 Son veri güncellemesi: {tr_time.strftime('%H:%M:%S')} (TR)")

            if live_trading_enabled:
                st.error("🔴 CANLI MOD: Sinyaller gerçek MEXC futures emri olarak gönderiliyor!")
            else:
                st.info("📝 KAĞIT MOD: Sinyaller simüle ediliyor, gerçek emir gönderilmiyor.")

            col_live_p, col_live_c = st.columns(2)
            col_live_p.metric(label="Anlık Fiyat (USDT)", value=f"${current_price:,.2f}")
            col_live_c.metric(label="24 Saatlik Değişim", value=f"{price_change_24h:+.2f}%")

            if manual_lock:
                st.warning("🔒 SEVİYELER DONDURULDU: Kademeler el ile kilitlendi.")
            else:
                st.success("🔓 CANLI TAKİP AKTİF")

            st.markdown("---")
            st.write(f"**Piyasa Durumu:** {market_state_label}")
            st.caption(f"Aktif Motor: {active_engine_name}")
            st.caption(f"Fiyat: {'Yüksek Oynaklık' if price_is_volatile else 'Normal/Düşük'} · Hacim: {'Ortalama Üstü' if volume_confirms else 'Ortalama Altı'}")

            st.markdown("---")
            col_t1, col_t2 = st.columns(2)
            col_t1.metric(label="4h Genel Trend", value=trend_4h)
            col_t2.metric(label="Pozisyon Yönü Uyarısı", value="SHORT'a Dikkat" if trend_4h == "YUKARI (BOĞA)" else "LONG'a Dikkat")
            if trend_4h == "YUKARI (BOĞA)": st.success(f"🛡️ {warning_msg}")
            else: st.error(f"🛡️ {warning_msg}")
        
            st.markdown("---")
            st.write(f"🎯 **Aktif Kademe RSI Filtreleri**")
            col_fa, col_fb, col_fc = st.columns(3)
            for col, lbl, rsi_v, rsi_p, db, dbr in zip([col_fa, col_fb, col_fc], [l1_lbl, l2_lbl, l3_lbl], [rsi_k1, rsi_k2, rsi_k3], [rsi_k1_prev, rsi_k2_prev, rsi_k3_prev], div_bull_per_kademe, div_bear_per_kademe):
                with col:
                    # Long (Alış) için RSI filtresi devre dışı bırakıldı
                    long_ok = "Devre Dışı"
                    short_ok = "✅" if (rsi_p > RSI_OVERBOUGHT and rsi_v <= RSI_OVERBOUGHT) else "❌"
                    st.write(f"**{lbl}**")
                    st.code(f"RSI: {rsi_v:.1f}")
                    st.caption(f"L: {long_ok}  S: {short_ok}")
                    div_text = []
                    if db: div_text.append("🟢")
                    if dbr: div_text.append("🔴")
                    st.caption(f"Iraksama: {' '.join(div_text) if div_text else '—'}")

            st.markdown("---")
            st.write("💼 **Açık Pozisyonlar**")

            l_active = sum(st.session_state[f"{state_prefix}l_status"]) > 0
            s_active = sum(st.session_state[f"{state_prefix}s_status"]) > 0

            if not l_active and not s_active:
                st.caption("Şu anda açık pozisyon yok. Kademe seviyelerinden biri tetiklenince burada görünecek.")
            else:
                if l_active:
                    l_avg = st.session_state[f"{state_prefix}l_avg_price"]
                    l_amt = st.session_state[f"{state_prefix}l_crypto"]
                    l_pnl_usd = (current_price - l_avg) * l_amt
                    l_pnl_pct = ((current_price / l_avg) - 1) * 100 if l_avg > 0 else 0.0
                    l_kademe = sum(st.session_state[f"{state_prefix}l_status"])
                    st.markdown(f"**📈 LONG** — {l_kademe}/3 kademe açık")
                    pl1, pl2, pl3 = st.columns(3)
                    pl1.metric("Maliyet Ort.", f"${l_avg:,.2f}")
                    pl2.metric("Miktar", f"{l_amt:.6f} {coin_title.split('/')[0]}")
                    pl3.metric("K/Z", f"${l_pnl_usd:+,.2f}", f"{l_pnl_pct:+.2f}%")

                if s_active:
                    s_avg = st.session_state[f"{state_prefix}s_avg_price"]
                    s_amt = st.session_state[f"{state_prefix}s_crypto"]
                    s_pnl_usd = (s_avg - current_price) * s_amt
                    s_pnl_pct = ((s_avg - current_price) / s_avg) * 100 if s_avg > 0 else 0.0
                    s_kademe = sum(st.session_state[f"{state_prefix}s_status"])
                    st.markdown(f"**📉 SHORT** — {s_kademe}/3 kademe açık")
                    ps1, ps2, ps3 = st.columns(3)
                    ps1.metric("Maliyet Ort.", f"${s_avg:,.2f}")
                    ps2.metric("Miktar", f"{s_amt:.6f} {coin_title.split('/')[0]}")
                    ps3.metric("K/Z", f"${s_pnl_usd:+,.2f}", f"{s_pnl_pct:+.2f}%")

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
