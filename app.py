import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import time
import datetime
import requests
from supabase import create_client, Client

# ================= TEMEL AYARLAR =================
BOT_LEVERAGE = 200  # MEXC BTC/USDT futures için kullanılacak kaldıraç (cross margin)
MEXC_TAKER_FEE_PCT = 0.0002  # %0.02 - market emirleri her zaman taker sayılır
MIN_PROFIT_SAFETY_MULT = 3.0  # Kar-al mesafesi, round-trip komisyonun en az bu katı olmalı
RSI_MIDPOINT = 50  # NW bandı dokunduğunda RSI'nin hangi tarafta olması gerektiği eşiği

TF_PARAMS = {
    "1m":  {"limit": 90,  "h": 6, "rsi_period": 7,  "std_window": 15},
    "5m":  {"limit": 100, "h": 7, "rsi_period": 9,  "std_window": 18},
    "15m": {"limit": 110, "h": 8, "rsi_period": 9,  "std_window": 20},
    "1h":  {"limit": 120, "h": 8, "rsi_period": 14, "std_window": 20},
    "4h":  {"limit": 90,  "h": 7, "rsi_period": 14, "std_window": 18},
    "1d":  {"limit": 60,  "h": 6, "rsi_period": 14, "std_window": 14},
}

# DCA: volatiliteye göre dinamik zaman d ilimi + büyük miktarlar (uzun vadeli ortalama düşürme)
DCA_AMOUNTS = [0.0001, 0.0004, 0.0015]   # 1:4:15 oranı, toplam 0.0020 BTC
# Scalp: her zaman sabit kısa zaman dilimi + aynı miktarlar, ayrı/bağımsız pozisyon
SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015]  # toplam 0.0020 BTC
SCALP_TIMEFRAMES = ["1m", "5m", "15m"]    # Scalp her zaman bu üçünü kullanır, mod fark etmez

ATR_TP_MULT, ATR_SL_MULT = 1.0, 1.5

# MEXC Futures (Vadeli) bağlantısı. API key/secret st.secrets üzerinden okunur.
MEXC_API_KEY = st.secrets.get("MEXC_API_KEY", "")
MEXC_API_SECRET = st.secrets.get("MEXC_API_SECRET", "")
VIEWER_PASSWORD = "dca2026"
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

# Telegram ve Supabase kimlik bilgileri st.secrets üzerinden okunur.
telegram_token = st.secrets.get("TELEGRAM_TOKEN", "")
telegram_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
supabase_url = st.secrets.get("SUPABASE_URL", "")
supabase_key = st.secrets.get("SUPABASE_KEY", "")
supabase: Client = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

# ================= GİRİŞ EKRANI =================
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct:
        return True

    st.markdown(
        """
        <style>
        @keyframes sheepBounce {
            0%, 100% { transform: translateY(0) rotate(-4deg); }
            50% { transform: translateY(-6px) rotate(4deg); }
        }
        .sheep-emoji { display: inline-block; animation: sheepBounce 2.2s ease-in-out infinite; }
        div[data-testid="stForm"] {
            max-width: 380px;
            margin: 0 auto;
        }
        div[data-testid="stForm"] div[data-testid="InputInstructions"] {
            display: none !important;
        }
        div[data-testid="stForm"] input[type="password"] {
            padding-right: 2.6rem !important;
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
                if user_password == VIEWER_PASSWORD:
                    st.session_state.password_correct = True
                    st.session_state.user_role = "viewer"
                    st.rerun()
                elif ADMIN_PASSWORD and user_password == ADMIN_PASSWORD:
                    st.session_state.password_correct = True
                    st.session_state.user_role = "admin"
                    st.rerun()
                else:
                    st.error("❌ Hatalı Şifre! Erişim reddedildi.")
    return False

if not check_password():
    st.stop()

st.set_page_config(page_title="Kyoun | DCA & Scalp Hedging Terminal", layout="wide")

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
    section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
        gap: 0.3rem !important;
    }
    [data-testid="stMain"] h3 {
        font-size: 1.1rem !important;
        margin-top: 0.6rem !important;
        margin-bottom: 0.3rem !important;
    }
    [data-testid="stMain"] .stMarkdown p {
        font-size: 0.88rem !important;
        line-height: 1.4 !important;
    }
    section[data-testid="stSidebar"] .stRadio > div {
        gap: 0.15rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ================= MATEMATİKSEL FONKSİYONLAR =================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    high, low, close = df["Yuksek"], df["Dusuk"], df["Kapanis"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

def detect_rsi_divergence(closes, rsis):
    if len(closes) < 15 or len(rsis) < 15:
        return False, False
    c, r = closes[-15:], rsis[-15:]
    lows = [i for i in range(1, len(c)-1) if c[i] < c[i-1] and c[i] < c[i+1]]
    bull = len(lows) >= 2 and c[lows[-1]] < c[lows[-2]] and r[lows[-1]] > r[lows[-2]] and r[lows[-1]] < 45
    highs = [i for i in range(1, len(c)-1) if c[i] > c[i-1] and c[i] > c[i+1]]
    bear = len(highs) >= 2 and c[highs[-1]] > c[highs[-2]] and r[highs[-1]] < r[highs[-2]] and r[highs[-1]] > 55
    return bull, bear

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
    # EWM (üstel ağırlıklı) standart sapma kullanılır - klasik rolling().std() ile
    # MATEMATİKSEL OLARAK AYNI MANTIK (yine standart sapma + sabit 3.0 çarpan),
    # tek fark: rolling() sabit genişlikte bir "kare pencere" kullandığı için bir
    # spike pencereden tam çıktığı anda bandı ANİDEN daraltır (test edildi: 20 barlık
    # pencerede spike +19'da hâlâ şişik, +20'de aniden eski seviyeye düşüyor). EWM ise
    # aynı std_window'u "span" olarak kullanarak eşdeğer bir hafıza süresi sağlar, ama
    # etkiyi KADEMELİ olarak söndürür - ani sıçrama yerine yumuşak bir geçiş olur.
    df["Sapma_Std"] = df["Fark"].ewm(span=std_window, min_periods=std_window).std()
    df[f"NW_Ust{col_suffix}"] = df["NW_Merkez"] + (std_multiplier * df["Sapma_Std"])
    df[f"NW_Alt{col_suffix}"] = df["NW_Merkez"] - (std_multiplier * df["Sapma_Std"])
    return df

def fetch_with_retry(fetch_fn, max_retries=2, base_delay=0.5):
    """
    MEXC API çağrılarını geçici hatalara (ağ kesintisi, 429 rate limit, MEXC'in
    kendi 5XX sunucu hataları) karşı dayanıklı hale getirir. Bu, "arada server
    hatası veriyor" şikayetinin ana çözümüdür - tek seferlik geçici bir hata artık
    fragment'i tamamen başarısız kılmıyor, kısa bir bekleme ile otomatik tekrar dener.
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return fetch_fn()
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(base_delay * (attempt + 1))
    raise last_error

def fetch_tf_data(symbol, tf):
    """Bir zaman dilimi için OHLCV çekip NW/RSI/ATR'yi hesaplar. Tüm zaman
    dilimi bazlı işlemler bu tek fonksiyondan geçer - DCA ve Scalp aynı veriyi
    aynı şekilde hesaplar, kod tekrarı ve tutarsızlık riski ortadan kalkar."""
    p = TF_PARAMS[tf]
    raw = fetch_with_retry(lambda: exchange.fetch_ohlcv(symbol, tf, limit=p["limit"]))
    df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
    df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
    df = calculate_nw_bands(df, 3.0, f"_{tf}", h=p["h"], std_window=p["std_window"])
    df["RSI"] = calculate_rsi(df["Kapanis"], period=p["rsi_period"])
    df["ATR"] = calculate_atr(df, period=14)
    return df

@st.cache_data(ttl=300)
def get_btc_funding_rate():
    try:
        fr_data = fetch_with_retry(lambda: exchange.fetch_funding_rate("BTC/USDT:USDT"))
        return {
            "rate": fr_data.get("fundingRate"),
            "next_rate": fr_data.get("nextFundingRate"),
            "next_time": fr_data.get("nextFundingTimestamp") or fr_data.get("fundingTimestamp"),
            "mark_price": fr_data.get("markPrice"),
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:150]}"}

