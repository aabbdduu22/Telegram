import os
import threading

# ============================================================
# X1 + X2 في ملف واحد
# Railway: شغّل هذا الملف بالأمر: python main.py
# ============================================================

import time
import requests
from datetime import datetime
import statistics

# ==================== إعدادات تيليجرام ====================
TELEGRAM_BOT_TOKEN = "8791638999:AAF1dnN8b0atxyuheGvUQbLfJmCJI_OO8jI"
TELEGRAM_CHAT_ID = "-1004345758550"
CHECK_INTERVAL = 60

# ==================== شروط الفلتر ====================
SURGE_MULTIPLIER = 5.0        # الانفجار = 5x الأساس
REVERSAL_MULTIPLIER = 2.0     # الارتداد = 2x الأساس
MIN_CONFIRMATION_VOL = 300    # أقل عقد في شمعة التأكيد
MIN_RANGE_PCT = 0.05          # أقل نطاق سعري
MIN_BASE_VOL = 5              # أقل أساس
# ===================================================

# فتح جلسة اتصال مستمرة لتقليل استهلاك الإنترنت وتسريع الطلبات
session = requests.Session()

def x1_clean_symbol(symbol):
    """مسح كلمة STOCK من اسم العملة"""
    return symbol.replace("STOCK", "").replace("_USDT", "")

