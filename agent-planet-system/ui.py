# ui.py
import streamlit as st
import requests

# Cấu hình kết nối tới Backend FastAPI
API_URL = "http://127.0.0.1:8000"
USER_ID = "u1"
USER_NAME = "Mina"

# Thiết lập giao diện trang web
st.set_page_config(page_title="WildTails - Catalyst Verse", page_icon="🪐", layout="wide")

# Khởi tạo bộ nhớ tạm (Session State) cho giao diện
if "planet" not in st.session_state:
    st.session_state.planet = "Trạm trung chuyển (Chưa xác định)"
if "mood" not in st.session_state:
    st.session_state.mood = "Chưa có dữ liệu"

# ==================== SIDEBAR ====================
with st.sidebar:
    st.title("🪐 WildTails")
    st.markdown("🌌 **Vũ trụ Nhật ký của bạn**")
    st.divider()

    st.image("https://api.dicebear.com/7.x/notionists/svg?seed=Mina&backgroundColor=b6e3f4", width=100)
    st.subheader(f"Nhà thám hiểm: {USER_NAME}")

    st.markdown("### 📊 Trạng thái hiện tại")
    st.success(f"**Cảm xúc:** {st.session_state.mood}")
    st.info(f"**Hành tinh:** {st.session_state.planet}")

    st.divider()
    if st.button("🔄 Cập nhật tin nhắn mới"):
        st.rerun()
    st.caption("Mạng lưới đa tác tử kết nối qua SSE/MCP")

# ==================== MAIN CHAT ====================
st.title("Giao tiếp cùng System Agent 🤖")
st.markdown("Hãy chia sẻ nhật ký, tâm sự hoặc ý tưởng của bạn hôm nay. Hệ thống sẽ lắng nghe và đưa bạn đến hành tinh phù hợp.")

# Lấy lịch sử hội thoại từ Backend
messages = []
try:
    resp = requests.get(f"{API_URL}/api/messages", timeout=3)
    if resp.status_code == 200:
        messages = resp.json().get("messages", [])
except requests.exceptions.ConnectionError:
    pass

# Hiển thị lịch sử trò chuyện
for msg in messages:
    role = msg.get("role", "assistant")
    sender = msg.get("sender", "")
    content = msg.get("content", "")

    with st.chat_message(role):
        if role == "assistant" and sender and sender != "System Agent":
            st.markdown(f"**🤖 {sender}:** {content}")
        else:
            st.markdown(content)

# Khung nhập liệu (Chat Input)
if prompt := st.chat_input("Hôm nay bạn cảm thấy thế nào?..."):
    # Hiển thị tin nhắn của User ngay lập tức
    with st.chat_message("user"):
        st.markdown(prompt)

    # Gửi tin nhắn tới FastAPI Backend
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("Đang kết nối với não bộ AI (Ollama)... ⏳")

        try:
            payload = {
                "user_id": USER_ID,
                "user_name": USER_NAME,
                "message": prompt,
            }
            response = requests.post(f"{API_URL}/api/chat", json=payload, timeout=30)

            if response.status_code == 200:
                data = response.json()

                st.session_state.planet = data.get("assigned_planet", "Không rõ")
                st.session_state.mood = data.get("mood", "Không rõ")

                reply = data.get("agent_reply", "Hệ thống đã ghi nhận.")
                message_placeholder.markdown(reply)

                # Rerun để sidebar + chat history cập nhật từ backend
                st.rerun()
            else:
                message_placeholder.error(
                    f"Lỗi từ server: {response.status_code}. "
                    "Hãy chắc chắn cấu trúc JSON backend trả về đúng."
                )

        except requests.exceptions.ConnectionError:
            message_placeholder.error(
                "Không thể kết nối tới Backend Server. "
                "Hãy chắc chắn bạn đang chạy `python app.py` ở một Terminal khác."
            )