@st.cache_data(ttl=300)
def estimate_liquidation_pools(symbol, is_volatile=False):
    """TAHMİNİ likidasyon haritası - gerçek borsa verisi değildir. Son N saatin
    mum verisine göre, yaygın kaldıraç seviyelerinin (10x/25x/50x/100x) çakıştığı
    olası yoğunlaşma noktalarını tahmin eder. Pencere: sakin modda 3 gün, volatil
    modda 7 gün (kademe sisteminin volatil modda 1 güne kadar çıkmasıyla tutarlı)."""
    try:
        lookback_hours = 168 if is_volatile else 72
        raw = fetch_with_retry(lambda: exchange.fetch_ohlcv(symbol, "1h", limit=lookback_hours))
        df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        highs, lows, volumes = df["Yuksek"].values, df["Dusuk"].values, df["Hacim"].values
        current_p = df.iloc[-1]["Kapanis"]
        round_step = 50.0 if current_p > 10000 else (1.0 if current_p > 100 else (0.1 if current_p > 1 else 0.01))
        leverage_levels = {10: 0.05, 25: 0.02, 50: 0.01, 100: 0.005}

        long_pools, short_pools = {}, {}
        for i in range(len(df)):
            for lev, pct in leverage_levels.items():
                p_long = round((lows[i] * (1 - pct)) / round_step) * round_step
                long_pools.setdefault(p_long, {"volume": 0.0, "leverages": set()})
                long_pools[p_long]["volume"] += volumes[i]
                long_pools[p_long]["leverages"].add(lev)
                p_short = round((highs[i] * (1 + pct)) / round_step) * round_step
                short_pools.setdefault(p_short, {"volume": 0.0, "leverages": set()})
                short_pools[p_short]["volume"] += volumes[i]
                short_pools[p_short]["leverages"].add(lev)

        def score(d):
            return d["volume"] * len(d["leverages"])

        sl = sorted(long_pools.items(), key=lambda x: score(x[1]), reverse=True)[:4]
        ss = sorted(short_pools.items(), key=lambda x: score(x[1]), reverse=True)[:4]
        sl.sort(key=lambda x: x[0], reverse=True)
        ss.sort(key=lambda x: x[0])
        avg_vol = df["Hacim"].mean()

        def label(d, emoji):
            n_lev, hi_vol = len(d["leverages"]), d["volume"] > avg_vol * 1.5
            if n_lev >= 3 and hi_vol:
                return f"{emoji*3} ÇOK YÜKSEK"
            elif n_lev >= 2 or hi_vol:
                return f"{emoji*2} YÜKSEK"
            return f"{emoji} ORTA"

        return (
            pd.DataFrame([{"Likidasyon Fiyatı": f"${p:,.2f}", "Çakışan Kaldıraç": "/".join(f"{l}x" for l in sorted(d["leverages"])), "Yoğunluk": label(d, "🔴")} for p, d in sl]),
            pd.DataFrame([{"Likidasyon Fiyatı": f"${p:,.2f}", "Çakışan Kaldıraç": "/".join(f"{l}x" for l in sorted(d["leverages"])), "Yoğunluk": label(d, "🟢")} for p, d in ss])
        )
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

def send_telegram_msg(message):
    if not telegram_token or not telegram_chat_id:
        return
    signed = f"🐑 *Kyoun*\n{message}"
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": telegram_chat_id, "text": signed, "parse_mode": "Markdown"})
    except Exception:
        pass

def place_futures_order(symbol, side, amount, leverage=None, is_live=False, reduce_only=False):
    """MEXC Futures emir gönderme. Kağıt modda hiçbir gerçek emir göndermez.
    Canlı modda göndermeden önce miktarın MEXC'in minimum/kontrat kuralına
    (0.0001 BTC'nin tam katı) uyup uymadığını doğrular."""
    if leverage is None:
        leverage = BOT_LEVERAGE
    if not is_live:
        return {"paper": True, "symbol": symbol, "side": side, "amount": amount, "status": "simulated"}

    MIN_ORDER_SIZE = 0.0001
    contracts = amount / MIN_ORDER_SIZE
    if amount < MIN_ORDER_SIZE or abs(contracts - round(contracts)) > 1e-6:
        return {"paper": False, "status": "error", "error": f"Geçersiz miktar: {amount} BTC, MEXC minimum {MIN_ORDER_SIZE} BTC'nin tam katı olmalı"}

    try:
        params = {"leverage": leverage, "marginMode": "cross"}
        if reduce_only:
            params["reduceOnly"] = True
        order = exchange.create_order(symbol, "market", side, amount, None, params)
        return {"paper": False, "status": "success", "order": order}
    except Exception as e:
        return {"paper": False, "status": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}

# ================= GRAFİK ÇİZİM =================
import plotly.graph_objects as go

PLOTLY_CONFIG = {
    "displaylogo": False,
    "scrollZoom": True,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d", "hoverClosestCartesian", "hoverCompareCartesian", "toggleSpikelines"],
    "displayModeBar": True,
}

def draw_plotly_chart(df_subset, price_col, alt_band_col, ust_band_col, title, l_avg=0.0, s_avg=0.0):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=df_subset[alt_band_col], name="Alt Band (Alış)",
                              line=dict(color='rgba(0, 230, 118, 0.85)', width=1.6, dash='dot')))
    fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=df_subset[ust_band_col], name="Üst Band (Satış)",
                              line=dict(color='rgba(255, 61, 87, 0.85)', width=1.6, dash='dot'),
                              fill='tonexty', fillcolor='rgba(120, 130, 255, 0.045)'))
    fig.add_trace(go.Candlestick(x=df_subset["Zaman"], open=df_subset["Acilis"], high=df_subset["Yuksek"],
                                  low=df_subset["Dusuk"], close=df_subset[price_col], name="Fiyat (OHLC)",
                                  increasing=dict(line=dict(color='#0ECB81', width=1), fillcolor='#0ECB81'),
                                  decreasing=dict(line=dict(color='#F6465D', width=1), fillcolor='#F6465D'),
                                  whiskerwidth=0.4))
    if l_avg > 0:
        fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=[l_avg]*len(df_subset), name="Long Maliyet Ort.",
                                  line=dict(color='#00E676', width=1.3, dash='longdash')))
    if s_avg > 0:
        fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=[s_avg]*len(df_subset), name="Short Maliyet Ort.",
                                  line=dict(color='#FF5252', width=1.3, dash='longdash')))

    last_price = df_subset[price_col].iloc[-1]
    fig.add_hline(y=last_price, line=dict(color='rgba(255,255,255,0.35)', width=1, dash='dot'),
                  annotation_text=f" {last_price:,.2f} ", annotation_position="right",
                  annotation_font=dict(color='#0B0E11', size=11, family="Arial Black"),
                  annotation_bgcolor='#F0B90B', annotation_borderpad=3, annotation_xshift=38)

    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", font=dict(size=15, color='#E8EAED', family="Arial"), x=0.01, xanchor='left', y=0.99, yanchor='top'),
        template="plotly_dark", plot_bgcolor='#0B0E11', paper_bgcolor='#0B0E11',
        font=dict(color='#B7BDC6', family="Arial"), margin=dict(l=10, r=85, t=85, b=10),
        height=420, bargap=0.25, xaxis_rangeslider_visible=False, hovermode="x unified",
        hoverlabel=dict(bgcolor='#1E2329', font_size=12, font_family="Arial", bordercolor='#2B3139'),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0.0, bgcolor='rgba(0,0,0,0)', font=dict(size=11, color='#B7BDC6')),
        dragmode='pan', spikedistance=-1, hoverdistance=100
    )
    fig.update_xaxes(showgrid=True, gridcolor='rgba(240, 185, 11, 0.06)', showline=True, linewidth=1, linecolor='#2B3139', mirror=True,
                      showspikes=True, spikecolor='#F0B90B', spikethickness=1, spikedash='solid', spikemode='across', spikesnap='cursor',
                      tickfont=dict(color='#9098A1', size=11))
    fig.update_yaxes(showgrid=True, gridcolor='rgba(240, 185, 11, 0.06)', showline=True, linewidth=1, linecolor='#2B3139', mirror=True,
                      side='right', showspikes=True, spikecolor='#F0B90B', spikethickness=1, spikedash='solid', spikemode='across', spikesnap='cursor',
                      tickfont=dict(color='#D1D4DC', size=12), automargin=True)
    return fig

# ================= ORTAK STATE ŞEMASI =================
# DCA ve Scalp AYNI state şemasını kullanır, sadece state_key_prefix farklıdır.
# Bu, iki stratejinin kodunun birbirinden kopyalanıp tutarsız hale gelmesini önler.
selected_symbol = "BTC/USDT:USDT"
coin_title = selected_symbol.split(':')[0]
base_prefix = f"{selected_symbol}_"

