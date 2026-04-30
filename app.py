import os
import re
import time
import random
import smtplib
from email.mime.text import MIMEText

import pandas as pd
import streamlit as st
import google.generativeai as genai
from google.generativeai.types import GenerationConfig


# =========================================================
# 系統與頁面設定
# =========================================================
st.set_page_config(
    page_title="助人技巧 AI 模擬系統",
    layout="wide",
    page_icon="🧑‍🏫",
)

MODEL_NAME = "gemini-2.5-flash-lite"

CLIENT_TEMPERATURE = 0.4
SUPERVISOR_TEMPERATURE = 0.0

MAX_CLIENT_OUTPUT_TOKENS = 220
MAX_MEMORY_OUTPUT_TOKENS = 700
MAX_SUPERVISOR_CHUNK_OUTPUT_TOKENS = 900
MAX_SUPERVISOR_FINAL_OUTPUT_TOKENS = 2200

RECENT_TURNS_FOR_CLIENT = 8
MEMORY_UPDATE_EVERY_MESSAGES = 8
SUPERVISOR_CHUNK_SIZE = 12

KEY_COOLDOWN_SECONDS = 90
RETRY_WAIT_SECONDS = 20


# =========================================================
# Secrets 設定：只放寄信帳號與白名單，不放 Gemini API Key
# =========================================================
def safe_secret_get(section, default=None):
    try:
        return st.secrets.get(section, default)
    except Exception:
        return default


def load_email_config():
    email_cfg = safe_secret_get("email", {}) or {}
    sender = str(email_cfg.get("sender", os.getenv("SENDER_EMAIL", ""))).strip()
    password = str(email_cfg.get("password", os.getenv("SENDER_PASSWORD", ""))).strip()
    return sender, password


def load_whitelist():
    raw = safe_secret_get("whitelist", {}) or {}
    return {str(k).strip().upper(): str(v).strip() for k, v in dict(raw).items()}


SENDER_EMAIL, SENDER_PASSWORD = load_email_config()
WHITELIST = load_whitelist()


# =========================================================
# AI 安全設定
# =========================================================
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


# =========================================================
# 預設個案庫
# =========================================================
CASES = {
    "【人際焦慮】小明 (大學生)": "小明是一名大二男生，主訴是嚴重的人際焦慮。他害怕上台報告，總覺得同學在背後嘲笑他，導致最近開始逃避去學校。",
    "【生涯迷惘】小華 (應屆畢業生)": "小華是即將畢業的大四女生，對於未來感到極度迷惘。父母希望她考公務員，但她內心想從事藝術工作，兩者衝突讓她每天失眠。",
    "【情緒低落】阿建 (科技業工程師)": "阿建今年30歲，剛經歷分手，加上工作壓力大，近期表現出明顯的憂鬱傾向。",
    "【自訂個案】": "請依照教師或使用者在前情提要中輸入的內容扮演個案。",
}


HILL_SKILLS_TEXT = """
1. 專注與傾聽
2. 開放式問句
3. 封閉式問句
4. 重述
5. 情感反映
6. 摘要
7. 探索想法
8. 探索情緒
9. 探索行為
10. 具體化
11. 溫和挑戰
12. 詮釋或重新框架
13. 即時性
14. 資訊提供或心理教育
15. 行動計畫或問題解決
""".strip()


SUPERVISOR_PROMPT = f"""
你是一位資深的諮商心理師臨床督導。請根據以下助人對話紀錄，
評估受訓者在 Hill 助人技巧的使用品質。

請使用繁體中文，依序給出：

一、質性總體評估；
二、15項技巧評分，每項 0-5 分，並簡短說明依據；
三、具體改進建議；
四、可替代回應示範；
五、下一次演練目標。

15項技巧如下：
{HILL_SKILLS_TEXT}
""".strip()


