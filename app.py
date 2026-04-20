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
st.set_page_config(page_title="助人技巧 AI 模擬系統 (教學專用版)", layout="wide", page_icon="🧑‍🏫")

# ==========================================
# 📧 系統發信帳號設定 (請填寫您的 Gmail 與應用程式密碼)
# ==========================================
SENDER_EMAIL = "your_email@gmail.com"  # 替換成用來寄信的 Gmail
SENDER_PASSWORD = "your_app_password"  # 替換成該 Gmail 的 16 碼「應用程式密碼」

def send_otp_email(receiver_email, otp_code):
    if SENDER_EMAIL == "your_email@gmail.com":
        return False, "⚠️ 系統尚未設定發信信箱 (SENDER_EMAIL)，請教師於程式碼中設定。"
        
    msg = MIMEText(f"同學您好：\n\n您的「助人技巧 AI 模擬系統」登入驗證碼為：【 {otp_code} 】\n\n請回到系統網頁輸入此 6 位數密碼以完成登入。\n祝您演練順利！\n\n(系統自動發送，請勿回信)")
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

# --- 🌟 本研究專屬白名單 (Whitelist) 🌟 ---
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

# --- 預設個案庫 ---
CASES = {
    "【人際焦慮】小明 (大學生)": "小明是一名大二男生，主訴是嚴重的人際焦慮。他害怕上台報告，總覺得同學在背後嘲笑他，導致最近開始逃避去學校。",
    "【生涯迷惘】小華 (應屆畢業生)": "小華是即將畢業的大四女生，對於未來感到極度迷惘。父母希望她考公務員，但她內心想從事藝術工作，兩者衝突讓她每天失眠。",
    "【情緒低落】阿建 (科技業工程師)": "阿建今年30歲，剛經歷分手，加上工作壓力大，近期表現出明顯的憂鬱傾向，覺得生活失去動力，對原本喜歡的事物也不感興趣。",
    "【自訂個案】": "請在下方前情提要中詳細描述個案狀態。"
}

# --- 15項助人技巧督導 Prompt ---
SUPERVISOR_PROMPT = """你是一位資深的諮商心理師臨床督導。請根據以下助人對話紀錄，評估受訓者在 Hill 助人技巧的使用品質。
請嚴格遵守以下格式給予回饋：
一、總體臨床評估（質性回饋）：
請具體說明學生表現好的地方，以及需要改進的盲點。
二、15項助人技巧評分（量化回饋，0-5分）：
格式：「技巧名稱：[X] 分」
1. 專注、2. 傾聽、3. 重述、4. 開放式問句、5. 情感反映、6. 探索性的自我表露、7. 意圖性的沉默、8. 挑戰、9. 解釋、10. 洞察性的自我表露、11. 立即性、12. 訊息提供、13. 直接指導、14. 角色扮演及行為演練、15. 家庭作業。
"""

# --- 初始化 Session State ---
keys_to_init = {
    "api_keys": [], "current_key_index": 0, "history": [],
    "chat_session": None, "is_ended": False, "supervisor_feedback": "",
    "is_started": False, "context_data": {}, "is_logged_in": False, "student_id": "",
    "otp_sent": False, "generated_otp": "", "target_email": ""
}
for k, v in keys_to_init.items():
    if k not in st.session_state: st.session_state[k] = v

# --- 側邊欄設定 ---
st.sidebar.title("⚙️ 系統設定")
api_input = st.sidebar.text_area("🔑 輸入 Gemini API Key (多組請換行)", value="\n".join(st.session_state.api_keys))
if api_input: 
    parsed_keys = [k.strip() for k in re.split(r'[\n,]+', api_input) if k.strip()]
    st.session_state.api_keys = parsed_keys

