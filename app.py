import streamlit as st
import asyncio
import edge_tts
import urllib.parse
import urllib.request
import json
import re

# تنظیمات صفحه وب
st.set_page_config(
    page_title="آموزش زبان - تلفظ و ترجمه تعاملی",
    page_icon="🗣️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# فونت و استایل‌های سفارشی برای نمایش بهتر در موبایل
st.markdown("""
    <style>
    body {
        direction: rtl;
        font-family: 'Tahoma', sans-serif;
    }
    .word-btn {
        display: inline-block;
        background-color: #EBF5FB;
        color: #2980B9;
        border: 1px solid #AED6F1;
        padding: 6px 12px;
        margin: 4px;
        border-radius: 8px;
        font-size: 20px;
        font-weight: bold;
        cursor: pointer;
        text-decoration: none;
    }
    .word-btn:hover {
        background-color: #3498DB;
        color: white;
    }
    .meaning-box {
        background-color: #F2F4F4;
        border-right: 5px solid #27AE60;
        padding: 15px;
        border-radius: 5px;
        font-size: 18px;
        margin-top: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# تابع ترجمه فارسی
def get_translation(word, lang_code):
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={lang_code}&tl=fa&dt=t&q={urllib.parse.quote(word)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req, timeout=3)
        data = json.loads(response.read().decode('utf-8'))
        return data[0][0][0]
    except Exception:
        return "معنی پیدا نشد (اتصال اینترنت را بررسی کنید)"

# ساخت فایل صوتی با edge-tts
async def generate_speech(text, voice, speed_percent):
    rate_str = f"{speed_percent:+d}%"
    communicate = edge_tts.Communicate(text, voice, rate=rate_str)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return audio_data

# --- رابط کاربری ---
st.title("🗣️ آموزش تعاملی زبان (ویژه موبایل و وب)")

col_lang, col_speed = st.columns([1, 1])

with col_lang:
    language = st.selectbox("🌐 انتخاب زبان متن:", ["Türkçe (ترکی)", "English (انگلیسی)"])

with col_speed:
    speed = st.slider("⏱ سرعت خواندن کل متن (درصد):", min_value=-50, max_value=20, value=-25)

voice_code = "tr-TR-AhmetNeural" if "Türkçe" in language else "en-US-GuyNeural"
lang_code = "tr" if "Türkçe" in language else "en"

# ورود متن اصلی
input_text = st.text_area("📖 متن کامل خود را وارد کنید:", height=150, value="Salih Hikaye Serisi, başta Suriyeli çocuklar olmak üzere ülkemizde bulunan yabancılara Türkçe Öğretimi amacıyla hazırlanmıştır.")

col_btn1, col_btn2 = st.columns([1, 1])

# ۱. پخش صوتی کل متن
with col_btn1:
    if st.button("🔊 پخش کل متن با صدای طبیعی", use_container_width=True):
        if input_text.strip():
            with st.spinner("در حال تولید فایل صوتی..."):
                audio_bytes = asyncio.run(generate_speech(input_text, voice_code, speed))
                st.audio(audio_bytes, format="audio/mp3")
        else:
            st.warning("لطفاً متنی وارد کنید.")

# ۲. دانلود فایل صوتی
with col_btn2:
    if input_text.strip():
        audio_bytes_dl = asyncio.run(generate_speech(input_text, voice_code, speed))
        st.download_button(
            label="💾 دانلود فایل صوتی MP3",
            data=audio_bytes_dl,
            file_name="speech.mp3",
            mime="audio/mp3",
            use_container_width=True
        )

st.divider()
st.subheader("👆 روی هر کلمه کلیک یا لمس کنید تا تلفظ و معنی آن را ببینید:")

# پردازش و نمایش کلمات تعاملی
if input_text.strip():
    words = re.findall(r'\b\w+\b', input_text)
    
    # بستری برای نمایش دکمه‌های کلمات
    cols = st.columns(6)
    
    selected_word = None
    for idx, word in enumerate(words):
        col_idx = idx % 6
        if cols[col_idx].button(word, key=f"btn_{idx}_{word}"):
            selected_word = word

    # اگر کلمه‌ای لمس/کلیک شد
    if selected_word or 'last_word' in st.session_state:
        word_to_show = selected_word if selected_word else st.session_state.get('last_word')
        st.session_state['last_word'] = word_to_show
        
        st.divider()
        st.markdown(f"### 🔤 کلمه انتخاب شده: **{word_to_show}**")
        
        # ترجمه کلمه
        meaning = get_translation(word_to_show, lang_code)
        st.markdown(f"<div class='meaning-box'>💡 <b>معنی فارسی:</b> {meaning}</div>", unsafe_allow_html=True)
        
        # پخش صدای کلمه انتخاب‌شده
        word_audio = asyncio.run(generate_speech(word_to_show, voice_code, -15))
        st.audio(word_audio, format="audio/mp3", autoplay=True)