# =========================================================
# Session State 初始化
# =========================================================
def init_session_state():
    defaults = {
        "api_keys": [],
        "current_key_index": 0,
        "key_cooldowns": {},
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
        "case_memory": "",
        "last_memory_update_len": 0,
        "client_system_instruction_fallback": False,
        "needs_chat_rebuild": False,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# =========================================================
# API Key 工具函式：學生自行輸入
# =========================================================
def parse_api_keys(raw_text):
    if not raw_text:
        return []

    if isinstance(raw_text, list):
        return [str(k).strip() for k in raw_text if str(k).strip()]

    return [k.strip() for k in re.split(r"[\n,]+", str(raw_text)) if k.strip()]


def get_current_api_key():
    if not st.session_state.api_keys:
        raise RuntimeError("尚未輸入任何 Gemini API Key。請在左側欄貼上自己的 Gemini API Key。")

    if st.session_state.current_key_index >= len(st.session_state.api_keys):
        st.session_state.current_key_index = 0

    return st.session_state.api_keys[st.session_state.current_key_index]


def mark_current_key_cooldown(seconds=KEY_COOLDOWN_SECONDS):
    try:
        key = get_current_api_key()
        st.session_state.key_cooldowns[key] = time.time() + seconds
    except Exception:
        pass


def switch_to_next_key():
    if not st.session_state.api_keys:
        return False

    now = time.time()
    total = len(st.session_state.api_keys)

    for step in range(1, total + 1):
        idx = (st.session_state.current_key_index + step) % total
        key = st.session_state.api_keys[idx]

        if st.session_state.key_cooldowns.get(key, 0) <= now:
            st.session_state.current_key_index = idx
            return True

    return False


def is_quota_error(err):
    text = str(err).lower()
    return any(x in text for x in ["429", "quota", "rate limit", "resource_exhausted"])


# =========================================================
# 個案設定與歷史處理
# =========================================================
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
""".strip()

    if extra_context:
        description += f"\n\n【前情提要／補充資料】\n{extra_context}"

    return description


def get_client_system_instruction():
    return f"""
你正在參與一個「心理諮商演練」的角色扮演。

【最高指令】
你永遠只能扮演「模擬個案」。
不可脫離角色。
不可扮演諮商師、老師、督導、助人者或 AI。
不可分析助人技巧。
不可給助人者建議。
不可評分。
不可產生督導回饋。

【個案設定】
{get_case_description()}

【固定角色規則】
1. 必須用第一人稱「我」自然回應。
2. 要展現該個案應有的情緒、猶豫、防衛、困惑或信任程度。
3. 回應長度維持 2 到 5 句，保持口語化。
4. 若助人者問得太急、太像審問、太快給建議，請表現出抗拒、停頓、困惑或退縮。
5. 不可說「作為諮商師」、「你可以這樣回應」、「這是一個很好的技巧」、「我的建議是」。
""".strip()


def normalize_role(role_value):
    role = str(role_value).strip().lower()

    if role in ["assistant", "model", "ai", "client", "個案"]:
        return "model"

    return "user"


def clean_loaded_history(rows):
    cleaned = []

    for _, row in rows.iterrows():
        role = normalize_role(row.get("role", "user"))
        content = str(row.get("content", "")).strip()

        if not content:
            continue

        hidden_prompt_patterns = [
            "你是個案",
            "絕對不要扮演諮商師",
            "最高指令",
            "system_instruction",
        ]

        if any(p in content for p in hidden_prompt_patterns):
            continue

        cleaned.append({"role": role, "parts": [content]})

    return cleaned


def history_to_gemini_format(exclude_last_user=False):
    hist = st.session_state.history

    if exclude_last_user and hist and hist[-1]["role"] == "user":
        hist = hist[:-1]

    recent_hist = hist[-RECENT_TURNS_FOR_CLIENT:]
    formatted = []

    if st.session_state.get("client_system_instruction_fallback"):
        formatted.append({"role": "user", "parts": [get_client_system_instruction()]})
        formatted.append({"role": "model", "parts": ["(我會維持個案角色。)"]})

    memory = st.session_state.get("case_memory", "").strip()

    if memory:
        formatted.append({
            "role": "user",
            "parts": [f"以下是先前晤談摘要，請維持個案連續性，不要逐字重複：\n{memory}"],
        })
        formatted.append({"role": "model", "parts": ["我記得前面的脈絡。"]})

    for msg in recent_hist:
        role = normalize_role(msg["role"])
        content = msg["parts"][0] if "parts" in msg else msg.get("content", "")
        content = str(content).strip()

        if content:
            formatted.append({"role": role, "parts": [content]})

    return formatted


# =========================================================
# Gemini 模型建立與回應擷取
# =========================================================
def build_client_model():
    genai.configure(api_key=get_current_api_key())

    try:
        st.session_state.client_system_instruction_fallback = False
        return genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=get_client_system_instruction(),
            generation_config=GenerationConfig(
                temperature=CLIENT_TEMPERATURE,
                max_output_tokens=MAX_CLIENT_OUTPUT_TOKENS,
            ),
            safety_settings=SAFETY_SETTINGS,
        )
    except TypeError:
        st.session_state.client_system_instruction_fallback = True
        return genai.GenerativeModel(
            model_name=MODEL_NAME,
            generation_config=GenerationConfig(
                temperature=CLIENT_TEMPERATURE,
                max_output_tokens=MAX_CLIENT_OUTPUT_TOKENS,
            ),
            safety_settings=SAFETY_SETTINGS,
        )


def build_supervisor_model(max_output_tokens=MAX_SUPERVISOR_FINAL_OUTPUT_TOKENS):
    genai.configure(api_key=get_current_api_key())

    return genai.GenerativeModel(
        model_name=MODEL_NAME,
        generation_config=GenerationConfig(
            temperature=SUPERVISOR_TEMPERATURE,
            max_output_tokens=max_output_tokens,
        ),
        safety_settings=SAFETY_SETTINGS,
    )


def extract_response_text(resp):
    try:
        text = resp.text
        if text and text.strip():
            return text.strip()
    except Exception:
        pass

    try:
        candidates = getattr(resp, "candidates", []) or []
        parts = candidates[0].content.parts
        text = "\n".join(getattr(p, "text", "") for p in parts if getattr(p, "text", ""))

        if text.strip():
            return text.strip()
    except Exception:
        pass

    feedback = getattr(resp, "prompt_feedback", "")
    raise RuntimeError(f"模型沒有回傳可用文字。{feedback}")


def generate_content_with_failover(prompt, purpose="AI生成", max_output_tokens=MAX_SUPERVISOR_FINAL_OUTPUT_TOKENS):
    waited_once = False

    while True:
        try:
            model = build_supervisor_model(max_output_tokens=max_output_tokens)
            resp = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
            return extract_response_text(resp)

        except Exception as e:
            if is_quota_error(e):
                mark_current_key_cooldown()

                if switch_to_next_key():
                    st.toast(f"{purpose}：API 暫時滿載，已切換至下一組 Key。", icon="🔄")
                    continue

                if not waited_once:
                    waited_once = True
                    st.warning(f"⏳ {purpose}：所有 Key 暫時滿載，等待 {RETRY_WAIT_SECONDS} 秒後重試。")
                    time.sleep(RETRY_WAIT_SECONDS)
                    continue

            raise e


def rebuild_chat_session(exclude_last_user=False):
    model = build_client_model()
    hist = history_to_gemini_format(exclude_last_user=exclude_last_user)
    st.session_state.chat_session = model.start_chat(history=hist)


def ensure_chat_session():
    if st.session_state.chat_session is None and st.session_state.is_started:
        rebuild_chat_session(exclude_last_user=False)


# =========================================================
# 角色錯亂偵測與修復
# =========================================================
def looks_like_role_confusion(text):
    patterns = [
        r"作為.*諮商師",
        r"身為.*諮商師",
        r"我是.*諮商師",
        r"作為.*助人者",
        r"身為.*助人者",
        r"諮商師.*可以",
        r"助人者.*可以",
        r"你可以這樣",
        r"以下是.*建議",
        r"我的評估是",
        r"技巧評分",
        r"督導回饋",
        r"這是一個很好的",
        r"同理心",
        r"做得很好",
        r"我們今天的晤談目標",
    ]

    return any(re.search(p, text) for p in patterns)


def repair_client_response(user_input, bad_response):
    prompt = f"""
剛才的 AI 回應疑似違反角色設定，變成諮商師、助人者或督導了。
請完全忽略剛才的錯誤，重新生成一段「模擬個案」第一人稱的口語回應。

【個案設定】
{get_case_description()}

【助人者說】
{user_input}

【錯誤回應】
{bad_response}

【重寫要求】
只能用個案第一人稱。
不可給建議。
不可分析技巧。
不可說自己是諮商師或督導。
請輸出 2 到 5 句自然口語回應。
""".strip()

    return generate_content_with_failover(
        prompt,
        purpose="角色修復",
        max_output_tokens=MAX_CLIENT_OUTPUT_TOKENS,
    )


def send_client_message_with_failover(user_input):
    ensure_chat_session()
    waited_once = False

    while True:
        try:
            response = st.session_state.chat_session.send_message(user_input)
            response_text = extract_response_text(response)

            if looks_like_role_confusion(response_text):
                repaired = repair_client_response(user_input, response_text)
                st.session_state.needs_chat_rebuild = True
                return repaired

            return response_text

        except Exception as e:
            if is_quota_error(e):
                mark_current_key_cooldown()

                if switch_to_next_key():
                    st.toast("個案回應：API 暫時滿載，已切換至下一組 Key。", icon="🔄")
                    rebuild_chat_session(exclude_last_user=True)
                    continue

                if not waited_once:
                    waited_once = True
                    st.warning(f"⏳ API 額度暫時滿載，等待 {RETRY_WAIT_SECONDS} 秒自動重試。")
                    time.sleep(RETRY_WAIT_SECONDS)
                    rebuild_chat_session(exclude_last_user=True)
                    continue

            raise e


# =========================================================
# Token 節省：個案記憶摘要
# =========================================================
def format_log(messages):
    return "\n".join([
        f"{'助人者' if m['role'] == 'user' else '個案'}: {m['parts'][0]}"
        for m in messages
    ])


def maybe_update_case_memory():
    hist = st.session_state.history

    if len(hist) < RECENT_TURNS_FOR_CLIENT + MEMORY_UPDATE_EVERY_MESSAGES:
        return

    summary_until = max(0, len(hist) - RECENT_TURNS_FOR_CLIENT)
    last_len = int(st.session_state.get("last_memory_update_len", 0))

    if summary_until <= last_len:
        return

    delta_hist = hist[last_len:summary_until]

    if len(delta_hist) < MEMORY_UPDATE_EVERY_MESSAGES:
        return

    prompt = f"""
請把以下心理諮商角色扮演紀錄壓縮成「個案狀態摘要」，供後續模擬個案維持連續性。

請保留：
1. 個案目前主要困擾；
2. 情緒狀態；
3. 對助人者的信任、抗拒或關係變化；
4. 已談過的重要事件；
5. 個案尚未說出口但可延續的內在矛盾。

不要加入督導評語。
不要評分。
不要建議助人者怎麼做。
請用 350 字以內繁體中文摘要。

【既有摘要】
{st.session_state.get("case_memory", "")}

【新增對話】
{format_log(delta_hist)}
""".strip()

    try:
        new_memory = generate_content_with_failover(
            prompt,
            purpose="壓縮對話記憶",
            max_output_tokens=MAX_MEMORY_OUTPUT_TOKENS,
        )

        st.session_state.case_memory = new_memory
        st.session_state.last_memory_update_len = summary_until
        rebuild_chat_session(exclude_last_user=False)

    except Exception:
        pass


# =========================================================
# 督導報告：分段生成
# =========================================================
def chunk_history_for_supervisor(history, chunk_size=SUPERVISOR_CHUNK_SIZE):
    for i in range(0, len(history), chunk_size):
        yield history[i:i + chunk_size]


def generate_supervisor_feedback_chunked():
    history = st.session_state.history

    if not history:
        return "目前沒有可評估的對話紀錄。"

    partial_reports = []

    for idx, chunk in enumerate(chunk_history_for_supervisor(history), start=1):
        chunk_prompt = f"""
你是一位資深諮商心理師臨床督導。
請先針對第 {idx} 段對話做局部評估。

請包含：
一、此段助人者做得好的地方；
二、此段主要問題；
三、Hill 助人技巧觀察；
四、可替代回應示範。

【個案設定】
{get_case_description()}

【第 {idx} 段對話】
{format_log(chunk)}
""".strip()

        partial = generate_content_with_failover(
            chunk_prompt,
            purpose=f"督導分段評估 {idx}",
            max_output_tokens=MAX_SUPERVISOR_CHUNK_OUTPUT_TOKENS,
        )

        partial_reports.append(f"【第 {idx} 段局部評估】\n{partial}")

    merge_prompt = f"""
{SUPERVISOR_PROMPT}

以下是各段局部評估。請整合成一份完整、清楚、可給學生閱讀的督導報告。
不要只是摘要分段內容，要形成整體判斷。

【個案設定】
{get_case_description()}

【分段局部評估】
{chr(10).join(partial_reports)}
""".strip()

    return generate_content_with_failover(
        merge_prompt,
        purpose="督導總報告",
        max_output_tokens=MAX_SUPERVISOR_FINAL_OUTPUT_TOKENS,
    )


# =========================================================
# OTP 發信函式
# =========================================================
def send_otp_email(receiver_email, otp_code):
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        return False, "寄件信箱尚未設定。請在 Streamlit Secrets 設定 email.sender 與 email.password。"

    msg = MIMEText(
        f"同學您好：\n\n"
        f"您的系統登入驗證碼為：【 {otp_code} 】\n\n"
        f"請於網頁輸入此 6 位數代碼完成身分確認。\n"
        f"祝演練順利！",
        _charset="utf-8",
    )

    msg["Subject"] = "【助人技巧 AI 模擬系統】登入驗證碼"
    msg["From"] = SENDER_EMAIL
    msg["To"] = receiver_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD.replace(" ", ""))
            server.send_message(msg)

        return True, "發送成功"

    except Exception as e:
        return False, str(e)


def reset_practice_state():
    keys_to_reset = [
        "history",
        "chat_session",
        "is_ended",
        "supervisor_feedback",
        "is_started",
        "context_data",
        "case_memory",
        "last_memory_update_len",
        "needs_chat_rebuild",
        "current_key_index",
        "key_cooldowns",
    ]

    for key in keys_to_reset:
        if key in st.session_state:
            del st.session_state[key]

    init_session_state()


# =========================================================
# 側邊欄
# =========================================================
st.sidebar.title("⚙️ 系統設定")

if st.session_state.is_logged_in:
    st.sidebar.write(f"👤 當前使用者：**{st.session_state.student_id}**")
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔑 Gemini API Key")

    st.sidebar.caption(
        "請貼上你自己的 Gemini API Key。Key 只會在本次使用期間暫存在 session，"
        "不會寫入 GitHub 或 Streamlit Secrets。"
    )

    student_key_1 = st.sidebar.text_input(
        "Gemini API Key 1",
        type="password",
        key="student_api_key_1",
    )

    student_key_2 = st.sidebar.text_input(
        "Gemini API Key 2（選填）",
        type="password",
        key="student_api_key_2",
    )

    st.session_state.api_keys = parse_api_keys([student_key_1, student_key_2])

    if st.session_state.api_keys:
        if st.session_state.current_key_index >= len(st.session_state.api_keys):
            st.session_state.current_key_index = 0

        st.sidebar.success(f"已輸入 {len(st.session_state.api_keys)} 組 API Key。")
        st.sidebar.write(
            f"目前使用：第 {st.session_state.current_key_index + 1} / {len(st.session_state.api_keys)} 組"
        )
    else:
        st.sidebar.warning("請先輸入至少 1 組 Gemini API Key。")

    st.sidebar.caption(
        "提醒：若兩組 API Key 來自同一個 Google Cloud project，Gemini quota 通常仍會一起計算。"
    )

    st.sidebar.markdown("---")

    if st.sidebar.button("🚪 登出系統"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]

        st.rerun()

else:
    st.sidebar.info("請先登入。登入後，學生可在這裡貼上自己的 Gemini API Key。")


# =========================================================
# 畫面 0：學號與 OTP 驗證
# =========================================================
if not st.session_state.is_logged_in:
    st.title("🔐 助人技巧 AI 模擬系統")

    if not WHITELIST:
        st.warning("尚未設定學生白名單。請在 Streamlit Secrets 的 [whitelist] 區塊加入學號與信箱。")

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        if not st.session_state.otp_sent:
            st.write("請輸入您的學號，系統將寄送驗證碼至您綁定的信箱。")

            sid_input = st.text_input(
                "📝 請輸入學號 Student ID：",
                placeholder="例如：MB1132018",
            ).strip().upper()

            if st.button("發送驗證碼", type="primary", use_container_width=True):
                if sid_input in WHITELIST:
                    st.session_state.student_id = sid_input
                    st.session_state.target_email = WHITELIST[sid_input]
                    st.session_state.generated_otp = str(random.randint(100000, 999999))

                    with st.spinner("📧 正在寄送驗證碼..."):
                        ok, err = send_otp_email(
                            st.session_state.target_email,
                            st.session_state.generated_otp,
                        )

                    if ok:
                        st.session_state.otp_sent = True
                        st.rerun()
                    else:
                        st.error(f"寄送失敗：{err}")
                else:
                    st.error("❌ 該學號不在白名單中，請聯繫授課教師。")

        else:
            email = st.session_state.target_email
            masked_email = email[:3] + "***@" + email.split("@")[-1]

            st.success(f"📧 驗證碼已寄至您的信箱：{masked_email}")

            otp_val = st.text_input("🔑 請輸入 6 位數驗證碼：", max_chars=6)

            c1, c2 = st.columns(2)

            with c1:
                if st.button("確認登入", type="primary", use_container_width=True):
                    if otp_val == st.session_state.generated_otp:
                        st.session_state.is_logged_in = True
                        st.rerun()
                    else:
                        st.error("❌ 驗證碼錯誤。")

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

    tab1, tab2 = st.tabs(["🆕 開啟新晤談", "📂 讀取舊紀錄 CSV"])

    with tab1:
        c1, c2 = st.columns(2)

        with c1:
            sel_case = st.selectbox("1. 選擇模擬個案：", list(CASES.keys()))
            s_num = st.number_input("2. 晤談次數：", min_value=1, value=1)

        with c2:
            rel = st.selectbox("3. 目前關係品質：", ["新開案", "陌生疏離", "逐漸建立信任", "投契穩固"])

        ctx_t = st.text_area("4. 前情提要 / 補充：")

        if st.button("🚀 開始演練", type="primary"):
            if not st.session_state.api_keys:
                st.error("❌ 請先在左側欄輸入至少 1 組自己的 Gemini API Key。")
            else:
                st.session_state.context_data = {
                    "case": sel_case,
                    "session_num": s_num,
                    "relation": rel,
                    "context": ctx_t,
                }
                st.session_state.current_key_index = 0
                st.session_state.history = []
                st.session_state.chat_session = None
                st.session_state.is_ended = False
                st.session_state.supervisor_feedback = ""
                st.session_state.case_memory = ""
                st.session_state.last_memory_update_len = 0
                st.session_state.is_started = True

                try:
                    rebuild_chat_session(exclude_last_user=False)
                    st.rerun()
                except Exception as e:
                    st.session_state.is_started = False
                    st.error(f"無法啟動 Gemini：{e}")

    with tab2:
        st.write("讀取舊紀錄時，請同時指定本次要延續的個案設定。")

        load_case = st.selectbox("選擇舊紀錄對應個案：", list(CASES.keys()), key="load_case_select")
        load_rel = st.selectbox("目前關係品質：", ["新開案", "陌生疏離", "逐漸建立信任", "投契穩固"], key="load_rel_select")
        load_context = st.text_area("舊紀錄補充說明：", key="load_context_text")
        up_f = st.file_uploader("上傳先前下載的對話紀錄 CSV", type="csv")

        if up_f and st.button("📂 載入進度"):
            if not st.session_state.api_keys:
                st.error("❌ 請先在左側欄輸入至少 1 組自己的 Gemini API Key。")
            else:
                try:
                    df = pd.read_csv(up_f)
                    cleaned_history = clean_loaded_history(df)

                    st.session_state.context_data = {
                        "case": load_case,
                        "session_num": 1,
                        "relation": load_rel,
                        "context": load_context,
                    }
                    st.session_state.current_key_index = 0
                    st.session_state.history = cleaned_history
                    st.session_state.chat_session = None
                    st.session_state.is_started = True
                    st.session_state.is_ended = False
                    st.session_state.supervisor_feedback = ""
                    st.session_state.case_memory = ""
                    st.session_state.last_memory_update_len = 0

                    maybe_update_case_memory()
                    rebuild_chat_session(exclude_last_user=False)
                    st.rerun()

                except Exception as e:
                    st.error(f"讀取 CSV 失敗：{e}")


# =========================================================
# 畫面 2：對話演練
# =========================================================
elif st.session_state.is_started and not st.session_state.is_ended:
    if not st.session_state.api_keys:
        st.error("❌ 你的 Gemini API Key 已清空。請在左側欄重新輸入，或返回首頁重新開始。")
        st.stop()

    ensure_chat_session()

    st.title(f"🗣️ 模擬晤談中 ({st.session_state.context_data.get('case')})")

    with st.expander("📄 個案設定與前情提要", expanded=True):
        st.markdown(get_case_description())

    if st.session_state.case_memory:
        with st.expander("🧠 系統壓縮記憶", expanded=False):
            st.write(st.session_state.case_memory)

    if not st.session_state.history:
        with st.chat_message("assistant"):
            st.write(st.session_state.initial_client_message)

    for m in st.session_state.history:
        role = "assistant" if m["role"] == "model" else "user"

        with st.chat_message(role):
            st.write(m["parts"][0])

    u_in = st.chat_input("請輸入回應...")

    if u_in:
        st.session_state.history.append({"role": "user", "parts": [u_in]})

        with st.chat_message("user"):
            st.write(u_in)

        with st.spinner("個案思考中..."):
            try:
                response_text = send_client_message_with_failover(u_in)
                st.session_state.history.append({"role": "model", "parts": [response_text]})

                if st.session_state.get("needs_chat_rebuild"):
                    st.session_state.needs_chat_rebuild = False
                    rebuild_chat_session(exclude_last_user=False)

                maybe_update_case_memory()
                st.rerun()

            except Exception as e:
                if st.session_state.history and st.session_state.history[-1]["role"] == "user":
                    st.session_state.history.pop()

                st.error(f"連線異常：{e}")

    st.markdown("---")

    c1, c2 = st.columns([1, 3])

    with c1:
        if st.button("🛑 結束並獲取督導回饋", type="primary"):
            st.session_state.is_ended = True
            st.rerun()

    with c2:
        st.caption(
            f"完整紀錄目前 {len(st.session_state.history)} 則；"
            f"實際對話只送最近 {RECENT_TURNS_FOR_CLIENT} 則加摘要，以節省 token。"
        )


# =========================================================
# 畫面 3：督導報告
# =========================================================
elif st.session_state.is_ended:
    if not st.session_state.api_keys:
        st.error("❌ 你的 Gemini API Key 已清空。請在左側欄重新輸入後再產生督導報告。")
        st.stop()

    st.title("📋 臨床督導回饋報告")

    if not st.session_state.supervisor_feedback:
        with st.spinner("👨‍🏫 正在分段審閱紀錄並生成督導報告..."):
            try:
                report = generate_supervisor_feedback_chunked()
                st.session_state.supervisor_feedback = report
                st.rerun()
            except Exception as e:
                if "safety" in str(e).lower() or "blocked" in str(e).lower():
                    st.error("⚠️ 督導生成失敗：對話內容可能觸發 Google 底層安全防護。請先下載對話紀錄。")
                else:
                    st.error(f"督導生成失敗：{e}")

    if st.session_state.supervisor_feedback:
        st.markdown(st.session_state.supervisor_feedback)

    df_s = pd.DataFrame([
        {"role": m["role"], "content": m["parts"][0]}
        for m in st.session_state.history
    ])

    st.download_button(
        "💾 下載完整對話紀錄 CSV",
        data=df_s.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{st.session_state.student_id}_對話紀錄.csv",
        mime="text/csv",
    )

    if st.session_state.supervisor_feedback:
        st.download_button(
            "💾 下載督導報告 TXT",
            data=st.session_state.supervisor_feedback.encode("utf-8-sig"),
            file_name=f"{st.session_state.student_id}_督導報告.txt",
            mime="text/plain",
        )

    if st.button("🔄 返回首頁"):
        reset_practice_state()
        st.rerun()