def x1_send_to_channel(text):
    """إرسال رسالة للقناة"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = session.post(url, json=payload, timeout=10)
        result = response.json()
        if not result.get("ok"):
            print(f"  ❌ خطأ تيليجرام: {result.get('description')}")
    except Exception as e:
        print(f"  ❌ خطأ في الإرسال: {e}")

def x1_get_stock_symbols():
    """جلب رموز الأسهم (Stocks) فقط"""
    url = "https://contract.mexc.com/api/v1/contract/detail"
    try:
        res = session.get(url, timeout=5)
        if res.status_code == 200:
            contracts = res.json().get("data", [])
            # التركيز حصراً على العقود التي تحتوي على STOCK و USDT
            return [c.get("symbol") for c in contracts if "STOCK" in c.get("symbol", "") and "USDT" in c.get("symbol", "")]
    except Exception as e:
        print(f"❌ خطأ في جلب العملات: {e}")
    return []

def x1_get_klines(symbol, limit=15):
    """جلب عدد قليل من الشموع (15) لتقليل استهلاك البيانات"""
    url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}?interval=Min1"
    try:
        res = session.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get("data", {})
            times = data.get("time", [])
            opens = data.get("open", [])
            highs = data.get("high", [])
            lows = data.get("low", [])
            closes = data.get("close", [])
            vols = data.get("vol", [])
            
            if len(times) >= limit:
                klines = []
                # جلب آخر N شمعة فقط
                for i in range(len(times) - limit, len(times)):
                    klines.append({
                        "time": int(times[i]),
                        "open": float(opens[i]),
                        "high": float(highs[i]),
                        "low": float(lows[i]),
                        "close": float(closes[i]),
                        "vol": float(vols[i])
                    })
                return klines
    except:
        pass
    return []

def x1_calculate_baseline(historical_klines):
    """حساب الفوليوم الأساسي بناءً على الشموع القديمة"""
    vols = [k["vol"] for k in historical_klines if k["vol"] > 0]
    
    if len(vols) < 5:
        return None
    
    median_vol = statistics.median(vols)
    mean_vol = statistics.mean(vols)
    baseline = max(median_vol, mean_vol * 0.5)
    baseline = max(baseline, MIN_BASE_VOL)
    
    return round(baseline, 1)

def x1_detect_early_surge(klines):
    """رصد التنبيه المبكر: الكشف عن شمعة انفجار أغلقت للتو"""
    # klines[-1] هي الشمعة المفتوحة (تتجاهل)
    # klines[-2] هي الشمعة التي أغلقت للتو
    baseline = x1_calculate_baseline(klines[:-2])
    if not baseline:
        return None
        
    surge = klines[-2]
    
    if surge["vol"] >= baseline * SURGE_MULTIPLIER:
        surge_range = surge["high"] - surge["low"]
        if (surge_range / surge["open"]) * 100 >= MIN_RANGE_PCT:
            direction = "صاعدة 🟢" if surge["close"] > surge["open"] else "هابطة 🔴"
            ratio = round(surge["vol"] / baseline, 1)
            return {"vol": surge["vol"], "ratio": ratio, "direction": direction}
    return None

def x1_detect_opportunity(klines):
    """كشف فرصة مكتملة (انفجار + ارتداد) بناءً على الشموع المغلقة فقط"""
    # klines[-1] الشمعة الحالية (لا نستخدمها)
    # klines[-2] شمعة الارتداد المغلقة
    # klines[-3] شمعة الانفجار المغلقة
    
    historical = klines[:-3]
    baseline = x1_calculate_baseline(historical)
    
    if not baseline:
        return None
    
    surge = klines[-3]
    reversal = klines[-2]
    
    # 1. شروط الانفجار
    if surge["vol"] < baseline * SURGE_MULTIPLIER:
        return None
    surge_range = surge["high"] - surge["low"]
    if (surge_range / surge["open"]) * 100 < MIN_RANGE_PCT:
        return None
    
    # 2. شروط الارتداد
    if reversal["vol"] < MIN_CONFIRMATION_VOL or reversal["vol"] < baseline * REVERSAL_MULTIPLIER:
        return None
    reversal_range = reversal["high"] - reversal["low"]
    if (reversal_range / reversal["open"]) * 100 < MIN_RANGE_PCT:
        return None
    
    # 3. التأكد من انعكاس الاتجاه
    surge_up = surge["close"] > surge["open"]
    reversal_up = reversal["close"] > reversal["open"]
    
    if surge_up == reversal_up:
        return None
    
    surge_ratio = surge["vol"] / baseline
    reversal_ratio = reversal["vol"] / baseline
    
    # تحديد الإعدادات بناءً على الاتجاه
    if not surge_up and reversal_up:
        direction = "🟢 ارتداد صاعد"
        action = "شراء"
        entry = reversal["close"]
        stop_loss = min(surge["low"], reversal["low"])
        target = surge["open"]
    else:
        direction = "🔴 ارتداد هابط"
        action = "بيع"
        entry = reversal["close"]
        stop_loss = max(surge["high"], reversal["high"])
        target = surge["open"]
    
    risk = abs(entry - stop_loss)
    reward = abs(target - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0
    
    return {
        "direction": direction,
        "action": action,
        "surge_vol": surge["vol"],
        "reversal_vol": reversal["vol"],
        "surge_ratio": round(surge_ratio, 1),
        "reversal_ratio": round(reversal_ratio, 1),
        "surge_range": round((surge_range / surge["open"]) * 100, 2),
        "reversal_range": round((reversal_range / reversal["open"]) * 100, 2),
        "entry": round(entry, 4),
        "target": round(target, 4),
        "stop_loss": round(stop_loss, 4),
        "risk_pct": round((risk / entry) * 100, 2),
        "reward_pct": round((reward / entry) * 100, 2),
        "rr": rr
    }

def x1_format_alert(symbol, r):
    """تنسيق رسالة الفرصة المكتملة"""
    name = x1_clean_symbol(symbol)
    stars = "⭐⭐⭐" if r['surge_ratio'] >= 50 else "⭐⭐" if r['surge_ratio'] >= 20 else "⭐"
    
    return (
        f"<b>{r['direction']} - {name}</b> {stars}\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"💥 انفجار: <b>{r['surge_vol']:,.0f}</b> عقد ({r['surge_ratio']}x)\n"
        f"🔄 ارتداد: <b>{r['reversal_vol']:,.0f}</b> عقد ({r['reversal_ratio']}x)\n"
        f"📊 النطاق: {r['surge_range']}% → {r['reversal_range']}%\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"💰 دخول: <b>${r['entry']:.4f}</b>\n"
        f"🎯 هدف: ${r['target']:.4f} (+{r['reward_pct']}%)\n"
        f"🛑 وقف: ${r['stop_loss']:.4f} (-{r['risk_pct']}%)\n"
        f"⚡ R/R: <b>{r['rr']}:1</b>\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"🚀 <b>{r['action']} الآن!</b>"
    )

def x1_scan_and_alert():
    print("="*50)
    print("🔄 بوت الأسهم: انفجار + ارتداد (مع التنبيه المبكر)")
    print("="*50)
    
    x1_send_to_channel("✅ <b>تم تشغيل البوت!</b>\n🔍 جاري مراقبة أسهم (Stocks) للبحث عن سيولة مبكرة...")
    
    symbols = x1_get_stock_symbols()
    if not symbols:
        print("❌ لا توجد أسهم متاحة حالياً.")
        return
    
    print(f"✅ {len(symbols)} سهم للمراقبة\n")
    
    completed_history = {}
    early_history = {}
    
    while True:
        now_str = datetime.now().strftime('%H:%M:%S')
        print(f"🔍 فحص {now_str} ...")
        
        for sym in symbols:
            klines = x1_get_klines(sym, limit=15)
            if not klines or len(klines) < 10:
                time.sleep(0.1) # حماية API
                continue
                
            now = time.time()
            name = x1_clean_symbol(sym)
            
            # 1. فحص التنبيه المبكر (شمعة الانفجار فقط)
            early_surge = x1_detect_early_surge(klines)
            if early_surge:
                # نرسل تنبيه مبكر إذا لم نرسله خلال الـ 3 دقائق الماضية
                if sym not in early_history or (now - early_history[sym]) > 180:
                    early_history[sym] = now
                    msg = (f"👀 <b>مراقبة مبكرة - {name}</b>\n"
                           f"⚡️ انفجار فوليوم ({early_surge['ratio']}x) بشمعة {early_surge['direction']}\n"
                           f"⏳ ننتظر إغلاق الشمعة الحالية للتأكيد...")
                    x1_send_to_channel(msg)
                    print(f"  👀 تنبيه مبكر: {name}")

            # 2. فحص الفرصة المكتملة (انفجار + ارتداد)
            result = x1_detect_opportunity(klines)
            if result:
                # نرسل إشارة الدخول إذا لم نرسلها خلال الـ 5 دقائق الماضية
                if sym not in completed_history or (now - completed_history[sym]) > 300:
                    completed_history[sym] = now
                    x1_send_to_channel(x1_format_alert(sym, result))
                    print(f"  🚨 فرصة مكتملة: {name} | R/R {result['rr']}:1")
            
            # تأخير زمني بسيط جداً لحماية اتصالك من الحظر (Rate Limit)
            time.sleep(0.1)
        
        print("⏳ انتظار لدورة الفحص القادمة...\n")
        time.sleep(CHECK_INTERVAL)

()

import time
import requests
from datetime import datetime
import statistics

# ==================== إعدادات تيليجرام ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CHECK_INTERVAL = 60

# ==================== شروط الفلتر ====================
SURGE_MULTIPLIER = 5.0        # الانفجار = 5x الأساس
REVERSAL_MULTIPLIER = 2.0     # الارتداد = 2x الأساس
MIN_CONFIRMATION_VOL = 300    # أقل عقد في شمعة التأكيد
MIN_RANGE_PCT = 0.05          # أقل نطاق سعري
MIN_BASE_VOL = 5              # أقل أساس
# ===================================================

# جلسة واحدة لتقليل استهلاك الإنترنت
session = requests.Session()

def x2_clean_symbol(symbol):
    """مسح كلمة STOCK من اسم العملة"""
    return symbol.replace("STOCK", "").replace("_USDT", "")

def x2_send_to_channel(text):
    """إرسال رسالة للقناة"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = session.post(url, json=payload, timeout=10)
        result = response.json()
        if result.get("ok"):
            return True
        else:
            print(f"  ❌ خطأ: {result.get('description')}")
            return False
    except Exception as e:
        print(f"  ❌ خطأ: {e}")
        return False