def empty_position_state():
    return {
        "l_status": [False, False, False], "l_entry_prices": [0.0, 0.0, 0.0],
        "l_crypto": 0.0, "l_usd_spent": 0.0, "l_avg_price": 0.0,
        "s_status": [False, False, False], "s_entry_prices": [0.0, 0.0, 0.0],
        "s_crypto": 0.0, "s_usd_spent": 0.0, "s_avg_price": 0.0,
    }

def load_state(strategy_key):
    """strategy_key: 'dca' veya 'scalp'. Her ikisi de Supabase'de tek bir satırda,
    farklı kolon önekleriyle (dca_ / scalp_) saklanır."""
    prefix = f"{base_prefix}{strategy_key}_"
    if f"{prefix}loaded" in st.session_state:
        return prefix

    defaults = empty_position_state()
    loaded = False
    db_error = None
    if supabase:
        try:
            q = supabase.table("bot_state").select("*").eq("coin_symbol", selected_symbol).order("id", descending=True).limit(1).execute()
            if q.data:
                d = q.data[0]
                col = lambda name: f"{strategy_key}_{name}"
                defaults["l_status"] = [d.get(col(f"l_status_{i}"), False) for i in range(3)]
                defaults["l_entry_prices"] = [d.get(col(f"l_entry_{i}"), 0.0) for i in range(3)]
                defaults["l_crypto"] = d.get(col("l_crypto"), 0.0)
                defaults["l_usd_spent"] = d.get(col("l_usd_spent"), 0.0)
                defaults["l_avg_price"] = d.get(col("l_avg_price"), 0.0)
                defaults["s_status"] = [d.get(col(f"s_status_{i}"), False) for i in range(3)]
                defaults["s_entry_prices"] = [d.get(col(f"s_entry_{i}"), 0.0) for i in range(3)]
                defaults["s_crypto"] = d.get(col("s_crypto"), 0.0)
                defaults["s_usd_spent"] = d.get(col("s_usd_spent"), 0.0)
                defaults["s_avg_price"] = d.get(col("s_avg_price"), 0.0)
                st.session_state[f"{base_prefix}balance_usd"] = d.get("balance_usd", 100.0)
                st.session_state[f"{base_prefix}log_history"] = d.get("log_history") or []
                st.session_state[f"{base_prefix}trade_history"] = d.get("trade_history") or []
                st.session_state[f"{base_prefix}manual_lock_db"] = d.get("manual_lock", False)
                st.session_state[f"{prefix}locked_prices"] = d.get(col("locked_prices"))
                loaded = True
        except Exception as e:
            # ÖNEMLİ: Hata artık sessizce yutulmuyor. Eğer Supabase'den veri
            # çekilemezse (eksik kolon, bağlantı sorunu, yetki hatası vb.), bu
            # durum kullanıcıya açıkça gösterilir - aksi halde "geçmiş sıfırlandı"
            # sanılan durumun gerçek sebebi (DB hatası) hiç görülemezdi.
            db_error = f"{type(e).__name__}: {str(e)[:200]}"

    for k, v in defaults.items():
        st.session_state[f"{prefix}{k}"] = v
    if not loaded:
        st.session_state.setdefault(f"{base_prefix}balance_usd", 100.0)
        st.session_state.setdefault(f"{base_prefix}log_history", [])
        st.session_state.setdefault(f"{base_prefix}trade_history", [])
        st.session_state.setdefault(f"{base_prefix}manual_lock_db", False)
        if db_error:
            st.session_state[f"{base_prefix}db_load_error"] = db_error
    st.session_state.setdefault(f"{prefix}locked_prices", None)
    st.session_state[f"{prefix}loaded"] = True
    return prefix

def save_state_to_db():
    if not supabase:
        return
    try:
        data = {"coin_symbol": selected_symbol,
                "balance_usd": st.session_state.get(f"{base_prefix}balance_usd", 100.0),
                "log_history": st.session_state.get(f"{base_prefix}log_history", []),
                "trade_history": st.session_state.get(f"{base_prefix}trade_history", []),
                "manual_lock": st.session_state.get("live_manual_lock_toggle", False)}
        for strategy_key in ("dca", "scalp"):
            prefix = f"{base_prefix}{strategy_key}_"
            col = lambda name: f"{strategy_key}_{name}"
            st_data = st.session_state
            data[col("l_crypto")] = st_data.get(f"{prefix}l_crypto", 0.0)
            data[col("l_usd_spent")] = st_data.get(f"{prefix}l_usd_spent", 0.0)
            data[col("l_avg_price")] = st_data.get(f"{prefix}l_avg_price", 0.0)
            data[col("s_crypto")] = st_data.get(f"{prefix}s_crypto", 0.0)
            data[col("s_usd_spent")] = st_data.get(f"{prefix}s_usd_spent", 0.0)
            data[col("s_avg_price")] = st_data.get(f"{prefix}s_avg_price", 0.0)
            data[col("locked_prices")] = st_data.get(f"{prefix}locked_prices")
            l_status = st_data.get(f"{prefix}l_status", [False, False, False])
            s_status = st_data.get(f"{prefix}s_status", [False, False, False])
            l_entries = st_data.get(f"{prefix}l_entry_prices", [0.0, 0.0, 0.0])
            s_entries = st_data.get(f"{prefix}s_entry_prices", [0.0, 0.0, 0.0])
            for i in range(3):
                data[col(f"l_status_{i}")] = l_status[i]
                data[col(f"s_status_{i}")] = s_status[i]
                data[col(f"l_entry_{i}")] = l_entries[i]
                data[col(f"s_entry_{i}")] = s_entries[i]
        supabase.table("bot_state").upsert(data).execute()
    except Exception as e:
        st.error(f"Veritabanı kaydı başarısız: {type(e).__name__}: {str(e)[:200]}")

def record_trade(strategy_label, direction, exit_reason, entry_price, exit_price, amount, pnl_usd, pnl_pct, is_live):
    trade_record = {
        "zaman": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "strateji": strategy_label, "yon": direction, "sebep": exit_reason,
        "giris_fiyati": round(entry_price, 2), "cikis_fiyati": round(exit_price, 2),
        "miktar": round(amount, 6), "pnl_usd": round(pnl_usd, 4), "pnl_pct": round(pnl_pct, 4),
        "mod": "Canlı" if is_live else "Kağıt",
    }
    st.session_state.setdefault(f"{base_prefix}trade_history", []).append(trade_record)

