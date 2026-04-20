# --- 畫面 3：督導回饋與綜合下載區 ---
elif st.session_state.is_ended:
    if not st.session_state.supervisor_feedback:
        st.markdown("---")
        # 🌟 修正點 1: 顯示明確進度條
        with st.spinner("👨‍🏫 臨床督導正在審閱對話並進行 15 項技巧評分..."):
            log_text = ""
            try:
                # 🌟 修正點 2: 更嚴謹的歷史紀錄解析
                for msg in st.session_state.history[1:]:
                    role_str = "助人者" if msg["role"] == "user" else "個案"
                    # 安全讀取 content 或 parts
                    content = ""
                    if "parts" in msg:
                        content = msg["parts"][0]
                    elif "content" in msg:
                        content = msg["content"]
                    
                    if content:
                        log_text += f"{role_str}: {content}\n"
                
                ctx = st.session_state.context_data
                final_prompt = f"{SUPERVISOR_PROMPT}\n\n[受訓者設定的晤談脈絡]\n第{ctx.get('session_num','-')}次會談\n關係品質：{ctx.get('relation','-')}\n\n[對話紀錄]\n{log_text}"
                
                # 🌟 修正點 3: 確保 API Key 重新載入並使用穩定模型 (1.5-flash)
                current_key = st.session_state.api_keys[st.session_state.current_key_index]
                genai.configure(api_key=current_key)
                
                # 建議使用 gemini-1.5-flash 或 gemini-1.5-pro (後者更聰明但較慢)
                supervisor_model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash", 
                    generation_config=GenerationConfig(temperature=0.0)
                )
                
                # 執行生成
                feedback_resp = supervisor_model.generate_content(final_prompt)
                
                if feedback_resp.text:
                    st.session_state.supervisor_feedback = feedback_resp.text
                else:
                    st.session_state.supervisor_feedback = "⚠️ 督導模型回傳空值，請嘗試重新點擊生成。"
                    
            except Exception as e:
                # 🌟 修正點 4: 輸出更詳細的錯誤資訊方便排除問題
                error_msg = str(e)
                st.error(f"產生督導回饋時發生錯誤: {error_msg}")
                if "429" in error_msg:
                    st.warning("⚠️ API 次數已達上限，請更換 Key 或稍後再試。")
                st.session_state.supervisor_feedback = f"無法生成督導回饋。錯誤訊息：{error_msg}"

            st.rerun()

    # --- 顯示報告與下載區域 (保持不變) ---
    if st.session_state.supervisor_feedback:
        st.markdown("## 📋 臨床督導回饋報告 (15項技巧評估)")
        st.info("若下方回饋未顯示，請確認 API Key 是否有效並重啟晤談。")
        st.markdown(st.session_state.supervisor_feedback)
        
        # 準備下載內容... (後續下載程式碼維持原本邏輯即可)