def x2_get_klines(symbol, limit=20):
    """جلب آخر 30 شمعة دقيقة كما في النسخة الأصلية"""
    url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}?interval=Min1"
    try:
        res = session.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get("data", {})
            times = data.get("time", [])
            opens = data.get("open", [])
            highs = data.get("high", [])
            lows = data.get("low", [])
            closes = data.get("close", [])
            vols = data.get("vol", [])
            
            if len(times) >= limit:
                klines = []
                for i in range(len(times) - limit, len(times)):
                    klines.append({
                        "time": int(times[i]),
                        "open": float(opens[i]),
                        "high": float(highs[i]),
                        "low": float(lows[i]),
                        "close": float(closes[i]),
                        "vol": float(vols[i])
                    })
                return klines
    except:
        pass
    return []

def x2_get_stock_symbols():
    url = "https://contract.mexc.com/api/v1/contract/detail"
    try:
        res = session.get(url, timeout=5)
        if res.status_code == 200:
            contracts = res.json().get("data", [])
            # فلترة لأسهم الكريبتو فقط
            return [c.get("symbol") for c in contracts if "STOCK" in c.get("symbol", "") and "USDT" in c.get("symbol", "")]
    except:
        pass
    return []

def x2_calculate_baseline(klines):
    """حساب أساس ذكي (نفس المنطق الأصلي الخاص بك)"""
    historical = klines[:-2]
    vols = [k["vol"] for k in historical if k["vol"] > 0]
    
    if len(vols) < 5:
        return None
    
    median_vol = statistics.median(vols)
    mean_vol = statistics.mean(vols)
    baseline = max(median_vol, mean_vol * 0.5)
    baseline = max(baseline, MIN_BASE_VOL)
    
    return {
        "baseline": round(baseline, 1),
        "mean": round(mean_vol, 1),
        "median": round(median_vol, 1)
    }