# ================= ORTAK KADEMELİ POZİSYON MOTORU =================
# Hem DCA hem Scalp BU TEK fonksiyonu kullanır. Davranış farkı sadece dışarıdan
# verilen parametrelerden gelir: hangi zaman dilimleri, hangi miktarlar, hangi
# etiket. Mantığın kendisi (kademe sırası, RSI onayı, ATR bazlı kar-al/stop-loss,
# komisyon güvenliği) HER İKİ STRATEJİ İÇİN BİREBİR AYNIDIR.
def run_staged_strategy(strategy_key, strategy_label, prefix, current_price, dfs_by_tf, amounts, is_live, manual_lock=False, allow_new_entries=True):
    """
    dfs_by_tf: {tf_name: dataframe} - 3 kademe için kullanılacak, [k1_df, k2_df, k3_df] sırasıyla.
    amounts: [k1_miktar, k2_miktar, k3_miktar] BTC cinsinden.
    Döner: (nw_alt_levels, nw_ust_levels, rsi_levels, labels, active_engine_desc)
    """
    tf_names = list(dfs_by_tf.keys())
    dfk = list(dfs_by_tf.values())

    raw_alt = [df.iloc[-2][f"NW_Alt_{tf}"] for df, tf in zip(dfk, tf_names)]
    raw_ust = [df.iloc[-2][f"NW_Ust_{tf}"] for df, tf in zip(dfk, tf_names)]
    atr_vals = [df.iloc[-2]["ATR"] for df in dfk]

    # GELİŞMİŞ KADEME SİSTEMİ: Önceden K2/K3, K1'den sadece yapay/sabit bir %0.3
    # mesafede olacak şekilde ZORLANIYORDU - bantlar gerçekte birbirine çok yakınsa
    # bile kademe "ayrışmış" sayılıyordu. Artık her kademenin GERÇEK NW bandı
    # kullanılır; bir sonraki kademe, öncekinden MIN_STAGE_GAP_ATR_MULT x ATR kadar
    # gerçekten ayrışana kadar "hazır değil" sayılır ve fiyat o seviyeye gelse de
    # açılmaz - sabırla bir sonraki gerçek Nadaraya-Watson değeri beklenir.
    MIN_STAGE_GAP_ATR_MULT = 0.5
    alt_base = [raw_alt[0]]
    alt_ready = [True]
    min_gaps_alt = [0.0]
    for i in range(1, 3):
        min_gap = MIN_STAGE_GAP_ATR_MULT * atr_vals[i]
        gap = alt_base[-1] - raw_alt[i]
        alt_base.append(raw_alt[i])
        alt_ready.append(gap >= min_gap)
        min_gaps_alt.append(min_gap)
    ust_base = [raw_ust[0]]
    ust_ready = [True]
    min_gaps_ust = [0.0]
    for i in range(1, 3):
        min_gap = MIN_STAGE_GAP_ATR_MULT * atr_vals[i]
        gap = raw_ust[i] - ust_base[-1]
        ust_base.append(raw_ust[i])
        ust_ready.append(gap >= min_gap)
        min_gaps_ust.append(min_gap)

    l_status = st.session_state[f"{prefix}l_status"]
    s_status = st.session_state[f"{prefix}s_status"]
    l_entries = st.session_state[f"{prefix}l_entry_prices"]
    s_entries = st.session_state[f"{prefix}s_entry_prices"]

    nw_alt = [l_entries[i] if l_status[i] else alt_base[i] for i in range(3)]
    nw_ust = [s_entries[i] if s_status[i] else ust_base[i] for i in range(3)]

    if manual_lock:
        lock_key = f"{prefix}locked_prices"
        if st.session_state.get(lock_key) is None:
            st.session_state[lock_key] = {"alt": nw_alt, "ust": nw_ust, "alt_ready": alt_ready, "ust_ready": ust_ready}
            save_state_to_db()
        locked = st.session_state[lock_key]
        nw_alt = locked["alt"]
        nw_ust = locked["ust"]
        # Eski kayıtlarda (yeni alanlar eklenmeden önce) alt_ready/ust_ready
        # olmayabilir - geriye dönük uyumluluk için güvenli varsayılan kullanılır.
        alt_ready = locked.get("alt_ready", alt_ready)
        ust_ready = locked.get("ust_ready", ust_ready)
    else:
        st.session_state[f"{prefix}locked_prices"] = None

    rsi_vals = [df.iloc[-2]["RSI"] for df in dfk]
    rsi_prev_vals = [df.iloc[-3]["RSI"] for df in dfk]
    atr_k3 = dfk[2].iloc[-2]["ATR"]

    round_trip_fee_pct = 2 * MEXC_TAKER_FEE_PCT
    min_tp_distance = current_price * round_trip_fee_pct * MIN_PROFIT_SAFETY_MULT
    raw_tp_distance = ATR_TP_MULT * atr_k3
    tp_distance = max(raw_tp_distance, min_tp_distance)
    scale_factor = tp_distance / raw_tp_distance if raw_tp_distance > 0 else 1.0
    sl_distance = ATR_SL_MULT * atr_k3 * scale_factor

    # --- LONG ÇIKIŞ (sadece K3 alındıysa stop-loss aktif) ---
    if sum(l_status) > 0:
        avg = st.session_state[f"{prefix}l_avg_price"]
        amt = st.session_state[f"{prefix}l_crypto"]
        usd_spent = st.session_state[f"{prefix}l_usd_spent"]
        tp = avg + tp_distance
        sl = avg - sl_distance
        exit_reason = None
        if l_status[2] and current_price <= sl:
            exit_reason = "Stop-Loss"
        elif current_price >= tp:
            exit_reason = "Kar-Al"
        if exit_reason:
            order_result = place_futures_order(selected_symbol, "sell", amt, is_live=is_live, reduce_only=True)
            pnl_usd = (current_price - avg) * amt
            pnl_pct = ((current_price / avg) - 1) * 100 if avg > 0 else 0.0
            margin_used = usd_spent / BOT_LEVERAGE
            st.session_state[f"{base_prefix}balance_usd"] += margin_used + pnl_usd
            mode_tag = "🔴 CANLI" if is_live else "📝 KAĞIT"
            note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
            emoji = "🔴" if exit_reason == "Stop-Loss" else "🟢"
            msg = f"{emoji} *[{mode_tag}] {strategy_label} LONG {exit_reason} ({coin_title})*\nMaliyet Ort.: {avg:.2f}\nKapanış: {current_price:.2f}\nMiktar: {amt:.6f} BTC\nK/Z: {pnl_usd:+.4f} USDT ({pnl_pct:+.2f}%){note}"
            send_telegram_msg(msg)
            st.session_state[f"{base_prefix}log_history"].append(msg)
            record_trade(strategy_label, "LONG", exit_reason, avg, current_price, amt, pnl_usd, pnl_pct, is_live)
            st.session_state[f"{prefix}l_crypto"], st.session_state[f"{prefix}l_usd_spent"], st.session_state[f"{prefix}l_avg_price"] = 0.0, 0.0, 0.0
            st.session_state[f"{prefix}l_status"] = [False, False, False]
            st.session_state[f"{prefix}l_entry_prices"] = [0.0, 0.0, 0.0]
            save_state_to_db()
            l_status = st.session_state[f"{prefix}l_status"]

    # --- SHORT ÇIKIŞ ---
    if sum(s_status) > 0:
        avg = st.session_state[f"{prefix}s_avg_price"]
        amt = st.session_state[f"{prefix}s_crypto"]
        usd_spent = st.session_state[f"{prefix}s_usd_spent"]
        tp = avg - tp_distance
        sl = avg + sl_distance
        exit_reason = None
        if s_status[2] and current_price >= sl:
            exit_reason = "Stop-Loss"
        elif current_price <= tp:
            exit_reason = "Kar-Al"
        if exit_reason:
            order_result = place_futures_order(selected_symbol, "buy", amt, is_live=is_live, reduce_only=True)
            pnl_ratio = (avg - current_price) / avg if avg > 0 else 0.0
            pnl_usd = usd_spent * pnl_ratio
            pnl_pct = pnl_ratio * 100
            margin_used = usd_spent / BOT_LEVERAGE
            st.session_state[f"{base_prefix}balance_usd"] += margin_used + pnl_usd
            mode_tag = "🔴 CANLI" if is_live else "📝 KAĞIT"
            note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
            emoji = "🔴" if exit_reason == "Stop-Loss" else "🟢"
            msg = f"{emoji} *[{mode_tag}] {strategy_label} SHORT {exit_reason} ({coin_title})*\nMaliyet Ort.: {avg:.2f}\nKapanış: {current_price:.2f}\nMiktar: {amt:.6f} BTC\nK/Z: {pnl_usd:+.4f} USDT ({pnl_pct:+.2f}%){note}"
            send_telegram_msg(msg)
            st.session_state[f"{base_prefix}log_history"].append(msg)
            record_trade(strategy_label, "SHORT", exit_reason, avg, current_price, amt, pnl_usd, pnl_pct, is_live)
            st.session_state[f"{prefix}s_crypto"], st.session_state[f"{prefix}s_usd_spent"], st.session_state[f"{prefix}s_avg_price"] = 0.0, 0.0, 0.0
            st.session_state[f"{prefix}s_status"] = [False, False, False]
            st.session_state[f"{prefix}s_entry_prices"] = [0.0, 0.0, 0.0]
            save_state_to_db()
            s_status = st.session_state[f"{prefix}s_status"]

    # --- LONG GİRİŞ (sıralı kademe, RSI onaylı, GERÇEK bant ayrışması beklenir) ---
    for idx in range(3):
        if not allow_new_entries:
            break
        rsi_ok = rsi_vals[idx] < RSI_MIDPOINT
        can_enter = (idx == 0 or l_status[idx-1]) and not l_status[idx]
        band_ready = alt_ready[idx]
        if current_price <= nw_alt[idx] and rsi_ok and can_enter and band_ready:
            val = amounts[idx]
            order_result = place_futures_order(selected_symbol, "buy", val, is_live=is_live)
            margin_used = (val * current_price) / BOT_LEVERAGE
            st.session_state[f"{base_prefix}balance_usd"] -= margin_used
            st.session_state[f"{prefix}l_crypto"] += val
            st.session_state[f"{prefix}l_usd_spent"] += val * current_price
            st.session_state[f"{prefix}l_status"][idx] = True
            st.session_state[f"{prefix}l_entry_prices"][idx] = current_price
            st.session_state[f"{prefix}l_avg_price"] = st.session_state[f"{prefix}l_usd_spent"] / st.session_state[f"{prefix}l_crypto"]
            mode_tag = "🔴 CANLI" if is_live else "📝 KAĞIT"
            note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
            msg = f"📈 *[{mode_tag}] {strategy_label} LONG K{idx+1} SATIN ALINDI ({coin_title})*\nFiyat: {current_price:.2f}\nMiktar: {val:.6f} BTC\nRSI: {rsi_vals[idx]:.1f} (<{RSI_MIDPOINT}){note}"
            send_telegram_msg(msg)
            st.session_state[f"{base_prefix}log_history"].append(msg)
            save_state_to_db()
            break

    # --- SHORT GİRİŞ (GERÇEK bant ayrışması beklenir) ---
    for idx in range(3):
        if not allow_new_entries:
            break
        rsi_ok = rsi_vals[idx] > RSI_MIDPOINT
        can_enter = (idx == 0 or s_status[idx-1]) and not s_status[idx]
        band_ready = ust_ready[idx]
        if current_price >= nw_ust[idx] and rsi_ok and can_enter and band_ready:
            val = amounts[idx]
            order_result = place_futures_order(selected_symbol, "sell", val, is_live=is_live)
            margin_used = (val * current_price) / BOT_LEVERAGE
            st.session_state[f"{base_prefix}balance_usd"] -= margin_used
            st.session_state[f"{prefix}s_crypto"] += val
            st.session_state[f"{prefix}s_usd_spent"] += val * current_price
            st.session_state[f"{prefix}s_status"][idx] = True
            st.session_state[f"{prefix}s_entry_prices"][idx] = current_price
            st.session_state[f"{prefix}s_avg_price"] = st.session_state[f"{prefix}s_usd_spent"] / st.session_state[f"{prefix}s_crypto"]
            mode_tag = "🔴 CANLI" if is_live else "📝 KAĞIT"
            note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
            msg = f"📈 *[{mode_tag}] {strategy_label} SHORT K{idx+1} AÇILDI ({coin_title})*\nFiyat: {current_price:.2f}\nMiktar: {val:.6f} BTC\nRSI: {rsi_vals[idx]:.1f} (>{RSI_MIDPOINT}){note}"
            send_telegram_msg(msg)
            st.session_state[f"{base_prefix}log_history"].append(msg)
            save_state_to_db()
            break

    return {
        "nw_alt": nw_alt, "nw_ust": nw_ust, "rsi_vals": rsi_vals, "rsi_prev_vals": rsi_prev_vals,
        "tf_names": tf_names, "tp_distance": tp_distance, "sl_distance": sl_distance, "atr_k3": atr_k3,
        "alt_ready": alt_ready, "ust_ready": ust_ready, "min_gaps_alt": min_gaps_alt, "min_gaps_ust": min_gaps_ust,
    }

