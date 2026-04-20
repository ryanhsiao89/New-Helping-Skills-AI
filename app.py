import streamlit as st
import google.generativeai as genai
from google.generativeai.types import GenerationConfig
import pandas as pd
import time
import re
import random
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

# --- 系統與頁面設定 ---
st.set_page_config(page_title="助人技巧 AI 模擬系統 (教學驗證版)", layout="wide", page_icon="🧑‍🏫")

# ==========================================
# 📧 系統發信帳號設定 (請教師務必在此填寫您的發信帳號)
# ==========================================
SENDER_EMAIL = "ryanhsiao89@gmail.com"  # 填入發信用的 Gmail
SENDER_PASSWORD = "hopehope20151205"  # 填入 16 碼「應用程式密碼」

# --- 🌟 本研究專屬白名單 (學號與信箱綁定) 🌟 ---
WHITELIST = {
    'BB1112067': 'bb1112067@hcu.edu.tw',
    'BB1122013': 'bb1122013@hcu.edu.tw',
    'BB1122034': 'bb1122034@hcu.edu.tw',
    'BB1122053': 'jasminehu0711@gmail.com',
    'BB1125034': 'bb1125034@hcu.edu.tw',
    'GB1132002': 'gb1132002@hcu.edu.tw',
    'GB1142006': 'gb1142006@hcu.edu.tw',
    'KA1140202': 'ka1140202@hcu.edu.tw',
    'KA1140223': 'ka1140223@hcu.edu.tw',
    'KA1140225': 'ka1140225@hcu.edu.tw',
    'KA1140229': 'ka1140229@hcu.edu.tw',
    'KB1140202': 'kb1140202@hcu.edu.tw',
    'MB1132018': 'mb1132018@hcu.edu.tw',
    'MB1142005': 'mb1142005@hcu.edu.tw',
    'MB1142008': 'mb1142008@hcu.edu.tw',
    'MB1142123': 'mb1142123@hcu.edu.tw',
    'KB1140128': 'kb1140128@hcu.edu.tw',
    '112152516': 'ryanhsiao89@gmail.com',
    'HOPE HARN': 'hopehopejoy@gmail.com'
}

# --- 發送 OTP 函式 ---
def send_otp_email(receiver_email, otp_code):
    if SENDER_EMAIL == "your_email@gmail.com":
        return False, "⚠️ 教師尚未設定發信信箱 (SENDER_EMAIL)，請通知管理員。"
    
    msg = MIMEText(f"同學您好：\n\n您的系統登入驗證碼為：【 {otp_code} 】\n\n請於網頁輸入此 6 位數代碼完成身分確認。\n祝演練順利！")
    msg['Subject'] = "【助人技巧 AI 模擬系統】登入驗證碼"
    msg['From'] = SENDER_EMAIL
    msg['To'] = receiver_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        return True, "發送成功"
    except Exception as e:
        return False, str(e)

# --- 預設個案庫 ---
CASES = {
    "【人際焦慮】小明 (大學生)": "小明是一名大二男生，主訴是嚴重的人際焦慮。他害怕上台報告，總覺得同學在背後嘲笑他，導致最近開始逃避去學校。",
    "【生涯迷惘】小華 (應屆畢業生)": "小華是即將畢業的大四女生，對於未來感到極度迷惘。父母希望她考公務員，但她內心想從事藝術工作，兩者衝突讓她每天失眠。",
    "【情緒低落】阿建 (科技業工程師)": "阿建今年30歲，剛經歷分手，加上工作壓力大，近期表現出明顯的憂鬱傾向。",
    "【自訂個案】": "請在下方前情提要中詳細描述個案狀態。"
}

# --- 督導 Prompt ---
SUPERVISOR_PROMPT = """你是一位資深的諮商心理師臨床督導。請根據以下助人對話紀錄，評估受訓者在 Hill 助人技巧的使用品質。
請依序給出回饋：一、質性總體評估；二、15項技巧評分(0-5分)。"""

# --- 初始化 Session State ---
state_defaults = {
    "api_keys": [], "current_key_index": 0, "history": [],
    "chat_session": None, "is_ended": False, "supervisor_feedback": "",
    "is_started": False, "context_data": {}, "is_logged_in": False, 
    "student_id": "", "otp_sent": False, "generated_otp": "", "target_email": ""
}
for k, v in state_defaults.items():
    if k not in st.session_state: st.session_state[k] = v

# --- 側邊欄 ---
st.sidebar.title("⚙️ 系統設定")
api_input = st.sidebar.text_area("🔑 輸入 Gemini API Key (多組請換行)", value="\n".join(st.session_state.api_keys))
if api_input: 
    st.session_state.api_keys = [k.strip() for k in re.split(r'[\n,]+', api_input) if k.strip()]

if st.session_state.is_logged_in:
    st.sidebar.markdown("---")
    st.sidebar.write(f"👤 當前使用者：**{st.session_state.student_id}**")
    if st.sidebar.button("🚪 登出系統"):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