def x2_detect_early_surge(klines):
    """إشعار مبكر: يراقب الشمعة الأخيرة (الحالية) لاكتشاف الانفجار قبل الارتداد"""
    if len(klines) < 10:
        return None
        
    historical = klines[:-1]
    vols = [k["vol"] for k in historical if k["vol"] > 0]
    
    if len(vols) < 5:
        return None
        
    median_vol = statistics.median(vols)
    mean_vol = statistics.mean(vols)
    baseline = max(median_vol, mean_vol * 0.5)
    baseline = max(baseline, MIN_BASE_VOL)
    
    surge = klines[-1] # الشمعة الحالية التي تتشكل الآن
    
    if surge["vol"] >= baseline * SURGE_MULTIPLIER:
        surge_range = surge["high"] - surge["low"]
        if (surge_range / surge["open"]) * 100 >= MIN_RANGE_PCT:
            direction = "صاعدة 🟢" if surge["close"] > surge["open"] else "هابطة 🔴"
            ratio = round(surge["vol"] / baseline, 1)
            return {"vol": surge["vol"], "ratio": ratio, "direction": direction}
    return None

def x2_detect_opportunity(klines):
    """كشف انفجار + ارتداد (نفس المنطق الأصلي الخاص بك)"""
    if len(klines) < 10:
        return None
    
    baseline_data = x2_calculate_baseline(klines)
    if not baseline_data:
        return None
    
    baseline = baseline_data["baseline"]
    surge = klines[-2]
    reversal = klines[-1]
    
    # شمعة الانفجار 5x
    if surge["vol"] < baseline * SURGE_MULTIPLIER:
        return None
    
    surge_range = surge["high"] - surge["low"]
    if (surge_range / surge["open"]) * 100 < MIN_RANGE_PCT:
        return None
    
    # شمعة التأكيد: 500 عقد + 2x الأساس
    if reversal["vol"] < MIN_CONFIRMATION_VOL:
        return None
    
    if reversal["vol"] < baseline * REVERSAL_MULTIPLIER:
        return None
    
    reversal_range = reversal["high"] - reversal["low"]
    if (reversal_range / reversal["open"]) * 100 < MIN_RANGE_PCT:
        return None
    
    # اتجاه متعاكس
    surge_up = surge["close"] > surge["open"]
    reversal_up = reversal["close"] > reversal["open"]
    
    if surge_up == reversal_up:
        return None
    
    surge_ratio = surge["vol"] / baseline
    reversal_ratio = reversal["vol"] / baseline
    
    if not surge_up and reversal_up:  # هبوط → صعود
        direction = "🟢 ارتداد صاعد"
        action = "شراء"
        entry = reversal["close"]
        stop_loss = min(surge["low"], reversal["low"])
        target = surge["open"]
    else:  # صعود → هبوط
        direction = "🔴 ارتداد هابط"
        action = "بيع"
        entry = reversal["close"]
        stop_loss = max(surge["high"], reversal["high"])
        target = surge["open"]
    
    risk = abs(entry - stop_loss)
    reward = abs(target - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0
    
    return {
        "direction": direction,
        "action": action,
        "surge_vol": surge["vol"],
        "reversal_vol": reversal["vol"],
        "surge_ratio": round(surge_ratio, 1),
        "reversal_ratio": round(reversal_ratio, 1),
        "baseline": baseline,
        "surge_range": round((surge_range / surge["open"]) * 100, 2),
        "reversal_range": round((reversal_range / reversal["open"]) * 100, 2),
        "entry": round(entry, 4),
        "target": round(target, 4),
        "stop_loss": round(stop_loss, 4),
        "risk_pct": round((risk / entry) * 100, 2),
        "reward_pct": round((reward / entry) * 100, 2),
        "rr": rr
    }

def x2_format_alert(symbol, r):
    """تنسيق الرسالة للقناة"""
    name = x2_clean_symbol(symbol)
    
    if r['surge_ratio'] >= 50:
        stars = "⭐⭐⭐"
    elif r['surge_ratio'] >= 20:
        stars = "⭐⭐"
    else:
        stars = "⭐"
    
    return (
        f"<b>{r['direction']} - {name}</b> {stars}\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"💥 انفجار: <b>{r['surge_vol']:,.0f}</b> عقد ({r['surge_ratio']}x)\n"
        f"🔄 ارتداد: <b>{r['reversal_vol']:,.0f}</b> عقد ({r['reversal_ratio']}x)\n"
        f"📊 النطاق: {r['surge_range']}% → {r['reversal_range']}%\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"💰 دخول: <b>${r['entry']:.4f}</b>\n"
        f"🎯 هدف: ${r['target']:.4f} (+{r['reward_pct']}%)\n"
        f"🛑 وقف: ${r['stop_loss']:.4f} (-{r['risk_pct']}%)\n"
        f"⚡ R/R: <b>{r['rr']}:1</b>\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"🚀 <b>{r['action']} الآن!</b>"
    )

def x2_scan_and_alert():
    print("="*50)
    print(f"🔄 بوت الانفجار + الارتداد (مع ميزة الإشعار المبكر)")
    print(f"📡 القناة: CR")
    print("="*50)
    
    # اختبار الإرسال للتأكد
    print("📡 جاري إرسال إشعار التأكيد...")
    x2_send_to_channel("✅ <b>بوت الفرص يعمل بنجاح!</b>\n🔍 جاري مراقبة أسهم (STOCK) للبحث عن الانفجارات والارتدادات...")
    print("✅ تم إرسال رسالة التأكيد للقناة.\n")
    
    symbols = x2_get_stock_symbols()
    if not symbols:
        print("❌ لا توجد أسهم")
        return
    
    print(f"✅ {len(symbols)} سهم للمراقبة\n")
    
    completed_history = {}
    early_history = {}
    
    while True:
        now_str = datetime.now().strftime('%H:%M:%S')
        print(f"🔍 فحص {now_str}")
        found = 0
        
        for sym in symbols:
            klines = x2_get_klines(sym, limit=30)
            if not klines or len(klines) < 10:
                time.sleep(0.05) # حماية خفيفة للـ API
                continue
            
            now = time.time()
            name = x2_clean_symbol(sym)
            
            # فحص الإشعار المبكر أولاً
            early_result = x2_detect_early_surge(klines)
            if early_result:
                if sym not in early_history or (now - early_history[sym]) > 180:
                    early_history[sym] = now
                    msg = (f"👀 <b>مراقبة مبكرة - {name}</b>\n"
                           f"⚡️ فوليوم غير طبيعي الآن ({early_result['ratio']}x)\n"
                           f"⏳ ننتظر إغلاق شمعة الارتداد للتأكيد...")
                    x2_send_to_channel(msg)
                    print(f"  👀 إشعار مبكر: {name} ({early_result['ratio']}x)")

            # فحص الفرصة المكتملة
            result = x2_detect_opportunity(klines)
            if result:
                if sym in completed_history and (now - completed_history[sym]) < 300:
                    continue
                
                completed_history[sym] = now
                found += 1
                
                print(f"  🚨 {name}: {result['surge_vol']:,.0f} عقد | {result['direction']} | R/R {result['rr']}:1")
                x2_send_to_channel(x2_format_alert(sym, result))
                
            time.sleep(0.05)
        
        if found == 0:
            print(f"  🔕 لا توجد فرص جديدة")
        else:
            print(f"  ✅ تم إرسال {found} فرصة مكتملة")
        
        print(f"⏳ انتظار دقيقة...\n")
        time.sleep(CHECK_INTERVAL)

()

# تشغيل البوتين في نفس الوقت داخل نفس خدمة Railway
if __name__ == "__main__":
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        raise RuntimeError("ضع TELEGRAM_BOT_TOKEN في Railway Variables")
    if not os.getenv("TELEGRAM_CHAT_ID"):
        raise RuntimeError("ضع TELEGRAM_CHAT_ID في Railway Variables")

    print("🚀 تشغيل X1 و X2 معًا...")

    t1 = threading.Thread(target=x1_scan_and_alert, name="X1", daemon=False)
    t2 = threading.Thread(target=x2_scan_and_alert, name="X2", daemon=False)

    t1.start()
    t2.start()

    print("✅ X1 يعمل")
    print("✅ X2 يعمل")

    t1.join()
    t2.join()