def close_position_manual(strategy_label, prefix, direction, current_price, is_live):
    """LONG veya SHORT pozisyonu manuel olarak (kullanıcı butonu) kapatır."""
    side_field = "l" if direction == "LONG" else "s"
    avg = st.session_state[f"{prefix}{side_field}_avg_price"]
    amt = st.session_state[f"{prefix}{side_field}_crypto"]
    usd_spent = st.session_state[f"{prefix}{side_field}_usd_spent"]
    if amt <= 0:
        return
    close_side = "sell" if direction == "LONG" else "buy"
    order_result = place_futures_order(selected_symbol, close_side, amt, is_live=is_live, reduce_only=True)
    if direction == "LONG":
        pnl_usd = (current_price - avg) * amt
        pnl_pct = ((current_price / avg) - 1) * 100 if avg > 0 else 0.0
    else:
        pnl_ratio = (avg - current_price) / avg if avg > 0 else 0.0
        pnl_usd = usd_spent * pnl_ratio
        pnl_pct = pnl_ratio * 100
    margin_used = usd_spent / BOT_LEVERAGE
    st.session_state[f"{base_prefix}balance_usd"] += margin_used + pnl_usd
    mode_tag = "🔴 CANLI" if is_live else "📝 KAĞIT"
    note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
    msg = f"✋ *[{mode_tag}] {strategy_label} {direction} MANUEL KAPATILDI ({coin_title})*\nMaliyet Ort.: {avg:.2f}\nKapanış: {current_price:.2f}\nMiktar: {amt:.6f} BTC\nK/Z: {pnl_usd:+.4f} USDT ({pnl_pct:+.2f}%){note}"
    send_telegram_msg(msg)
    st.session_state[f"{base_prefix}log_history"].append(msg)
    record_trade(strategy_label, direction, "Manuel Kapatma", avg, current_price, amt, pnl_usd, pnl_pct, is_live)
    st.session_state[f"{prefix}{side_field}_crypto"], st.session_state[f"{prefix}{side_field}_usd_spent"], st.session_state[f"{prefix}{side_field}_avg_price"] = 0.0, 0.0, 0.0
    st.session_state[f"{prefix}{side_field}_status"] = [False, False, False]
    st.session_state[f"{prefix}{side_field}_entry_prices"] = [0.0, 0.0, 0.0]
    save_state_to_db()

# ================= STATE YÜKLEME =================
dca_prefix = load_state("dca")
scalp_prefix = load_state("scalp")
is_admin = st.session_state.get("user_role") == "admin"

# ================= SIDEBAR (sade, sadece ayarlar) =================
st.sidebar.markdown("## 🐑 Kyoun")
role_label = "👑 Yönetici" if is_admin else "👁️ İzleyici"
st.sidebar.caption(f"BTC/USDT Futures · Giriş: {role_label}")
if st.sidebar.button("🚪 Çıkış Yap", key="logout_button_global", use_container_width=True):
    st.session_state.password_correct = False
    st.session_state.user_role = None
    st.rerun()

db_load_error = st.session_state.get(f"{base_prefix}db_load_error")
if db_load_error:
    st.sidebar.error(f"⚠️ Veritabanından geçmiş veri yüklenemedi:\n{db_load_error}\n\nBu pencere boyunca geçici/sıfır state ile çalışılıyor.")

st.sidebar.divider()
st.sidebar.markdown("**⚙️ İşlem Modu**")
api_keys_present = bool(MEXC_API_KEY and MEXC_API_SECRET)
if not is_admin:
    st.sidebar.caption("👁️ İzleyici: Canlı Mod kilitli.")
elif not api_keys_present:
    st.sidebar.caption("⚠️ API anahtarı yok: Sadece Kağıt Mod.")
trading_mode = st.sidebar.radio("Mod", options=["📝 Kağıt Mod", "🔴 Canlı Mod"], index=0,
                                  key="trading_mode_radio", disabled=not (is_admin and api_keys_present), label_visibility="collapsed")
live_trading_enabled = trading_mode.startswith("🔴") and api_keys_present and is_admin
if live_trading_enabled:
    st.sidebar.error("🔴 CANLI — gerçek emir gönderilecek!")
    if not st.sidebar.checkbox("Riskleri anladım, onaylıyorum", key="live_trading_confirm_checkbox"):
        live_trading_enabled = False
else:
    st.sidebar.caption("📝 Sinyaller simüle ediliyor, gerçek emir yok.")

st.sidebar.divider()
st.sidebar.markdown("**🎯 Aktif Strateji**")
dca_has_position = sum(st.session_state[f"{dca_prefix}l_status"]) > 0 or sum(st.session_state[f"{dca_prefix}s_status"]) > 0
scalp_has_position = sum(st.session_state[f"{scalp_prefix}l_status"]) > 0 or sum(st.session_state[f"{scalp_prefix}s_status"]) > 0
if not is_admin:
    st.sidebar.caption("🔒 Sadece yönetici değiştirebilir.")
selected_mode_radio = st.sidebar.radio("Strateji", options=["📊 DCA (Kademeli)", "⚡ Scalp (Kademeli, Hızlı)"],
                                        index=0, key="strategy_mode_radio", label_visibility="collapsed", disabled=not is_admin)
selected_mode = "DCA" if selected_mode_radio.startswith("📊") else "SCALP"
if dca_has_position and selected_mode == "SCALP":
    st.sidebar.caption("📊 DCA açık — Scalp yeni emir açamaz.")
elif scalp_has_position and selected_mode == "DCA":
    st.sidebar.caption("⚡ Scalp açık — DCA yeni emir açamaz.")

