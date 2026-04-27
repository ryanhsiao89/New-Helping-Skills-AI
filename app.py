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


# =========================================================
# 系統與頁面設定
# =========================================================
st.set_page_config(
    page_title="助人技巧 AI 模擬系統 (教學驗證版)",
    layout="wide",
    page_icon="🧑‍🏫"
)

MODEL_NAME = "gemini-1.5-flash"

# 🌟 修正點 1：將個案與督導的溫度分開。個案需要一點情緒(0.4)，督導需要絕對理性(0.0)
CLIENT_TEMPERATURE = 0.4
SUPERVISOR_TEMPERATURE = 0.0


# =========================================================
# 系統發信帳號設定
# =========================================================
SENDER_EMAIL = "ryanhsiao89@gmail.com"       
SENDER_PASSWORD = "umnq csuk lzru tzrq"      # (⚠️ 提醒：此為敏感資訊，請妥善保管您的源碼)


# =========================================================
# AI 安全設定 (全版本相容寫法)
# =========================================================
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


# =========================================================
# 本研究專屬白名單
# =========================================================
WHITELIST = {
    "BB1112067": "bb1112067@hcu.edu.tw",
    "BB1122013": "bb1122013@hcu.edu.tw",
    "BB1122034": "bb1122034@hcu.edu.tw",
    "BB1122053": "jasminehu0711@gmail.com",
    "BB1125034": "bb1125034@hcu.edu.tw",
    "GB1132002": "gb1132002@hcu.edu.tw",
    "GB1142006": "gb1142006@hcu.edu.tw",
    "KA1140202": "ka1140202@hcu.edu.tw",
    "KA1140223": "ka1140223@hcu.edu.tw",
    "KA1140225": "ka1140225@hcu.edu.tw",
    "KA1140229": "ka1140229@hcu.edu.tw",
    "KB1140202": "kb1140202@hcu.edu.tw",
    "MB1132018": "mb1132018@hcu.edu.tw",
    "MB1142005": "mb1142005@hcu.edu.tw",
    "MB1142008": "mb1142008@hcu.edu.tw",
    "MB1142123": "mb1142123@hcu.edu.tw",
    "KB1140128": "kb1140128@hcu.edu.tw",
    "MB1142015": "mb1142015@hcu.edu.tw",
    "112152516": "ryanhsiao89@gmail.com",
    "HOPE HARN": "hopehopejoy@gmail.com",
}


# =========================================================
# 預設個案庫
# =========================================================
CASES = {
    "【人際焦慮】小明 (大學生)": "小明是一名大二男生，主訴是嚴重的人際焦慮。他害怕上台報告，總覺得同學在背後嘲笑他，導致最近開始逃避去學校。",
    "【生涯迷惘】小華 (應屆畢業生)": "小華是即將畢業的大四女生，對於未來感到極度迷惘。父母希望她考公務員，但她內心想從事藝術工作，兩者衝突讓她每天失眠。",
    "【情緒低落】阿建 (科技業工程師)": "阿建今年30歲，剛經歷分手，加上工作壓力大，近期表現出明顯的憂鬱傾向。",
    "【自訂個案】": "請依照教師或使用者在前情提要中輸入的內容扮演個案。",
}


# =========================================================
# 督導 Prompt
# =========================================================
SUPERVISOR_PROMPT = """
你是一位資深的諮商心理師臨床督導。請根據以下助人對話紀錄，
評估受訓者在 Hill 助人技巧的使用品質。

請依序給出回饋：
一、質性總體評估；
二、15項技巧評分（0-5分）；
三、具體改進建議；
四、可替代回應示範。
"""


# =========================================================
# OTP 發信函式
# =========================================================
def send_otp_email(receiver_email, otp_code):
    if SENDER_EMAIL == "your_email@gmail.com":
        return False, "⚠️ 寄件失敗：請檢查 SENDER_EMAIL 設定。"

    msg = MIMEText(
        f"同學您好：\n\n"
        f"您的系統登入驗證碼為：【 {otp_code} 】\n\n"
        f"請於網頁輸入此 6 位數代碼完成身分確認。\n"
        f"祝演練順利！"
    )
    msg["Subject"] = "【助人技巧 AI 模擬系統】登入驗證碼"
    msg["From"] = SENDER_EMAIL
    msg["To"] = receiver_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD.replace(" ", "")) # 自動過濾空白
            server.send_message(msg)
        return True, "發送成功"
    except Exception as e:
        return False, str(e)


