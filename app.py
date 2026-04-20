import streamlit as st
import google.generativeai as genai
from google.generativeai.types import GenerationConfig
import pandas as pd
import time
import re
import random
from datetime import datetime
import io

# --- 系統與頁面設定 ---
st.set_page_config(page_title="助人技巧 AI 模擬系統 (教學專用版)", layout="wide", page_icon="🧑‍🏫")

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
格式：技巧名稱：[X] 分
1. 專注、2. 傾聽、3. 重述、4. 開放式問句、5. 情感反映、6. 探索性的自我表露、7. 意圖性的沉默、8. 挑戰、9. 解釋、10. 洞察性的自我表露、11. 立即性、12. 訊息提供、13. 直接指導、14. 角色扮演及行為演練、15. 家庭作業。
"""

# --- 初始化 Session State ---
if "api_keys" not in st.session_state: st.session_state.api_keys = []
if "current_key_index" not in st.session_state: st.session_state.current_key_index = 0
if "history" not in st.session_state: st.session_state.history = []
if "chat_session" not in st.session_state: st.session_state.chat_session = None
if "is_ended" not in st.session_state: st.session_state.is_ended = False
if "supervisor_feedback" not in st.session_state: st.session_state.supervisor_feedback = ""
if "is_started" not in st.session_state: st.session_state.is_started = False
if "context_data" not in st.session_state: st.session_state.context_data = {}

# --- 側邊欄設定 ---
st.sidebar.title("⚙️ 系統設定")
api_input = st.sidebar.text_area("🔑 輸入 Gemini API Key", value="\n".join(st.session_state.api_keys))
if api_input: 
    parsed_keys = [k.strip() for k in re.split(r'[\n,]+', api_input) if k.strip()]
    st.session_state.api_keys = parsed_keys

# --- 畫面分流邏輯 ---

# 1. 初始畫面
if not st.session_state.is_started:
    st.title("🧑‍🏫 助人技巧模擬演練系統 (教學版)")
    tab1, tab2 = st.tabs(["🆕 開啟新晤談", "📂 讀取先前的紀錄 (CSV)"])
    
    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            selected_case = st.selectbox("1. 選擇模擬個案：", list(CASES.keys()))
            session_num = st.number_input("2. 這是第幾次晤談？", min_value=1, value=1)
        with col2:
            relationship_quality = st.selectbox("3. 關係品質：", ["新開案", "關係陌生", "逐漸建立", "信任穩固"])
        context_text = st.text_area("4. 前情提要：")
        
        if st.button("🚀 開始新晤談", type="primary"):
            if not st.session_state.api_keys:
                st.error("❌ 請先輸入 API Key！")
            else:
                st.session_state.context_data = {"case": selected_case, "session_num": session_num, "relation": relationship_quality, "context": context_text}
                system_instruction = f"你是個案{selected_case}。關係：{relationship_quality}。不要扮演諮商師。"
                st.session_state.is_started = True
                genai.configure(api_key=st.session_state.api_keys[0])
                model = genai.GenerativeModel("gemini-1.5-flash")
                st.session_state.history = [{"role": "user", "parts": [system_instruction]}, {"role": "model", "parts": ["(坐在椅子上...)"]}]
                st.session_state.chat_session = model.start_chat(history=st.session_state.history)
                st.rerun()

# 2. 對話畫面
elif st.session_state.is_started and not st.session_state.is_ended:
    st.title(f"🗣️ 模擬晤談中 ({st.session_state.context_data.get('case')})")
    
    for msg in st.session_state.history[1:]:
        role = "assistant" if msg["role"] == "model" else "user"
        with st.chat_message(role):
            st.write(msg["parts"][0])

    user_input = st.chat_input("請輸入回應...")
    if user_input:
        st.session_state.history.append({"role": "user", "parts": [user_input]})
        with st.chat_message("user"): st.write(user_input)
        with st.spinner("個案思考中..."):
            try:
                response = st.session_state.chat_session.send_message(user_input)
                st.session_state.history.append({"role": "model", "parts": [response.text]})
                st.rerun()
            except Exception as e:
                st.error(f"連線錯誤：{e}")

    if st.button("🛑 結束晤談並獲取督導回饋"):
        st.session_state.is_ended = True
        st.rerun()

# 3. 督導畫面 (這裡就是之前報錯的地方，現在它跟在前面的 if/elif 後面)
elif st.session_state.is_ended:
    st.title("📋 臨床督導回饋報告")
    if not st.session_state.supervisor_feedback:
        with st.spinner("👨‍🏫 督導正在審閱對話紀錄..."):
            log_text = ""
            for msg in st.session_state.history[1:]:
                role = "助人者" if msg["role"] == "user" else "個案"
                log_text += f"{role}: {msg['parts'][0]}\n"
            
            try:
                # 重新配置 API Key 確保穩定
                current_key = st.session_state.api_keys[st.session_state.current_key_index]
                genai.configure(api_key=current_key)
                # 使用穩定版模型
                supervisor_model = genai.GenerativeModel("gemini-1.5-flash")
                feedback_resp = supervisor_model.generate_content(f"{SUPERVISOR_PROMPT}\n\n對話紀錄：\n{log_text}")
                st.session_state.supervisor_feedback = feedback_resp.text
                st.rerun()
            except Exception as e:
                st.error(f"督導生成失敗: {e}")

    st.markdown(st.session_state.supervisor_feedback)
    if st.button("🔄 返回首頁"):
        for key in list(st.session_state.keys()):
            if key != "api_keys": del st.session_state[key]
        st.rerun()