manual_lock = st.sidebar.toggle("🔒 Seviyeleri Dondur", value=st.session_state.get(f"{base_prefix}manual_lock_db", False), key="live_manual_lock_toggle", disabled=not is_admin)
if is_admin and manual_lock != st.session_state.get(f"{base_prefix}manual_lock_db", False):
    st.session_state[f"{base_prefix}manual_lock_db"] = manual_lock
    if not manual_lock:
        st.session_state[f"{base_prefix}locked_prices"] = None
    save_state_to_db()

st.sidebar.divider()
col_b1, col_b2 = st.sidebar.columns(2)
if col_b1.button("🔔 Test", key="telegram_test_btn", use_container_width=True, disabled=not is_admin):
    send_telegram_msg("👋 *Bağlantı Testi:* Başarılı!")
    st.sidebar.success("Gönderildi!")
if col_b2.button("🔴 Sıfırla", key="reset_all_btn", use_container_width=True, disabled=not is_admin):
    for strategy_key in ("dca", "scalp"):
        prefix = f"{base_prefix}{strategy_key}_"
        for k, v in empty_position_state().items():
            st.session_state[f"{prefix}{k}"] = v
    st.session_state[f"{base_prefix}balance_usd"] = 100.0
    st.session_state[f"{base_prefix}locked_prices"] = None
    save_state_to_db()
    st.rerun()

st.sidebar.divider()
btc_funding = get_btc_funding_rate()
if btc_funding.get("rate") is not None:
    rate_pct = btc_funding["rate"] * 100.0
    fr_color = "green" if rate_pct < 0 else "red"
    st.sidebar.caption(f"💸 Fonlama: :{fr_color}[{rate_pct:+.4f}%]")

