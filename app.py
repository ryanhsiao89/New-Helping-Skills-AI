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

# --- 預設個案庫 (可自行擴充) ---
CASES = {
    "【人際焦慮】小明 (大學生)": "小明是一名大二男生，主訴是嚴重的人際焦慮。他害怕上台報告，總覺得同學在背後嘲笑他，導致最近開始逃避去學校。",
    "【生涯迷惘】小華 (應屆畢業生)": "小華是即將畢業的大四女生，對於未來感到極度迷惘。父母希望她考公務員，但她內心想從事藝術工作，兩者衝突讓她每天失眠。",
    "【情緒低落】阿建 (科技業工程師)": "阿建今年30歲，剛經歷分手，加上工作壓力大，近期表現出明顯的憂鬱傾向，覺得生活失去動力，對原本喜歡的事物也不感興趣。",
    "【自訂個案】": "請在下方前情提要中詳細描述個案狀態。"
}

# --- 15項助人技巧督導 Prompt ---
SUPERVISOR_PROMPT = """你是一位資深的諮商心理師臨床督導。請根據以下助人對話紀錄，評估受訓者在 Hill 助人技巧（涵蓋探索、洞察、行動三階段）的使用品質。
請嚴格遵守以下格式給予回饋：

一、總體臨床評估（質性回饋）：
請具體說明學生表現好的地方，以及需要改進的盲點。請考量他們設定的「晤談次數」與「關係品質」，評估其介入深度是否合適。

二、15項助人技巧評分（量化回饋，0-5分，0代表完全未使用，5代表使用得非常精準到位）：
請務必依序給出以下15項技巧的評分，格式必須為「技巧名稱：[X] 分」。
1. 專注：[X] 分
2. 傾聽：[X] 分
3. 重述：[X] 分
4. 開放式問句：[X] 分
5. 情感反映：[X] 分
6. 探索性的自我表露：[X] 分
7. 意圖性的沉默：[X] 分
8. 挑戰：[X] 分
9. 解釋：[X] 分
10. 洞察性的自我表露：[X] 分
11. 立即性：[X] 分
12. 訊息提供：[X] 分
13. 直接指導：[X] 分
14. 角色扮演及行為演練：[X] 分
15. 家庭作業：[X] 分
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

# --- 側邊欄：API Key 設定 ---
st.sidebar.title("⚙️ 系統設定")
api_input = st.sidebar.text_area("🔑 輸入 Gemini API Key\n(可輸入多組，請用逗號或換行隔開以防斷線)", value="\n".join(st.session_state.api_keys))
if api_input: 
    parsed_keys = [k.strip() for k in re.split(r'[\n,]+', api_input) if k.strip()]
    st.session_state.api_keys = parsed_keys

st.sidebar.markdown("---")
st.sidebar.markdown("**📝 演練提示**\n- 記得使用 **`( )`** 描述非口語行為。\n- 隨時可點擊「暫停並下載進度」將紀錄存成 CSV 檔。")

# --- 畫面 1：情境設定與讀檔區 ---
if not st.session_state.is_started:
    st.title("🧑‍🏫 助人技巧模擬演練系統 (教學版)")
    st.info("本系統無須連線資料庫，您的演練紀錄僅保存在本地端。")
    
    tab1, tab2 = st.tabs(["🆕 開啟新晤談", "📂 讀取先前的紀錄 (CSV)"])
    
    with tab1:
        st.subheader("設定晤談脈絡")
        col1, col2 = st.columns(2)
        with col1:
            selected_case = st.selectbox("1. 選擇模擬個案：", list(CASES.keys()))
            session_num = st.number_input("2. 這是第幾次晤談？", min_value=1, max_value=20, value=1)
        with col2:
            relationship_quality = st.selectbox("3. 目前與個案的關係品質：", [
                "新開案_關係尚待建立", 
                "關係陌生疏離_個案帶有防衛", 
                "關係逐漸建立_個案開始試探性信任", 
                "關係投契信任_工作同盟穩固"
            ])
            
        context_text = st.text_area("4. 前情提要 / 轉介事由 / 當下情境補充：", 
                                    placeholder="例如：上次晤談結束前個案大哭，本次是過了一個禮拜後的會談。個案今天走進來時神情落寞...")
        
        if st.button("🚀 開始新晤談", type="primary"):
            if not st.session_state.api_keys:
                st.error("❌ 請先在左側欄輸入至少一組 API Key！")
            else:
                st.session_state.context_data = {
                    "case": selected_case, "case_desc": CASES[selected_case],
                    "session_num": session_num, "relation": relationship_quality, "context": context_text
                }
                
                # 建構給 AI 的系統提示詞
                system_instruction = f"""
                [角色設定]
                你是一個正在接受心理諮商的個案。請根據以下設定自然地與諮商師對話。
                個案基本資料：{selected_case} - {CASES[selected_case]}
                
                [本次晤談脈絡]
                這是你與諮商師的第 {session_num} 次晤談。
                目前你對諮商師的信任程度：{relationship_quality} (請依照這個信任程度調整你的防衛心或自我揭露程度)。
                前情提要補充：{context_text}
                
                [互動規則]
                1. 絕對不要扮演諮商師，你只能是個案。
                2. 請根據你的關係品質與前情提要來決定第一句話怎麼說。
                """
                
                st.session_state.is_started = True
                genai.configure(api_key=st.session_state.api_keys[0])
                model = genai.GenerativeModel(model_name="gemini-2.5-flash", generation_config=GenerationConfig(temperature=0.3))
                
                # 初始化歷史紀錄
                st.session_state.history = [
                    {"role": "user", "parts": [system_instruction]},
                    {"role": "model", "parts": ["(坐在椅子上，等待諮商師開口...)"]}
                ]
                st.session_state.chat_session = model.start_chat(history=st.session_state.history)
                st.rerun()

    with tab2:
        st.subheader("延續之前的晤談")
        uploaded_file = st.file_uploader("上傳您之前下載的對話紀錄 (CSV檔)", type="csv")
        if uploaded_file is not None:
            if not st.session_state.api_keys:
                st.error("❌ 請先在左側欄輸入 API Key！")
            else:
                try:
                    df = pd.read_csv(uploaded_file)
                    # 檢查 CSV 格式
                    if 'role' in df.columns and 'content' in df.columns:
                        st.session_state.history = []
                        for index, row in df.iterrows():
                            st.session_state.history.append({"role": row['role'], "parts": [str(row['content'])]})
                        
                        # 假定讀取成功，還原設定
                        st.session_state.context_data = {"case": "從 CSV 讀取的個案", "session_num": "延續", "relation": "延續", "context": "讀取舊檔"}
                        st.session_state.is_started = True
                        
                        genai.configure(api_key=st.session_state.api_keys[0])
                        model = genai.GenerativeModel(model_name="gemini-2.5-flash", generation_config=GenerationConfig(temperature=0.3))
                        st.session_state.chat_session = model.start_chat(history=st.session_state.history)
                        st.success("✅ 讀檔成功！點擊下方按鈕繼續。")
                        if st.button("🚀 繼續晤談"):
                            st.rerun()
                    else:
                        st.error("❌ CSV 格式不符，缺少 role 或 content 欄位。")
                except Exception as e:
                    st.error(f"讀檔發生錯誤：{e}")

# --- 畫面 2：對話演練區 ---
elif st.session_state.is_started and not st.session_state.is_ended:
    ctx = st.session_state.context_data
    st.title(f"🗣️ 模擬晤談中 ({ctx.get('case', '載入個案')})")
    
    with st.expander("📄 本次晤談脈絡設定 (點擊展開/收合)", expanded=False):
        st.write(f"**第 {ctx.get('session_num', '-')} 次晤談 | 關係品質：{ctx.get('relation', '-')}**")
        st.write(f"**前情提要：** {ctx.get('context', '無')}")

    # 顯示對話歷史 (隱藏第一句系統 Prompt)
    for msg in st.session_state.history[1:]:
        role = "assistant" if msg["role"] == "model" else "user"
        with st.chat_message(role):
            st.write(msg["content"] if "content" in msg else msg["parts"][0])

    # 聊天輸入框
    user_input = st.chat_input("請輸入你的回應 (記得加上括號描述非語言行為)...")
    if user_input:
        if "(" not in user_input and "（" not in user_input:
            st.toast("⚠️ 溫馨提醒：你似乎忘了使用 ( ) 描述非口語行為喔！", icon="💡")
        
        st.session_state.history.append({"role": "user", "parts": [user_input]})
        with st.chat_message("user"): st.write(user_input)
            
        with st.spinner("個案思考中..."):
            time.sleep(1.5)
            
            # API 輪詢防護機制 (處理 429 錯誤)
            max_attempts = len(st.session_state.api_keys)
            response_text = None
            
            for attempt in range(max_attempts):
                try:
                    response = st.session_state.chat_session.send_message(user_input)
                    response_text = response.text
                    break
                except Exception as e:
                    if "429" in str(e) or "Quota" in str(e):
                        next_index = st.session_state.current_key_index + 1
                        if next_index < len(st.session_state.api_keys):
                            st.session_state.current_key_index = next_index
                            genai.configure(api_key=st.session_state.api_keys[next_index])
                            st.toast(f"🔄 自動切換至第 {next_index+1} 把備用 Key...", icon="🛡️")
                            
                            # 🌟 [修復角色錯亂] 重建 Session 確保包含初始設定檔
                            model = genai.GenerativeModel(model_name="gemini-2.5-flash", generation_config=GenerationConfig(temperature=0.3))
                            old_history = st.session_state.history[:-1] 
                            st.session_state.chat_session = model.start_chat(history=old_history)
                        else:
                            st.warning("⏳ API 額度暫滿，倒數 20 秒緩衝...")
                            time.sleep(20)
                            response = st.session_state.chat_session.send_message(user_input)
                            response_text = response.text
                            break
                    else:
                        st.error(f"錯誤：{e}")
                        break
            
            if response_text:
                st.session_state.history.append({"role": "model", "parts": [response_text]})
                st.rerun()

    st.markdown("---")
    col1, col2, col3 = st.columns([4, 3, 3])
    
    # [新功能] 下載進度 CSV (中途存檔)
    with col2:
        df_history = pd.DataFrame([{"role": m["role"], "content": m["parts"][0]} for m in st.session_state.history])
        csv_data = df_history.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="💾 暫停並下載進度 (CSV)",
            data=csv_data,
            file_name=f"晤談進度_{datetime.now().strftime('%Y%m%d%H%M')}.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col3:
        if st.button("🛑 結束晤談並獲取督導回饋", type="primary", use_container_width=True):
            st.session_state.is_ended = True
            st.rerun()

# --- 畫面 3：督導回饋與綜合下載區 ---
elif st.session_state.is_ended:
    if not st.session_state.supervisor_feedback:
        st.markdown("---")
        with st.spinner("👨‍🏫 臨床督導正在根據 Hill 15項助人技巧審閱你的對話紀錄..."):
            log_text = ""
            # 略過第一句系統設定 Prompt
            for msg in st.session_state.history[1:]:
                role_str = "助人者" if msg["role"] == "user" else "個案"
                content = msg["parts"][0]
                log_text += f"{role_str}: {content}\n"
            
            ctx = st.session_state.context_data
            final_prompt = f"{SUPERVISOR_PROMPT}\n\n[受訓者設定的晤談脈絡]\n第{ctx.get('session_num','-')}次會談\n關係品質：{ctx.get('relation','-')}\n\n[對話紀錄]\n{log_text}"
            
            try:
                supervisor_model = genai.GenerativeModel(model_name="gemini-2.5-flash", generation_config=GenerationConfig(temperature=0.0))
                feedback_resp = supervisor_model.generate_content(final_prompt)
                st.session_state.supervisor_feedback = feedback_resp.text
            except Exception as e:
                st.error(f"產生督導回饋時發生錯誤: {e}")
                st.session_state.supervisor_feedback = "無法生成督導回饋，請稍後重試。"

            st.rerun()

    if st.session_state.supervisor_feedback:
        st.markdown("## 📋 臨床督導回饋報告 (15項技巧評估)")
        st.markdown(st.session_state.supervisor_feedback)
        
        # 準備完整的文字報告供下載
        export_text = f"【助人技巧 AI 模擬演練綜合報告】\n"
        export_text += f"演練時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        ctx = st.session_state.context_data
        export_text += f"晤談脈絡：第{ctx.get('session_num','-')}次晤談 | 關係：{ctx.get('relation','-')}\n"
        export_text += "="*40 + "\n\n【對話逐字稿】\n"
        for msg in st.session_state.history[1:]:
            role_str = "助人者" if msg["role"] == "user" else "個案"
            export_text += f"{role_str}：{msg['parts'][0]}\n\n"
        export_text += "="*40 + "\n\n【督導回饋報告】\n"
        export_text += st.session_state.supervisor_feedback

        col1, col2 = st.columns([1, 1])
        with col1:
            st.download_button(
                label="📥 下載完整逐字稿與督導報告 (TXT檔)",
                data=export_text.encode('utf-8-sig'),
                file_name=f"完整演練報告_{datetime.now().strftime('%Y%m%d%H%M')}.txt",
                mime="text/plain",
                use_container_width=True,
                type="primary"
            )
        with col2:
            if st.button("🔄 返回首頁 / 開啟新練習", use_container_width=True):
                for key in list(st.session_state.keys()):
                    if key not in ["api_keys"]: del st.session_state[key]
                st.rerun()