if st.session_state.is_logged_in:
    st.sidebar.markdown("---")
    st.sidebar.write(f"👤 目前使用者：**{st.session_state.student_id}**")
    if st.sidebar.button("🚪 登出系統"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# --- 畫面 0：雙重登入驗證畫面 (OTP) ---
if not st.session_state.is_logged_in:
    st.title("🔐 助人技巧 AI 模擬系統 (登入)")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if not st.session_state.otp_sent:
            st.info("請輸入學號，系統將寄送驗證碼至您的信箱。")
            user_id_input = st.text_input("📝 請輸入學號 (Student ID)：", placeholder="例如：MB1132018")
            if st.button("發送驗證碼", type="primary", use_container_width=True):
                clean_id = user_id_input.strip().upper() 
                if clean_id in WHITELIST:
                    st.session_state.student_id = clean_id
                    st.session_state.target_email = WHITELIST[clean_id]
                    # 隨機生成 6 位數 OTP
                    st.session_state.generated_otp = str(random.randint(100000, 999999))
                    
                    with st.spinner("📧 正在發送驗證碼至您的信箱，請稍候..."):
                        success, msg = send_otp_email(st.session_state.target_email, st.session_state.generated_otp)
                        if success:
                            st.session_state.otp_sent = True
                            st.rerun()
                        else:
                            st.error(f"郵件發送失敗：{msg}")
                else:
                    st.error("❌ 學號不在白名單中，請重新確認或聯繫教師。")
        else:
            st.success(f"📧 驗證碼已發送至：**{st.session_state.target_email}** (請檢查收件匣或垃圾郵件)")
            otp_input = st.text_input("🔑 請輸入 6 位數驗證碼：", max_chars=6)
            
            c1, c2 = st.columns(2)
            with c1:
                if st.button("驗證並登入", type="primary", use_container_width=True):
                    if otp_input == st.session_state.generated_otp:
                        st.session_state.is_logged_in = True
                        st.success(f"✅ 登入成功！歡迎 {st.session_state.student_id}。")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ 驗證碼錯誤，請重新輸入！")
            with c2:
                if st.button("重新輸入學號", use_container_width=True):
                    st.session_state.otp_sent = False
                    st.session_state.generated_otp = ""
                    st.rerun()

# --- 畫面 1：初始設定與讀檔 ---
elif not st.session_state.is_started:
    st.title("🧑‍🏫 助人技巧模擬演練系統 (教學版)")
    tab1, tab2 = st.tabs(["🆕 開啟新晤談", "📂 讀取先前的紀錄 (CSV)"])
    
    with tab1:
        st.subheader("設定晤談脈絡")
        col1, col2 = st.columns(2)
        with col1:
            selected_case = st.selectbox("1. 選擇模擬個案：", list(CASES.keys()))
            session_num = st.number_input("2. 這是第幾次晤談？", min_value=1, value=1)
        with col2:
            relationship_quality = st.selectbox("3. 目前關係品質：", ["新開案_關係尚待建立", "關係陌生疏離", "逐漸建立信任", "關係投契穩固"])
        context_text = st.text_area("4. 前情提要 / 補充：")
        
        if st.button("🚀 開始新晤談", type="primary"):
            if not st.session_state.api_keys:
                st.error("❌ 請先於左側面板輸入 API Key！")
            else:
                st.session_state.context_data = {"case": selected_case, "session_num": session_num, "relation": relationship_quality, "context": context_text}
                system_instruction = f"你是個案{selected_case}。描述：{CASES.get(selected_case)}。第{session_num}次晤談，關係：{relationship_quality}。{context_text}。絕對不要扮演諮商師。"
                st.session_state.is_started = True
                genai.configure(api_key=st.session_state.api_keys[0])
                model = genai.GenerativeModel("gemini-1.5-flash")
                st.session_state.history = [{"role": "user", "parts": [system_instruction]}, {"role": "model", "parts": ["(坐在椅子上，等待諮商師開口...)"]}]
                st.session_state.chat_session = model.start_chat(history=st.session_state.history)
                st.rerun()

    with tab2:
        st.subheader("續接舊進度")
        uploaded_file = st.file_uploader("請上傳先前下載的 CSV 檔", type="csv")
        if uploaded_file is not None:
            if not st.session_state.api_keys:
                st.error("❌ 請先於左側面板輸入 API Key！")
            else:
                try:
                    df = pd.read_csv(uploaded_file)
                    if 'role' in df.columns and 'content' in df.columns:
                        st.session_state.history = []
                        for _, row in df.iterrows():
                            st.session_state.history.append({"role": row['role'], "parts": [str(row['content'])]})
                        st.session_state.context_data = {"case": "從 CSV 讀取的舊進度", "session_num": "續接", "relation": "續接"}
                        st.session_state.is_started = True
                        genai.configure(api_key=st.session_state.api_keys[0])
                        model = genai.GenerativeModel("gemini-1.5-flash")
                        st.session_state.chat_session = model.start_chat(history=st.session_state.history)
                        st.success("✅ 讀取成功！")
                        if st.button("🚀 繼續進入晤談"): st.rerun()
                    else:
                        st.error("❌ CSV 格式錯誤，缺少 role 或 content 欄位。")
                except Exception as e:
                    st.error(f"讀取失敗：{e}")

# --- 畫面 2：演練中 ---
elif st.session_state.is_started and not st.session_state.is_ended:
    st.title(f"🗣️ 模擬晤談中 ({st.session_state.context_data.get('case')})")
    for msg in st.session_state.history[1:]:
        role = "assistant" if msg["role"] == "model" else "user"
        with st.chat_message(role):
            st.write(msg["parts"][0])

    user_input = st.chat_input("輸入回應 (建議使用括號描述動作)...")
    if user_input:
        st.session_state.history.append({"role": "user", "parts": [user_input]})
        with st.chat_message("user"): st.write(user_input)
        with st.spinner("個案思考中..."):
            try:
                response = st.session_state.chat_session.send_message(user_input)
                st.session_state.history.append({"role": "model", "parts": [response.text]})
                st.rerun()
            except Exception as e:
                if len(st.session_state.api_keys) > 1:
                    st.session_state.current_key_index = (st.session_state.current_key_index + 1) % len(st.session_state.api_keys)
                    genai.configure(api_key=st.session_state.api_keys[st.session_state.current_key_index])
                    st.warning("🔄 嘗試更換 API Key 並重新傳送...")
                st.error(f"連線異常：{e}")

    col1, col2 = st.columns([7, 3])
    with col2:
        if st.button("🛑 結束晤談並獲取督導回饋", type="primary"):
            st.session_state.is_ended = True
            st.rerun()

# --- 畫面 3：督導報告 ---
elif st.session_state.is_ended:
    st.title("📋 臨床督導回饋報告 (15項技巧評估)")
    if not st.session_state.supervisor_feedback:
        with st.spinner("👨‍🏫 臨床督導正在審閱紀錄，請稍候..."):
            log_text = ""
            for msg in st.session_state.history[1:]:
                role = "助人者" if msg["role"] == "user" else "個案"
                log_text += f"{role}: {msg['parts'][0]}\n"
            
            try:
                genai.configure(api_key=st.session_state.api_keys[st.session_state.current_key_index])
                model = genai.GenerativeModel("gemini-1.5-flash")
                resp = model.generate_content(f"{SUPERVISOR_PROMPT}\n\n[對話紀錄]\n{log_text}")
                st.session_state.supervisor_feedback = resp.text
                st.rerun()
            except Exception as e:
                st.error(f"督導生成失敗: {e}")

    st.markdown(st.session_state.supervisor_feedback)
    
    df_save = pd.DataFrame([{"role": m["role"], "content": m["parts"][0]} for m in st.session_state.history])
    csv_save = df_save.to_csv(index=False).encode('utf-8-sig')
    student_id_str = st.session_state.student_id
    st.download_button("💾 下載本次紀錄與報告 (CSV)", data=csv_save, file_name=f"{student_id_str}_晤談報告_{datetime.now().strftime('%m%d_%H%M')}.csv", mime="text/csv")
    
    if st.button("🔄 返回首頁開啟新練習"):
        keys_to_keep = ["api_keys", "is_logged_in", "student_id"]
        for key in list(st.session_state.keys()):
            if key not in keys_to_keep: 
                del st.session_state[key]
        st.rerun()