# ================= ÜST PERFORMANS ÇUBUĞU (her zaman görünür) =================
st.markdown(
    """
    <style>
    .kyoun-topbar { display:flex; gap:0; padding:0; margin-bottom:0.6rem; }
    div[data-testid="stMetric"] { background:#161B22; border:1px solid #2A2E37; border-radius:10px; padding:10px 14px; }
    div[data-testid="stMetricLabel"] { font-size:0.78rem; }
    /* Sidebar ile ana içerik arası boşluğu sıkılaştır */
    [data-testid="stMainBlockContainer"] { padding-top: 1.2rem !important; }
    section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] { gap: 0.4rem; }
    /* Kademe durumu kutularındaki uzun metinlerin taşmasını önle, satır aralığını düzelt */
    div[data-testid="stVerticalBlockBorderWrapper"] p { line-height: 1.45 !important; }
    /* Canlı nabız animasyonu */
    @keyframes pulse-dot {
        0%   { box-shadow: 0 0 0 0 rgba(46, 204, 113, 0.7); }
        70%  { box-shadow: 0 0 0 6px rgba(46, 204, 113, 0); }
        100% { box-shadow: 0 0 0 0 rgba(46, 204, 113, 0); }
    }
    .live-pulse {
        display: inline-block; width: 10px; height: 10px; border-radius: 50%;
        background: #2ecc71; animation: pulse-dot 1.8s infinite; margin-right: 6px;
        vertical-align: middle;
    }
    .live-status-bar {
        display: flex; align-items: center; justify-content: space-between;
        background: #161B22; border: 1px solid #2A2E37; border-radius: 10px;
        padding: 8px 16px; margin-bottom: 0.8rem; font-size: 0.85rem; color: #B7BDC6;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Canlı durum çubuğu + üst metrikler - ayrı bir fragment olarak çalışır (1s),
# böylece "Sistem Aktif" göstergesi ve saat gerçekten canlı kalır, sayfa tam
# yenilenmeden de güncellenir. dca_fragment/scalp_fragment her başarılı tarama
# sonunda kendi zaman damgasını (dca_last_success / scalp_last_success) yazar;
# bu fragment o damgaları okuyup "kaç saniye önce güncellendi" bilgisini gösterir.
@st.fragment(run_every="1s")
def status_bar_fragment():
    now_tr = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)
    mode_text = "🔴 CANLI MOD" if live_trading_enabled else "📝 Kağıt Mod"

    dca_last = st.session_state.get("dca_last_success")
    scalp_last = st.session_state.get("scalp_last_success")
    now_epoch = time.time()
    dca_age = f"{int(now_epoch - dca_last)}s önce" if dca_last else "bekleniyor..."
    scalp_age = f"{int(now_epoch - scalp_last)}s önce" if scalp_last else "bekleniyor..."
    # 25 saniyeden fazla güncelleme yoksa (2.5 tarama döngüsü kaçmışsa) uyarı rengi.
    dca_stale = dca_last is None or (now_epoch - dca_last) > 25
    scalp_stale = scalp_last is None or (now_epoch - scalp_last) > 25
    dca_dot = "#e74c3c" if dca_stale else "#2ecc71"
    scalp_dot = "#e74c3c" if scalp_stale else "#2ecc71"

    st.markdown(
        f"""
        <div class="live-status-bar">
            <div><span class="live-pulse"></span><b>Sistem Aktif</b> · Saat: <b>{now_tr.strftime('%H:%M:%S')}</b> (TR) · {mode_text}</div>
            <div>📊 DCA: <span style="color:{dca_dot}">●</span> {dca_age} &nbsp;&nbsp; ⚡ Scalp: <span style="color:{scalp_dot}">●</span> {scalp_age}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    trade_history_all = st.session_state.get(f"{base_prefix}trade_history", [])
    total_pnl_all = sum(t["pnl_usd"] for t in trade_history_all) if trade_history_all else 0.0
    balance_now = st.session_state.get(f"{base_prefix}balance_usd", 100.0)
    dca_pos = sum(st.session_state.get(f"{dca_prefix}l_status", [False]*3)) > 0 or sum(st.session_state.get(f"{dca_prefix}s_status", [False]*3)) > 0
    scalp_pos = sum(st.session_state.get(f"{scalp_prefix}l_status", [False]*3)) > 0 or sum(st.session_state.get(f"{scalp_prefix}s_status", [False]*3)) > 0

    top1, top2, top3, top4, top5 = st.columns(5)
    top1.metric("💳 Bakiye", f"${balance_now:,.2f}")
    top2.metric("📈 Toplam K/Z", f"${total_pnl_all:+,.4f}")
    top3.metric("📊 DCA Pozisyon", "Açık" if dca_pos else "Yok")
    top4.metric("⚡ Scalp Pozisyon", "Açık" if scalp_pos else "Yok")
    top5.metric("🎯 Aktif Mod", selected_mode)

status_bar_fragment()
st.divider()

# ================= ORTAK LİKİDASYON HARİTASI (açılan pencere/popover) =================
# Ana ekranı sade tutmak için ayrı bir popover'da gösterilir, hem DCA hem Scalp
# panelinde aynı buton/pencere kullanılır - kod tekrarı ve görsel tutarsızlık olmaz.
def render_liquidity_popover(is_volatile, key_ns):
    days_label = "7" if is_volatile else "3"
    with st.popover(f"🎯 Tahmini Likidasyon Haritası ({days_label} günlük)", use_container_width=True):
        df_long_liq, df_short_liq = estimate_liquidation_pools(selected_symbol, is_volatile)
        st.caption("⚠️ Gerçek borsa verisi değildir. Yaygın kaldıraç seviyelerinin (10x/25x/50x/100x) çakıştığı olası yoğunlaşma noktalarının tahminidir.")
        st.caption(f"Pencere: sakin piyasada 3 gün, volatil piyasada 7 gün (şu an: {days_label} gün)")
        cliq1, cliq2 = st.columns(2)
        with cliq1:
            st.markdown("**🔴 LONG Havuzları**")
            if not df_long_liq.empty:
                st.dataframe(df_long_liq.reset_index(drop=True), hide_index=True, use_container_width=True, key=f"{key_ns}_liq_long_df")
            else:
                st.caption("Veri yok.")
        with cliq2:
            st.markdown("**🟢 SHORT Havuzları**")
            if not df_short_liq.empty:
                st.dataframe(df_short_liq.reset_index(drop=True), hide_index=True, use_container_width=True, key=f"{key_ns}_liq_short_df")
            else:
                st.caption("Veri yok.")

# ================= ORTAK PANEL RENDER FONKSİYONU =================
# DCA ve Scalp AYNI görsel yapıyı kullanır: Grafik -> Kademe Durumu -> Açık
# Pozisyon Özeti -> (varsa) Manuel Kapat. Görsel tutarsızlık böylece imkansız hale gelir.
def render_strategy_panel(strategy_label, prefix, current_price, chart_dfs, tf_keys, labels, result, is_live, key_ns):
    l_status = st.session_state[f"{prefix}l_status"]
    s_status = st.session_state[f"{prefix}s_status"]
    l_avg = st.session_state[f"{prefix}l_avg_price"]
    s_avg = st.session_state[f"{prefix}s_avg_price"]
    l_crypto = st.session_state[f"{prefix}l_crypto"]
    s_crypto = st.session_state[f"{prefix}s_crypto"]

    col_chart, col_side = st.columns([1.7, 1])

    with col_chart:
        tabs = st.tabs([f"⏱️ {tf}" for tf in tf_keys])
        for tab, tf in zip(tabs, tf_keys):
            with tab:
                df_subset = chart_dfs[tf].tail(TF_PARAMS[tf]["limit"])
                st.plotly_chart(
                    draw_plotly_chart(df_subset, "Kapanis", f"NW_Alt_{tf}", f"NW_Ust_{tf}", f"{coin_title} - {tf}", l_avg, s_avg),
                    use_container_width=True, key=f"{key_ns}_chart_{tf}", config=PLOTLY_CONFIG
                )

        st.markdown("##### 🪜 Kademe Durumu")
        col_kl, col_ks = st.columns(2)
        with col_kl:
            st.caption("📈 LONG")
            for i in range(3):
                if l_status[i]:
                    st.success(f"✅ {labels[i]} — Alındı @ {st.session_state[f'{prefix}l_entry_prices'][i]:,.2f}")
                elif not result["alt_ready"][i]:
                    needed = result["nw_alt"][i-1] - result["min_gaps_alt"][i]
                    with st.container(border=True):
                        st.write(f"🔸 **{labels[i]}** — Bant: {result['nw_alt'][i]:,.2f}")
                        st.caption(f"{labels[i-1]}'den henüz ayrışmadı · en az {needed:,.2f} altına inmeli")
                else:
                    st.container(border=True).write(f"⏳ {labels[i]} — Bekliyor @ {result['nw_alt'][i]:,.2f}")
        with col_ks:
            st.caption("📉 SHORT")
            for i in range(3):
                if s_status[i]:
                    st.success(f"✅ {labels[i]} — Açıldı @ {st.session_state[f'{prefix}s_entry_prices'][i]:,.2f}")
                elif not result["ust_ready"][i]:
                    needed = result["nw_ust"][i-1] + result["min_gaps_ust"][i]
                    with st.container(border=True):
                        st.write(f"🔸 **{labels[i]}** — Bant: {result['nw_ust'][i]:,.2f}")
                        st.caption(f"{labels[i-1]}'den henüz ayrışmadı · en az {needed:,.2f} üstüne çıkmalı")
                else:
                    st.container(border=True).write(f"⏳ {labels[i]} — Bekliyor @ {result['nw_ust'][i]:,.2f}")

    with col_side:
        st.markdown(f"##### 💼 {strategy_label} Açık Pozisyon")
        has_long = sum(l_status) > 0
        has_short = sum(s_status) > 0

        if not has_long and not has_short:
            st.info("Şu an açık pozisyon yok. Kademe sinyali geldiğinde otomatik açılacak.")
        else:
            if has_long:
                pnl_usd = (current_price - l_avg) * l_crypto
                pnl_pct = ((current_price / l_avg) - 1) * 100 if l_avg > 0 else 0.0
                with st.container(border=True):
                    st.markdown(f"**📈 LONG** · {sum(l_status)}/3 kademe")
                    cL1, cL2 = st.columns(2)
                    cL1.metric("Maliyet Ort.", f"${l_avg:,.2f}")
                    cL2.metric("Miktar", f"{l_crypto:.6f} BTC")
                    st.metric("Anlık K/Z", f"${pnl_usd:+,.4f}", f"{pnl_pct:+.2f}%")
                    st.caption(f"🟢 Kar-Al: {l_avg + result['tp_distance']:,.2f}" + (f" · 🔴 Stop: {l_avg - result['sl_distance']:,.2f}" if l_status[2] else " · Stop: K3'te aktif olacak"))
                    if st.button("✋ LONG Kapat", key=f"{key_ns}_close_long", disabled=not is_admin, use_container_width=True):
                        close_position_manual(strategy_label, prefix, "LONG", current_price, is_live)
                        st.rerun(scope="fragment")
            if has_short:
                pnl_ratio = (s_avg - current_price) / s_avg if s_avg > 0 else 0.0
                s_usd_spent = st.session_state[f"{prefix}s_usd_spent"]
                pnl_usd = s_usd_spent * pnl_ratio
                pnl_pct = pnl_ratio * 100
                with st.container(border=True):
                    st.markdown(f"**📉 SHORT** · {sum(s_status)}/3 kademe")
                    cS1, cS2 = st.columns(2)
                    cS1.metric("Maliyet Ort.", f"${s_avg:,.2f}")
                    cS2.metric("Miktar", f"{s_crypto:.6f} BTC")
                    st.metric("Anlık K/Z", f"${pnl_usd:+,.4f}", f"{pnl_pct:+.2f}%")
                    st.caption(f"🟢 Kar-Al: {s_avg - result['tp_distance']:,.2f}" + (f" · 🔴 Stop: {s_avg + result['sl_distance']:,.2f}" if s_status[2] else " · Stop: K3'te aktif olacak"))
                    if st.button("✋ SHORT Kapat", key=f"{key_ns}_close_short", disabled=not is_admin, use_container_width=True):
                        close_position_manual(strategy_label, prefix, "SHORT", current_price, is_live)
                        st.rerun(scope="fragment")

        st.markdown("##### 🎯 RSI Filtreleri")
        rsi_cols = st.columns(3)
        for i, col in enumerate(rsi_cols):
            with col:
                long_ok = "✅" if result["rsi_vals"][i] < RSI_MIDPOINT else "❌"
                short_ok = "✅" if result["rsi_vals"][i] > RSI_MIDPOINT else "❌"
                st.caption(labels[i])
                st.code(f"{result['rsi_vals'][i]:.1f}")
                st.caption(f"L:{long_ok} S:{short_ok}")

# ================= DCA FRAGMENT =================
@st.fragment(run_every="10s")
def dca_fragment():
    try:
        live_ticker = fetch_with_retry(lambda: exchange.fetch_ticker(selected_symbol))
        current_price = live_ticker.get('last') or live_ticker.get('close') or 0.0
        price_change_24h = live_ticker.get('percentage') or 0.0

        df_1m = fetch_tf_data(selected_symbol, "1m")
        df_5m = fetch_tf_data(selected_symbol, "5m")
        df_15m = fetch_tf_data(selected_symbol, "15m")
        df_1h = fetch_tf_data(selected_symbol, "1h")
        df_4h = fetch_tf_data(selected_symbol, "4h")
        df_1d = fetch_tf_data(selected_symbol, "1d")

        raw_4h_trend = fetch_with_retry(lambda: exchange.fetch_ohlcv(selected_symbol, "4h", limit=250))
        df_4h_trend = pd.DataFrame(raw_4h_trend, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_4h_trend["EMA_200"] = df_4h_trend["Kapanis"].ewm(span=200, adjust=False).mean()
        trend_4h = "YUKARI (BOĞA)" if df_4h_trend.iloc[-1]["Kapanis"] > df_4h_trend.iloc[-1]["EMA_200"] else "AŞAĞI (AYI)"

        price_std_now = df_15m["Kapanis"].rolling(20).std().iloc[-1]
        price_std_median = df_15m["Kapanis"].rolling(20).std().median()
        vol_now = df_15m["Hacim"].rolling(20).mean().iloc[-1]
        vol_median = df_15m["Hacim"].rolling(20).mean().median()
        price_is_volatile = price_std_now > price_std_median
        volume_confirms = vol_now > vol_median
        is_volatile = price_is_volatile and volume_confirms

        if is_volatile:
            market_state_label = "⚡ VOLATİL (Hacim Onaylı)"
            market_state_short = "⚡ Volatil"
            dfs_by_tf = {"15m": df_15m, "1h": df_1h, "1d": df_1d}
            tf_keys = ["15m", "1h", "1d"]
            labels = ["K1 (15m)", "K2 (1h)", "K3 (1d)"]
        else:
            reason = "Fiyat Oynak/Hacim Düşük" if price_is_volatile else "Yatay Salınım"
            market_state_label = f"💤 SAKİN ({reason})"
            market_state_short = "💤 Sakin"
            dfs_by_tf = {"1m": df_1m, "5m": df_5m, "15m": df_15m}
            tf_keys = ["1m", "5m", "15m"]
            labels = ["K1 (1m)", "K2 (5m)", "K3 (15m)"]

        result = run_staged_strategy("dca", "DCA", dca_prefix, current_price, dfs_by_tf, DCA_AMOUNTS, live_trading_enabled, manual_lock, allow_new_entries=(selected_mode == "DCA"))
        chart_dfs = {"1m": df_1m, "5m": df_5m, "15m": df_15m, "1h": df_1h, "4h": df_4h, "1d": df_1d}

        info1, info2, info3, info4 = st.columns(4)
        info1.metric("Anlık Fiyat", f"${current_price:,.2f}", f"{price_change_24h:+.2f}%")
        info2.metric("Piyasa Durumu", market_state_short)
        info3.metric("4h Trend", trend_4h)
        info4.metric("Son Güncelleme", (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)).strftime('%H:%M:%S'))
        st.caption(f"Aktif Motor: {' / '.join(tf_keys)} hiyerarşisi · Kar-Al mesafe: {result['tp_distance']:.2f} · Stop-Loss mesafe: {result['sl_distance']:.2f}")

        render_strategy_panel("DCA", dca_prefix, current_price, chart_dfs, ["1m", "5m", "15m", "1h", "4h", "1d"], labels, result, live_trading_enabled, "dca")
        render_liquidity_popover(is_volatile, "dca")
        st.session_state["dca_last_success"] = time.time()

    except Exception as e:
        st.error(f"DCA hatası, 10s sonra tekrar denenecek: {type(e).__name__}: {str(e)[:200]}")
        try:
            has_pos = sum(st.session_state[f"{dca_prefix}l_status"]) > 0 or sum(st.session_state[f"{dca_prefix}s_status"]) > 0
            if has_pos:
                last_warn = st.session_state.get(f"{base_prefix}dca_last_warn", 0)
                if time.time() - last_warn > 300:
                    send_telegram_msg(f"⚠️ *DCA BOT HATA ALDI* ({type(e).__name__})\nAçık pozisyonunuz var, kontrol edemiyor.")
                    st.session_state[f"{base_prefix}dca_last_warn"] = time.time()
        except Exception:
            pass
        time.sleep(5)

# ================= SCALP FRAGMENT =================
@st.fragment(run_every="10s")
def scalp_fragment():
    try:
        live_ticker = fetch_with_retry(lambda: exchange.fetch_ticker(selected_symbol))
        current_price = live_ticker.get('last') or live_ticker.get('close') or 0.0
        price_change_24h = live_ticker.get('percentage') or 0.0

        df_1m = fetch_tf_data(selected_symbol, "1m")
        df_5m = fetch_tf_data(selected_symbol, "5m")
        df_15m = fetch_tf_data(selected_symbol, "15m")
        dfs_by_tf = {"1m": df_1m, "5m": df_5m, "15m": df_15m}
        labels = ["K1 (1m)", "K2 (5m)", "K3 (15m)"]

        result = run_staged_strategy("scalp", "SCALP", scalp_prefix, current_price, dfs_by_tf, SCALP_AMOUNTS, live_trading_enabled, manual_lock, allow_new_entries=(selected_mode == "SCALP"))
        chart_dfs = {"1m": df_1m, "5m": df_5m, "15m": df_15m}

        info1, info2, info3 = st.columns(3)
        info1.metric("Anlık Fiyat", f"${current_price:,.2f}", f"{price_change_24h:+.2f}%")
        info2.metric("Kar-Al Mesafe", f"${result['tp_distance']:.2f}")
        info3.metric("Stop-Loss Mesafe", f"${result['sl_distance']:.2f}")
        st.caption("Her zaman 1m/5m/15m kullanır (piyasa durumundan bağımsız). DCA ile aynı kademe mantığı, ayrı/bağımsız pozisyon.")

        render_strategy_panel("SCALP", scalp_prefix, current_price, chart_dfs, ["1m", "5m", "15m"], labels, result, live_trading_enabled, "scalp")
        render_liquidity_popover(False, "scalp")  # Scalp her zaman kısa vadeli - sabit 3 günlük pencere
        st.session_state["scalp_last_success"] = time.time()

    except Exception as e:
        st.error(f"Scalp hatası, 10s sonra tekrar denenecek: {type(e).__name__}: {str(e)[:200]}")
        try:
            has_pos = sum(st.session_state[f"{scalp_prefix}l_status"]) > 0 or sum(st.session_state[f"{scalp_prefix}s_status"]) > 0
            if has_pos:
                last_warn = st.session_state.get(f"{base_prefix}scalp_last_warn", 0)
                if time.time() - last_warn > 300:
                    send_telegram_msg(f"⚠️ *SCALP BOT HATA ALDI* ({type(e).__name__})\nAçık pozisyonunuz var, kontrol edemiyor.")
                    st.session_state[f"{base_prefix}scalp_last_warn"] = time.time()
        except Exception:
            pass
        time.sleep(5)

# ================= ANA SEKME YAPISI =================
tab_dca, tab_scalp, tab_history = st.tabs(["📊 DCA", "⚡ Scalp", "📜 İşlem Geçmişi"])

with tab_dca:
    dca_fragment()

with tab_scalp:
    scalp_fragment()

with tab_history:
    st.markdown("##### 📜 İşlem Geçmişi ve Performans")
    trade_history = st.session_state.get(f"{base_prefix}trade_history", [])

    if not trade_history:
        st.info("Henüz kapanmış bir işlem yok.")
    else:
        df_trades = pd.DataFrame(trade_history)
        filter_strategy = st.radio("Filtre", options=["Tümü", "DCA", "SCALP"], horizontal=True, key="history_filter")
        df_filtered = df_trades if filter_strategy == "Tümü" else df_trades[df_trades["strateji"] == filter_strategy]

        if df_filtered.empty:
            st.info("Bu filtreye uygun işlem yok.")
        else:
            total_trades = len(df_filtered)
            winning = len(df_filtered[df_filtered["pnl_usd"] > 0])
            losing = len(df_filtered[df_filtered["pnl_usd"] <= 0])
            win_rate = (winning / total_trades * 100) if total_trades > 0 else 0.0
            total_pnl = df_filtered["pnl_usd"].sum()
            avg_pct = df_filtered["pnl_pct"].mean()

            h1, h2, h3, h4 = st.columns(4)
            h1.metric("Toplam İşlem", total_trades)
            h2.metric("Kazanma Oranı", f"%{win_rate:.1f}", f"{winning}K / {losing}Z")
            h3.metric("Toplam K/Z", f"${total_pnl:+,.4f}", f"Ort. %{avg_pct:+.3f}")
            h4.metric("En İyi / Kötü", f"${df_filtered['pnl_usd'].max():+,.4f}", f"${df_filtered['pnl_usd'].min():+,.4f}")

            df_display = df_filtered.copy()
            df_display["zaman"] = pd.to_datetime(df_display["zaman"])
            df_display = df_display.sort_values("zaman", ascending=False)
            df_display["zaman"] = df_display["zaman"].dt.strftime("%d.%m %H:%M:%S")
            df_display = df_display.rename(columns={
                "zaman": "Zaman", "strateji": "Strateji", "yon": "Yön", "sebep": "Sebep",
                "giris_fiyati": "Giriş", "cikis_fiyati": "Çıkış",
                "miktar": "Miktar (BTC)", "pnl_usd": "K/Z (USDT)", "pnl_pct": "K/Z (%)", "mod": "Mod"
            })
            st.dataframe(df_display, use_container_width=True, hide_index=True, height=380)

            csv_data = df_trades.to_csv(index=False).encode("utf-8")
            col_dl, col_clr = st.columns(2)
            col_dl.download_button("⬇️ CSV İndir", data=csv_data, file_name="kyoun_islem_gecmisi.csv", mime="text/csv", use_container_width=True)
            with col_clr.popover("🗑️ Geçmişi Sil", use_container_width=True, disabled=not is_admin):
                st.warning("Bu işlem geri alınamaz.")
                if st.checkbox("Onaylıyorum, geçmişi tamamen sil", key="confirm_clear_history"):
                    if st.button("Evet, Şimdi Sil", key="clear_history_btn", type="primary", use_container_width=True):
                        st.session_state[f"{base_prefix}trade_history"] = []
                        save_state_to_db()
                        st.rerun()