# =========================================================
# Session State 初始化
# =========================================================
def init_session_state():
    defaults = {
        "api_keys": [],
        "current_key_index": 0,
        "history": [],                       
        "chat_session": None,
        "is_ended": False,
        "supervisor_feedback": "",
        "is_started": False,
        "context_data": {},
        "is_logged_in": False,
        "student_id": "",
        "otp_sent": False,
        "generated_otp": "",
        "target_email": "",
        "initial_client_message": "(坐在椅子上等待...)",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()


# =========================================================
# 工具函式：API Key、模型、角色設定、歷史重建
# =========================================================
def parse_api_keys(raw_text):
    if not raw_text: return []
    return [k.strip() for k in re.split(r"[\n,]+", raw_text) if k.strip()]

def get_current_api_key():
    if not st.session_state.api_keys:
        raise RuntimeError("尚未輸入任何 Gemini API Key。")
    return st.session_state.api_keys[st.session_state.current_key_index]

def switch_to_next_key():
    next_index = st.session_state.current_key_index + 1
    if next_index < len(st.session_state.api_keys):
        st.session_state.current_key_index = next_index
        return True
    return False

def get_case_description():
    context_data = st.session_state.get("context_data", {})
    case_key = context_data.get("case", "【自訂個案】")
    base_case = CASES.get(case_key, CASES["【自訂個案】"])
    extra_context = context_data.get("context", "").strip()
    relation = context_data.get("relation", "新開案")
    session_num = context_data.get("session_num", 1)

    description = f"""
【個案名稱與類型】{case_key}
【個案基本設定】{base_case}
【目前晤談次數】第 {session_num} 次晤談
【目前關係品質】{relation}
"""
    if extra_context:
        description += f"\n【前情提要／補充資料】\n{extra_context}\n"
    return description.strip()


def get_client_system_instruction():
    case_description = get_case_description()
    return f"""
你正在參與一個「心理諮商演練」的角色扮演。
【最高指令】：你永遠只能扮演「模擬個案」。不可脫離角色，不可扮演諮商師、老師、督導或 AI。
【個案設定】
{case_description}

【固定角色規則】
1. 必須用第一人稱（我）自然回應，展現該個案應有的情緒與防衛心。
2. 絕對不可給予建議、不可分析諮商技巧、不可說「作為諮商師...」或「你可以這樣回應」。
3. 對話長度維持 2 到 5 句，保持口語化。
4. 若使用者（諮商師）問得太急，請表現出抗拒或沈默。
""".strip()


def build_client_model():
    genai.configure(api_key=get_current_api_key())
    return genai.GenerativeModel(
        model_name=MODEL_NAME,
        generation_config=GenerationConfig(temperature=CLIENT_TEMPERATURE),
        safety_settings=SAFETY_SETTINGS,
    )

def build_supervisor_model():
    genai.configure(api_key=get_current_api_key())
    return genai.GenerativeModel(
        model_name=MODEL_NAME,
        generation_config=GenerationConfig(temperature=SUPERVISOR_TEMPERATURE),
        safety_settings=SAFETY_SETTINGS,
    )

def normalize_role(role_value):
    role = str(role_value).strip().lower()
    if role in ["assistant", "model", "ai", "client", "個案"]: return "model"
    return "user"

def clean_loaded_history(rows):
    cleaned = []
    for _, row in rows.iterrows():
        role = normalize_role(row.get("role", "user"))
        content = str(row.get("content", "")).strip()
        if not content: continue
        hidden_prompt_patterns = ["你是個案", "絕對不要扮演諮商師", "最高指令"]
        if any(p in content for p in hidden_prompt_patterns): continue
        cleaned.append({"role": role, "parts": [content]})
    return cleaned


def history_to_gemini_format(exclude_last_user=False):
    hist = st.session_state.history
    if exclude_last_user and hist and hist[-1]["role"] == "user":
        hist = hist[:-1]

    formatted = []
    
    # 🌟 修正點 2：強制錨點。將角色提示詞鎖死在歷史的「第一句」，根絕忘記角色的問題
    system_prompt = get_client_system_instruction()
    formatted.append({"role": "user", "parts": [system_prompt]})
    formatted.append({"role": "model", "parts": ["(坐在椅子上等待諮商師開口...)"]})

    for msg in hist:
        role = normalize_role(msg["role"])
        content = msg["parts"][0] if "parts" in msg else msg.get("content", "")
        if not content: continue
        formatted.append({"role": role, "parts": [content]})

    return formatted

def rebuild_chat_session(exclude_last_user=False):
    model = build_client_model()
    hist = history_to_gemini_format(exclude_last_user=exclude_last_user)
    st.session_state.chat_session = model.start_chat(history=hist)

def ensure_chat_session():
    if st.session_state.chat_session is None and st.session_state.is_started:
        rebuild_chat_session(exclude_last_user=False)


# 🌟 修正點 3：擴充抓取 AI 角色錯亂的敏感字眼
def looks_like_role_confusion(text):
    patterns = [
        r"作為.*諮商師", r"身為.*諮商師", r"我是.*諮商師", r"作為.*助人者",
        r"身為.*助人者", r"諮商師.*可以", r"助人者.*可以", r"你可以這樣",
        r"以下是.*建議", r"我的評估是", r"技巧評分", r"督導回饋",
        r"這是一個很好的", r"同理心", r"做得很好", r"我們今天的晤談目標"
    ]
    return any(re.search(p, text) for p in patterns)


def repair_client_response(user_input, bad_response):
    repair_prompt = f"""
剛才的 AI 回應疑似違反角色設定，變成諮商師或督導了。
請完全忽略剛才的錯誤，重新生成一段「模擬個案」第一人稱的口語回應。
【助人者說】：{user_input}
【重寫要求】：只能用個案第一人稱。絕對不可給建議或分析技巧。
"""
    model = build_client_model()
    resp = model.generate_content(repair_prompt, safety_settings=SAFETY_SETTINGS)
    return resp.text


def send_client_message_with_failover(user_input):
    ensure_chat_session()
    waited_once = False

    while True:
        try:
            response = st.session_state.chat_session.send_message(user_input)
            response_text = response.text

            if looks_like_role_confusion(response_text):
                repaired = repair_client_response(user_input, response_text)
                response_text = repaired
                st.session_state.history.append({"role": "model", "parts": [response_text]})
                rebuild_chat_session(exclude_last_user=False)
                return response_text

            return response_text

        except Exception as e:
            err_text = str(e)
            if "429" in err_text or "Quota" in err_text:
                if switch_to_next_key():
                    st.toast(f"🔄 API 額度已滿，切換至下一組 Key。", icon="🛡️")
                    rebuild_chat_session(exclude_last_user=True)
                    continue
                if not waited_once:
                    waited_once = True
                    st.warning("⏳ API 額度暫時滿載，等待 20 秒自動重試。")
                    time.sleep(20)
                    rebuild_chat_session(exclude_last_user=True)
                    continue
            raise e

def generate_supervisor_feedback_with_failover(prompt):
    waited_once = False
    while True:
        try:
            model = build_supervisor_model()
            resp = model.generate_content(prompt)
            return resp.text
        except Exception as e:
            err_text = str(e)
            if "429" in err_text or "Quota" in err_text:
                if switch_to_next_key(): continue
                if not waited_once:
                    waited_once = True
                    st.info("⏳ 督導評分：API 額度滿載，等待 20 秒重試。")
                    time.sleep(20)
                    continue
            raise e

def reset_practice_state():
    for k in ["history", "chat_session", "is_ended", "supervisor_feedback", "is_started", "context_data"]:
        if k in st.session_state: del st.session_state[k]


# =========================================================
# 側邊欄
# =========================================================
st.sidebar.title("⚙️ 系統設定")

api_input = st.sidebar.text_area(
    "🔑 輸入 Gemini API Key (多組請用換行或逗號分隔)",
    value="\n".join(st.session_state.api_keys),
)
st.session_state.api_keys = parse_api_keys(api_input)

if st.session_state.is_logged_in:
    st.sidebar.markdown("---")
    st.sidebar.write(f"👤 當前使用者：**{st.session_state.student_id}**")
    if st.sidebar.button("🚪 登出系統"):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()


# =========================================================
# 畫面 0：學號與 OTP 驗證
# =========================================================
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
            masked_email = st.session_state.target_email[:3] + "***@" + st.session_state.target_email.split("@")[-1]
            st.success(f"📧 驗證碼已寄至您的信箱：{masked_email}")
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
                    st.session_state.generated_otp = ""
                    st.rerun()


# =========================================================
# 畫面 1：演練設定
# =========================================================
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
            if not st.session_state.api_keys: st.error("❌ 請先在左側欄填寫至少一組 API Key。")
            else:
                st.session_state.context_data = {
                    "case": sel_case, "session_num": s_num, "relation": rel, "context": ctx_t,
                }
                st.session_state.current_key_index = 0
                st.session_state.history = []
                st.session_state.chat_session = None
                st.session_state.is_ended = False
                st.session_state.supervisor_feedback = ""
                st.session_state.is_started = True
                rebuild_chat_session(exclude_last_user=False)
                st.rerun()

    with tab2:
        st.write("讀取舊紀錄時，請同時指定本次要延續的個案設定。")
        load_case = st.selectbox("選擇舊紀錄對應個案：", list(CASES.keys()), key="load_case_select")
        load_rel = st.selectbox("目前關係品質：", ["新開案", "陌生疏離", "逐漸建立信任", "投契穩固"], key="load_rel_select")
        load_context = st.text_area("舊紀錄補充說明：", key="load_context_text")
        up_f = st.file_uploader("上傳先前下載的對話紀錄 (CSV)", type="csv")

        if up_f and st.button("📂 載入進度"):
            if not st.session_state.api_keys: st.error("❌ 請先在左側欄填寫至少一組 API Key。")
            else:
                try:
                    df = pd.read_csv(up_f)
                    cleaned_history = clean_loaded_history(df)
                    st.session_state.context_data = {
                        "case": load_case, "session_num": 1, "relation": load_rel, "context": load_context,
                    }
                    st.session_state.current_key_index = 0
                    st.session_state.history = cleaned_history
                    st.session_state.chat_session = None
                    st.session_state.is_started = True
                    st.session_state.is_ended = False
                    st.session_state.supervisor_feedback = ""
                    rebuild_chat_session(exclude_last_user=False)
                    st.rerun()
                except Exception as e: st.error(f"讀取 CSV 失敗：{e}")


# =========================================================
# 畫面 2：對話演練
# =========================================================
elif st.session_state.is_started and not st.session_state.is_ended:
    ensure_chat_session()
    st.title(f"🗣️ 模擬晤談中 ({st.session_state.context_data.get('case')})")

    with st.expander("📄 個案設定與前情提要", expanded=True):
        st.markdown(get_case_description())

    if not st.session_state.history:
        with st.chat_message("assistant"): st.write(st.session_state.initial_client_message)

    for m in st.session_state.history:
        role = "assistant" if m["role"] == "model" else "user"
        with st.chat_message(role): st.write(m["parts"][0])

    u_in = st.chat_input("請輸入回應...")

    if u_in:
        st.session_state.history.append({"role": "user", "parts": [u_in]})
        with st.chat_message("user"): st.write(u_in)

        with st.spinner("個案思考中..."):
            try:
                response_text = send_client_message_with_failover(u_in)
                if not (st.session_state.history and st.session_state.history[-1]["role"] == "model" and st.session_state.history[-1]["parts"][0] == response_text):
                    st.session_state.history.append({"role": "model", "parts": [response_text]})
                st.rerun()
            except Exception as e:
                if st.session_state.history and st.session_state.history[-1]["role"] == "user":
                    st.session_state.history.pop()
                st.error(f"連線異常：{e}")

    st.markdown("---")
    if st.button("🛑 結束並獲取督導回饋"):
        st.session_state.is_ended = True
        st.rerun()


# =========================================================
# 畫面 3：督導報告
# =========================================================
elif st.session_state.is_ended:
    st.title("📋 臨床督導回饋報告")

    if not st.session_state.supervisor_feedback:
        with st.spinner("👨‍🏫 審閱紀錄中..."):
            log = "\n".join([f"{'助人者' if m['role'] == 'user' else '個案'}: {m['parts'][0]}" for m in st.session_state.history])
            final_prompt = f"{SUPERVISOR_PROMPT}\n\n【待評估對話紀錄】\n{log}"
            try:
                report = generate_supervisor_feedback_with_failover(final_prompt)
                st.session_state.supervisor_feedback = report
                st.rerun()
            except Exception as e:
                if "safety_ratings" in str(e):
                    st.error("⚠️ 督導生成失敗：對話內容可能觸發 Google 底層安全防護。請先下載對話紀錄。")
                else:
                    st.error(f"督導生成失敗：{e}")

    if st.session_state.supervisor_feedback:
        st.markdown(st.session_state.supervisor_feedback)

    df_s = pd.DataFrame([{"role": m["role"], "content": m["parts"][0]} for m in st.session_state.history])
    st.download_button(
        "💾 下載紀錄 (CSV)",
        data=df_s.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{st.session_state.student_id}_報告.csv",
        mime="text/csv",
    )

    if st.button("🔄 返回首頁"):
        reset_practice_state()
        st.rerun()