# --- 畫面 0：學號與 OTP 驗證 ---
if not st.session_state.is_logged_in:
    st.title("🔐 助人技巧 AI 模擬系統 (登入驗證)")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if not st.session_state.otp_sent:
            st.write("請輸入您的學號，系統將寄送驗證碼至您綁定的信箱。")
            sid_input = st.text_input("📝 請輸入學號 (Student ID)：", placeholder="例如：MB1132018").strip().upper()
            if st.button("發送驗證碼", type="primary", use_container_width=True):
                if sid_input in WHITELIST:
                    st.session_state.student_id = sid_input
                    st.session_state.target_email = WHITELIST[sid_input]
                    st.session_state.generated_otp = str(random.randint(100000, 999999))
                    with st.spinner("📧 正在寄送驗證碼..."):
                        ok, err = send_otp_email(st.session_state.target_email, st.session_state.generated_otp)
                        if ok:
                            st.session_state.otp_sent = True
                            st.rerun()
                        else: st.error(f"寄送失敗：{err}")
                else: st.error("❌ 該學號不在白名單中，請聯繫授課教師。")
        else:
            st.success(f"📧 驗證碼已寄至您的信箱：{st.session_state.target_email[:3]}***@{st.session_state.target_email.split('@')[-1]}")
            otp_val = st.text_input("🔑 請輸入 6 位數驗證碼：", max_chars=6)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("確認登入", type="primary", use_container_width=True):
                    if otp_val == st.session_state.generated_otp:
                        st.session_state.is_logged_in = True
                        st.rerun()
                    else: st.error("❌ 驗證碼錯誤！")
            with c2:
                if st.button("返回重填學號", use_container_width=True):
                    st.session_state.otp_sent = False
                    st.rerun()

# --- 畫面 1：演練設定 ---
elif not st.session_state.is_started:
    st.title("🧑‍🏫 助人技巧模擬演練系統")
    tab1, tab2 = st.tabs(["🆕 開啟新晤談", "📂 讀取舊紀錄 (CSV)"])
    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            sel_case = st.selectbox("1. 選擇模擬個案：", list(CASES.keys()))
            s_num = st.number_input("2. 晤談次數：", min_value=1, value=1)
        with c2:
            rel = st.selectbox("3. 目前關係品質：", ["新開案", "陌生疏離", "逐漸建立信任", "投契穩固"])
        ctx_t = st.text_area("4. 前情提要 / 補充：")
        if st.button("🚀 開始演練", type="primary"):
            if not st.session_state.api_keys: st.error("❌ 請先填寫 API Key")
            else:
                st.session_state.context_data = {"case": sel_case, "session_num": s_num, "relation": rel, "context": ctx_t}
                st.session_state.is_started = True
                genai.configure(api_key=st.session_state.api_keys[0])
                model = genai.GenerativeModel("gemini-1.5-flash")
                st.session_state.history = [{"role": "user", "parts": [f"你是個案{sel_case}。關係：{rel}。絕對不要扮演諮商師。"]}, {"role": "model", "parts": ["(坐在椅子上等待...)"]}]
                st.session_state.chat_session = model.start_chat(history=st.session_state.history)
                st.rerun()
    with tab2:
        up_f = st.file_uploader("上傳先前下載的對話紀錄 (CSV)", type="csv")
        if up_f and st.button("📂 載入進度"):
            df = pd.read_csv(up_f)
            st.session_state.history = [{"role": r['role'], "parts": [str(r['content'])]} for _, r in df.iterrows()]
            st.session_state.is_started = True
            genai.configure(api_key=st.session_state.api_keys[0])
            st.session_state.chat_session = genai.GenerativeModel("gemini-1.5-flash").start_chat(history=st.session_state.history)
            st.rerun()

# --- 畫面 2：對話演練 ---
elif st.session_state.is_started and not st.session_state.is_ended:
    st.title(f"🗣️ 模擬晤談中 ({st.session_state.context_data.get('case')})")
    for m in st.session_state.history[1:]:
        with st.chat_message("assistant" if m["role"] == "model" else "user"): st.write(m["parts"][0])
    u_in = st.chat_input("請輸入回應...")
    if u_in:
        st.session_state.history.append({"role": "user", "parts": [u_in]})
        with st.spinner("個案思考中..."):
            try:
                resp = st.session_state.chat_session.send_message(u_in)
                st.session_state.history.append({"role": "model", "parts": [resp.text]})
                st.rerun()
            except Exception as e: st.error(f"連線異常：{e}")
    if st.button("🛑 結束並獲取督導回饋"):
        st.session_state.is_ended = True
        st.rerun()

# --- 畫面 3：督導報告 ---
elif st.session_state.is_ended:
    st.title("📋 臨床督導回饋報告")
    if not st.session_state.supervisor_feedback:
        with st.spinner("👨‍🏫 審閱紀錄中..."):
            log = "\n".join([f"{'助人者' if m['role']=='user' else '個案'}: {m['parts'][0]}" for m in st.session_state.history[1:]])
            try:
                genai.configure(api_key=st.session_state.api_keys[0])
                resp = genai.GenerativeModel("gemini-1.5-flash").generate_content(f"{SUPERVISOR_PROMPT}\n\n{log}")
                st.session_state.supervisor_feedback = resp.text
                st.rerun()
            except Exception as e: st.error(f"督導生成失敗: {e}")
    st.markdown(st.session_state.supervisor_feedback)
    df_s = pd.DataFrame([{"role": m["role"], "content": m["parts"][0]} for m in st.session_state.history])
    st.download_button("💾 下載紀錄 (CSV)", data=df_s.to_csv(index=False).encode('utf-8-sig'), file_name=f"{st.session_state.student_id}_報告.csv")
    if st.button("🔄 返回首頁"):
        for k in ["history", "chat_session", "is_ended", "supervisor_feedback", "is_started", "context_data"]: del st.session_state[k]
        st.rerun()
