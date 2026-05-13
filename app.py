# -*- coding: utf-8 -*-
"""
Streamlit app that combines:
- Browser-based text-to-speech preview (Web Speech API)
- PDF -> narrated video generator with selectable voices (gTTS or local pyttsx3)
"""
import os
import json
import shutil
import socket
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import streamlit as st
import streamlit.components.v1 as components
from gtts import gTTS
from pdf2image import convert_from_path
from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips
from PIL import Image
import pypdf
import re
import unicodedata

try:
    import pyttsx3
except ImportError:  # pyttsx3 is optional
    pyttsx3 = None

PAGE_TITLE = "講義動画＆音声読み上げツール"
DPI = 120
FPS = 12
MAX_SLIDE_WIDTH = 1280
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
ENCODE_THREADS = max(2, (os.cpu_count() or 2) - 1)
MOBILE_UPLOAD_PORT = 8502
MOBILE_UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "lecture_mobile_uploads")
JOBS_DIR = os.path.join(tempfile.gettempdir(), "lecture_video_jobs")
DEFAULT_APP_PASSWORD = "note2026"
LOCAL_MOBILE_UPLOAD_ENABLED = os.name == "nt" and os.environ.get("ENABLE_MOBILE_UPLOAD", "1") == "1"

TTS_COMPONENT = """
<div style=\"font-family: Segoe UI, sans-serif; background:#f5f7fb; padding:16px; border-radius:12px; border:1px solid #dce2ec;\">
  <h3 style=\"margin-top:0;\">音声読み上げ（ブラウザ）</h3>
  <textarea id=\"tts-text\" style=\"width:100%; min-height:140px; font-size:15px; padding:10px;\" placeholder=\"ここに読み上げたい文章を入力\"></textarea>
  <div style=\"display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin:10px 0;\">
    <label style=\"font-size:13px; display:flex; flex-direction:column; gap:4px;\">音量
      <input id=\"tts-volume\" type=\"range\" min=\"0\" max=\"1\" step=\"0.1\" value=\"1\" />
    </label>
    <label style=\"font-size:13px; display:flex; flex-direction:column; gap:4px;\">速度
      <input id=\"tts-rate\" type=\"range\" min=\"0.5\" max=\"2\" step=\"0.1\" value=\"1\" />
    </label>
    <label style=\"font-size:13px; display:flex; flex-direction:column; gap:4px;\">ピッチ
      <input id=\"tts-pitch\" type=\"range\" min=\"0.5\" max=\"2\" step=\"0.1\" value=\"1\" />
    </label>
    <label style=\"font-size:13px; display:flex; flex-direction:column; gap:4px;\">ボイス
      <select id=\"tts-voice\"></select>
    </label>
  </div>
  <div style=\"display:flex; gap:12px; margin-top:8px;\">
    <button id=\"tts-speak\" style=\"padding:10px 14px; font-size:15px; cursor:pointer;\">読み上げ</button>
    <button id=\"tts-stop\" style=\"padding:10px 14px; font-size:15px; cursor:pointer;\">停止</button>
  </div>
  <p style=\"font-size:12px; color:#555; margin-top:10px;\">ブラウザのWeb Speech APIを使用します。音声の種類はブラウザに依存します。</p>
</div>
<script>
  (function() {
    const synth = window.speechSynthesis;
    const textEl = document.getElementById("tts-text");
    const voiceEl = document.getElementById("tts-voice");
    const volumeEl = document.getElementById("tts-volume");
    const rateEl = document.getElementById("tts-rate");
    const pitchEl = document.getElementById("tts-pitch");
    const speakBtn = document.getElementById("tts-speak");
    const stopBtn = document.getElementById("tts-stop");
    let voices = [];

    function loadVoices() {
      voices = synth.getVoices().filter(v => v.lang.startsWith("ja") || v.lang.startsWith("en"));
      voiceEl.innerHTML = voices.map((v, i) => `<option value="${i}">${v.name} (${v.lang})</option>`).join("");
      if (voiceEl.options.length === 0) voiceEl.innerHTML = `<option disabled>音声が見つかりません</option>`;
    }
    loadVoices();
    if (speechSynthesis.onvoiceschanged !== undefined) {
      speechSynthesis.onvoiceschanged = loadVoices;
    }

    function speak() {
      const text = textEl.value.trim();
      if (!text) return;
      synth.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      const voice = voices[voiceEl.value];
      if (voice) utter.voice = voice;
      utter.volume = parseFloat(volumeEl.value);
      utter.rate = parseFloat(rateEl.value);
      utter.pitch = parseFloat(pitchEl.value);
      synth.speak(utter);
    }

    function stop() { synth.cancel(); }

    speakBtn.onclick = speak;
    stopBtn.onclick = stop;
  })();
</script>
"""


# -------------- Helpers --------------
def get_lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def get_latest_mobile_upload():
    if not os.path.isdir(MOBILE_UPLOAD_DIR):
        return None
    pdfs = [
        os.path.join(MOBILE_UPLOAD_DIR, name)
        for name in os.listdir(MOBILE_UPLOAD_DIR)
        if name.lower().endswith(".pdf")
    ]
    if not pdfs:
        return None
    return max(pdfs, key=os.path.getmtime)


def get_app_password():
    env_password = os.environ.get("APP_PASSWORD")
    if env_password:
        return env_password
    try:
        secret_password = st.secrets.get("APP_PASSWORD")
        if secret_password:
            return str(secret_password)
    except Exception:
        pass
    if os.name == "nt":
        return DEFAULT_APP_PASSWORD
    return ""


def require_login():
    if st.session_state.get("authenticated"):
        return True

    st.title(PAGE_TITLE)
    st.subheader("ログイン")
    app_password = get_app_password()
    if not app_password:
        st.error("アプリの合言葉が設定されていません。Streamlit Cloud の Secrets に APP_PASSWORD を設定してください。")
        return False

    password = st.text_input("合言葉", type="password")
    if st.button("ログイン", type="primary", use_container_width=True):
        if password == app_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("合言葉が違います。")
    st.info("note/Brainの記事内に記載されている合言葉を入力してください。")
    return False


def load_pdf_bytes(pdf_bytes: bytes, pdf_name: str):
    pdf_path = None
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
        tmp_pdf.write(pdf_bytes)
        pdf_path = tmp_pdf.name

    try:
        loaded_images = convert_from_path(pdf_path, dpi=DPI)
        loaded_scripts, found_any = extract_scripts_from_pdf(pdf_path, len(loaded_images))
        return {
            "fingerprint": f"{pdf_name}:{len(pdf_bytes)}",
            "images": loaded_images,
            "extracted_scripts": loaded_scripts,
            "pdf_name": pdf_name,
        }, found_any
    finally:
        try:
            if pdf_path and os.path.exists(pdf_path):
                os.unlink(pdf_path)
        except Exception:
            pass


def save_slide_image_for_video(img, img_path: str):
    if img.width > MAX_SLIDE_WIDTH:
        new_height = max(1, int(img.height * MAX_SLIDE_WIDTH / img.width))
        img = img.resize((MAX_SLIDE_WIDTH, new_height), Image.Resampling.LANCZOS)
    img.save(img_path, "JPEG", quality=88, optimize=True)


def update_job_status(job_dir: str, **updates):
    os.makedirs(job_dir, exist_ok=True)
    status_path = os.path.join(job_dir, "status.json")
    status = {}
    if os.path.exists(status_path):
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                status = json.load(f)
        except Exception:
            status = {}
    status.update(updates)
    status["updated_at"] = time.time()
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def read_job_status(job_dir: str):
    status_path = os.path.join(job_dir, "status.json")
    if not os.path.exists(status_path):
        return {}
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def list_recent_jobs(limit=5):
    if not os.path.isdir(JOBS_DIR):
        return []
    job_dirs = [
        os.path.join(JOBS_DIR, name)
        for name in os.listdir(JOBS_DIR)
        if os.path.isdir(os.path.join(JOBS_DIR, name))
    ]
    job_dirs.sort(key=os.path.getmtime, reverse=True)
    return job_dirs[:limit]


def generate_video_job(job_id, images, scripts, settings):
    job_dir = os.path.join(JOBS_DIR, job_id)
    work_dir = None
    video_clips = []
    final_video = None

    try:
        update_job_status(job_dir, state="running", progress=0, message="準備中", job_id=job_id)
        work_dir = tempfile.mkdtemp()
        slides_dir = os.path.join(work_dir, "slides")
        audio_dir = os.path.join(work_dir, "audio")
        os.makedirs(slides_dir, exist_ok=True)
        os.makedirs(audio_dir, exist_ok=True)

        update_job_status(job_dir, progress=15, message="PDFをスライド画像に変換中")
        slide_paths = []
        for idx, img in enumerate(images):
            img_path = os.path.join(slides_dir, f"slide_{idx+1:03d}.jpg")
            save_slide_image_for_video(img, img_path)
            slide_paths.append(img_path)

        update_job_status(job_dir, progress=30, message="音声を生成中")
        for idx, script in enumerate(scripts):
            script_text = (script or "").strip()
            audio_path_mp3 = os.path.join(audio_dir, f"audio_{idx+1:03d}.mp3")
            audio_path_wav = os.path.join(audio_dir, f"audio_{idx+1:03d}.wav")

            if script_text:
                if settings["engine_choice"] == "pyttsx3 (ローカル)" and pyttsx3 is not None:
                    generate_audio_pyttsx3(script_text, audio_path_wav, settings.get("pyttsx3_voice_id"), settings["voice_speed"])
                else:
                    generate_audio_gtts(script_text, audio_path_mp3, settings["voice_lang"], settings["voice_speed"])

            progress = 30 + int((idx + 1) / max(1, len(scripts)) * 30)
            update_job_status(job_dir, progress=progress, message=f"音声を生成中 ({idx + 1}/{len(scripts)})")

        update_job_status(job_dir, progress=65, message="動画クリップを作成中")
        video_clips = build_video_clips(slide_paths, audio_dir)
        if not video_clips:
            raise RuntimeError("生成できるクリップがありません。原稿が空か、音声生成に失敗しました。")

        total_duration = sum([c.duration for c in video_clips]) if video_clips else 0
        update_job_status(job_dir, progress=75, message=f"動画を書き出し中（合計 {total_duration:.1f} 秒）")
        final_video = concatenate_videoclips(video_clips, method="compose")

        output_path = os.path.join(job_dir, "lecture_video.mp4")
        final_video.write_videofile(
            output_path,
            fps=FPS,
            codec=VIDEO_CODEC,
            audio_codec=AUDIO_CODEC,
            preset="ultrafast",
            threads=ENCODE_THREADS,
            verbose=False,
            logger=None,
            temp_audiofile=os.path.join(work_dir, "temp-audio.m4a"),
            remove_temp=True,
        )

        project_output_path = os.path.join(os.getcwd(), "lecture_video.mp4")
        shutil.copy2(output_path, project_output_path)
        update_job_status(
            job_dir,
            state="done",
            progress=100,
            message="動画生成が完了しました",
            output_path=output_path,
            project_output_path=project_output_path,
        )
    except Exception as e:
        update_job_status(job_dir, state="error", message=str(e), error=repr(e))
    finally:
        try:
            if final_video is not None:
                final_video.close()
        except Exception:
            pass
        for clip in video_clips:
            try:
                if getattr(clip, "audio", None):
                    clip.audio.close()
            except Exception:
                pass
            try:
                clip.close()
            except Exception:
                pass
        if work_dir and os.path.exists(work_dir):
            for _ in range(3):
                try:
                    shutil.rmtree(work_dir)
                    break
                except Exception:
                    time.sleep(0.5)


def start_video_job(images, scripts, settings):
    os.makedirs(JOBS_DIR, exist_ok=True)
    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    job_dir = os.path.join(JOBS_DIR, job_id)
    update_job_status(job_dir, state="queued", progress=0, message="処理待ち", job_id=job_id)
    images_for_job = [img.copy() for img in images]
    scripts_for_job = list(scripts)
    thread = threading.Thread(
        target=generate_video_job,
        args=(job_id, images_for_job, scripts_for_job, dict(settings)),
        daemon=False,
    )
    thread.start()
    return job_id


@st.cache_resource
def start_mobile_upload_server():
    os.makedirs(MOBILE_UPLOAD_DIR, exist_ok=True)

    class MobileUploadHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _send_html(self, body, status=200):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            app_url = f"http://{get_lan_ip()}:8501"
            self._send_html(f"""<!doctype html>
<html lang="ja">
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PDFアップロード</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; line-height: 1.6; }}
    input, button, a {{ font-size: 18px; }}
    button, a.button {{ display: block; box-sizing: border-box; width: 100%; margin-top: 16px; padding: 14px; text-align: center; background: #1769e0; color: white; border: 0; border-radius: 8px; text-decoration: none; }}
  </style>
</head>
<body>
  <h2>PDFアップロード</h2>
  <form method="post" enctype="multipart/form-data">
    <input name="pdf" type="file" accept="application/pdf,.pdf" required>
    <button type="submit">PDFを送信</button>
  </form>
  <a class="button" href="{app_url}">アプリに戻る</a>
</body>
</html>""")

        def do_POST(self):
            content_type = self.headers.get("Content-Type", "")
            boundary_token = "boundary="
            if boundary_token not in content_type:
                self._send_html("<p>アップロード形式が正しくありません。</p>", 400)
                return

            boundary = ("--" + content_type.split(boundary_token, 1)[1].strip().strip('"')).encode("utf-8")
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            parts = body.split(boundary)
            pdf_data = None
            original_name = "mobile_upload.pdf"

            for part in parts:
                if b'name="pdf"' not in part:
                    continue
                header_end = part.find(b"\r\n\r\n")
                if header_end == -1:
                    continue
                headers = part[:header_end].decode("utf-8", errors="ignore")
                data = part[header_end + 4:].rstrip(b"\r\n-")
                if data:
                    pdf_data = data
                    filename_marker = 'filename="'
                    if filename_marker in headers:
                        original_name = headers.split(filename_marker, 1)[1].split('"', 1)[0] or original_name
                    break

            if not pdf_data:
                self._send_html("<p>PDFを受け取れませんでした。</p>", 400)
                return

            safe_name = os.path.basename(original_name).replace("\\", "_").replace("/", "_")
            if not safe_name.lower().endswith(".pdf"):
                safe_name += ".pdf"
            upload_path = os.path.join(MOBILE_UPLOAD_DIR, f"{int(time.time())}_{safe_name}")
            with open(upload_path, "wb") as f:
                f.write(pdf_data)

            app_url = f"http://{get_lan_ip()}:8501"
            self._send_html(f"""<!doctype html>
<html lang="ja">
<head><meta name="viewport" content="width=device-width, initial-scale=1"><title>送信完了</title></head>
<body style="font-family:sans-serif; margin:24px; line-height:1.7;">
  <h2>PDFを送信しました</h2>
  <p>アプリに戻って「スマホで送ったPDFを読み込む」を押してください。</p>
  <a href="{app_url}" style="display:block; padding:14px; background:#1769e0; color:white; text-align:center; border-radius:8px; text-decoration:none; font-size:18px;">アプリに戻る</a>
</body>
</html>""")

    try:
        server = ThreadingHTTPServer(("0.0.0.0", MOBILE_UPLOAD_PORT), MobileUploadHandler)
    except OSError:
        return None

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def generate_audio_gtts(text: str, audio_path: str, lang: str, speed: float):
    """Create an mp3 file with gTTS."""
    tts = gTTS(text=text, lang=lang, slow=(speed < 1.0))
    tts.save(audio_path)


def list_pyttsx3_voices():
    if pyttsx3 is None:
        return []
    engine = pyttsx3.init()
    voices = []
    for v in engine.getProperty("voices"):
        try:
            lang = ""
            if hasattr(v, "languages") and v.languages:
                lang_val = v.languages[0]
                lang = lang_val.decode(errors="ignore") if isinstance(lang_val, (bytes, bytearray)) else str(lang_val)
            elif hasattr(v, "lang"):
                lang = str(v.lang)
            voices.append({"id": v.id, "name": v.name, "lang": lang.replace("_", "-") if lang else "unknown"})
        except Exception:
            voices.append({"id": v.id, "name": v.name, "lang": "unknown"})
    engine.stop()
    return voices


def generate_audio_pyttsx3(text: str, audio_path: str, voice_id: str | None, rate_factor: float):
    if pyttsx3 is None:
        raise RuntimeError("pyttsx3 is not installed")
    engine = pyttsx3.init()
    if voice_id:
        engine.setProperty("voice", voice_id)
    base_rate = engine.getProperty("rate") or 200
    engine.setProperty("rate", int(base_rate * rate_factor))
    engine.save_to_file(text, audio_path)
    engine.runAndWait()
    engine.stop()


def build_video_clips(slide_paths, audio_dir: str):
    """Combine slide images and audio into moviepy clips.
    Always include slides even if audio is missing.
    """
    clips = []
    for idx, image_path in enumerate(slide_paths):
        audio_path_mp3 = os.path.join(audio_dir, f"audio_{idx+1:03d}.mp3")
        audio_path_wav = os.path.join(audio_dir, f"audio_{idx+1:03d}.wav")

        audio_file = None
        if os.path.exists(audio_path_mp3):
            audio_file = audio_path_mp3
        elif os.path.exists(audio_path_wav):
            audio_file = audio_path_wav

        if not os.path.exists(image_path):
            continue

        audio_clip = None
        if audio_file:
            try:
                audio_clip = AudioFileClip(audio_file)
            except Exception:
                audio_clip = None

        if audio_clip:
            duration = max(0.2, audio_clip.duration)
            clip = ImageClip(image_path).set_duration(duration).set_audio(audio_clip).set_fps(FPS)
        else:
            # No audio (empty script or audio read failure), default duration 5s
            duration = 5.0
            clip = ImageClip(image_path).set_duration(duration).set_fps(FPS)

        clips.append(clip)
    return clips



def parse_text_to_scripts(text: str, num_pages: int | None = None):
    """
    Parse text containing 'スライドN：... 講義用解説：(content)...'
    Returns a dict {slide_index: script_content}
    Uses re.split to robustly separate slide blocks.
    """
    # Normalize text (handle full-width numbers etc)
    text = unicodedata.normalize('NFKC', text)

    # Split text by slide headers like "スライド 1" or "Slide 1"
    # capture group (\d+) keeps the slide number in the result list
    split_pattern = re.compile(r'(?:^|\n)(?:スライド|Slide)\s*(\d+)', re.IGNORECASE)
    parts = split_pattern.split(text)

    extracted = {}
    
    # parts[0] is text before the first slide header (usually empty or irrelevant)
    # The list structure will be: [preamble, slide_num_1, content_1, slide_num_2, content_2, ...]
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            try:
                slide_num_str = parts[i]
                block_content = parts[i+1]
                slide_index = int(slide_num_str) - 1  # 0-indexed
            except (ValueError, IndexError):
                continue

            # Look for explanation marker in this block
            # Matches "講義用解説：" followed by everything until end of block
            expl_match = re.search(r'講義用解説[:：]\s*(.*)', block_content, re.DOTALL)
            
            if expl_match:
                extracted[slide_index] = expl_match.group(1).strip()
            else:
                # Fallback for Slide 1 if no explanation found
                if slide_index == 0:
                    # Prioritize finding an explicit "Title" line
                    title_match = re.search(r'(?:タイトル|Title)[:：]\s*(.*)', block_content)
                    if title_match:
                         extracted[slide_index] = title_match.group(1).strip()
                    else:
                        # Treat the first non-empty line of the block as the title/script
                        # The block starts right after the number, so it might contain "：Title..."
                        # Clean up leading colon/space
                        clean_content = block_content.lstrip(" :：").strip()
                        if clean_content:
                            # Take the first line
                            extracted[slide_index] = clean_content.splitlines()[0].strip()

    if extracted or not num_pages:
        return extracted

    blocks = [
        block.strip()
        for block in re.split(r'\n\s*\n+|(?:^|\n)\s*[-=]{3,}\s*(?:\n|$)', text)
        if block.strip()
    ]
    if len(blocks) >= num_pages:
        return {i: blocks[i] for i in range(num_pages)}

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= num_pages:
        return {i: lines[i] for i in range(num_pages)}

    sentences = re.split(r'(?<=[。！？!?])\s*', text.strip())
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    if sentences:
        buckets = [""] * num_pages
        for idx, sentence in enumerate(sentences):
            bucket_idx = min(num_pages - 1, int(idx * num_pages / max(1, len(sentences))))
            buckets[bucket_idx] = (buckets[bucket_idx] + sentence).strip()
        return {i: value for i, value in enumerate(buckets) if value}

    return {}


def extract_scripts_from_pdf(pdf_path: str, num_pages: int):
    """
    Extract text from PDF and parse '講義用解説' sections for each slide.
    """
    try:
        reader = pypdf.PdfReader(pdf_path)
        full_text = ""
        for page in reader.pages:
            text = page.extract_text() or ""
            full_text += text + "\n"
        
        extracted = parse_text_to_scripts(full_text, num_pages)
                
        # Create a list matching the number of pages (images)
        # If no script found for a page, default to empty string
        scripts_list = [extracted.get(i, "") for i in range(num_pages)]
        return scripts_list, bool(extracted)

    except Exception as e:
        print(f"Error parsing PDF text: {e}")
        return [""] * num_pages, False


# -------------- UI --------------
st.set_page_config(page_title=PAGE_TITLE, page_icon="🎬", layout="wide")
if not require_login():
    st.stop()

st.title(PAGE_TITLE)
st.caption("PDFから動画作成とテキスト読み上げを一つの画面で実行できます。")

with st.sidebar:
    if st.button("ログアウト"):
        st.session_state.authenticated = False
        st.rerun()

    st.header("音声設定")
    engine_choice = st.selectbox(
        "動画用音声エンジン",
        ["gTTS (オンライン)", "pyttsx3 (ローカル)"],
        help="pyttsx3はWindowsのローカル音声を使用します。インストールが必要です。",
    )
    voice_lang = st.selectbox("音声言語 (gTTS)", ["ja", "en"], format_func=lambda x: "日本語" if x == "ja" else "English")
    voice_speed = st.slider("音声速度", 0.7, 1.3, 1.0, 0.1)

    pyttsx3_voice_id = None
    pyttsx3_voice_label = None
    if engine_choice == "pyttsx3 (ローカル)":
        if pyttsx3 is None:
            st.warning("pyttsx3 が未インストールです。`pip install pyttsx3` を実行してください。")
        else:
            available = list_pyttsx3_voices()
            filtered = [v for v in available if v.get("lang", "").lower().startswith(voice_lang)] or available
            if filtered:
                labels = [f"{v['name']} ({v['lang']})" for v in filtered]
                # Prefer Microsoft Sayaka if available to quickly reach Japanese voice
                default_index = 0
                for i, v in enumerate(filtered):
                    if "sayaka" in (v.get("name", "") + v.get("id", "")).lower():
                        default_index = i
                        break
                selected = st.selectbox("動画用の声", labels, index=default_index)
                pyttsx3_voice_id = filtered[labels.index(selected)]["id"]
                pyttsx3_voice_label = selected
            else:
                st.warning("利用できる音声が見つかりません。Windowsの音声合成を確認してください。")


# Tabs
(tab_video, tab_tts) = st.tabs(["PDF→動画生成", "音声読み上げ"])

# ----- Tab: browser TTS -----
with tab_tts:
    st.subheader("ブラウザで読み上げを確認")
    st.write("入力したテキストをWeb Speech APIで即座に読み上げます。インストール不要。")
    components.html(TTS_COMPONENT, height=480, scrolling=False)


# ----- Tab: PDF to video -----
with tab_video:
    st.subheader("PDFから講義動画を作成")
    st.write("PDFの各スライドに原稿を付けてナレーション付き動画を生成します。")

    if "pdf_upload_state" not in st.session_state:
        st.session_state.pdf_upload_state = {
            "fingerprint": None,
            "images": [],
            "extracted_scripts": [],
            "pdf_name": "",
        }

    images = st.session_state.pdf_upload_state["images"]
    extracted_scripts = st.session_state.pdf_upload_state["extracted_scripts"]
    scripts = []
    active_pdf_name = st.session_state.pdf_upload_state.get("pdf_name") or "uploaded.pdf"

    if LOCAL_MOBILE_UPLOAD_ENABLED:
        lan_ip = get_lan_ip()
        mobile_upload_url = f"http://{lan_ip}:{MOBILE_UPLOAD_PORT}"
        st.markdown("### スマホ用アップロード")
        st.write("標準の「Browse files」で止まる場合は、下のURLをスマホで開いてPDFを送信してください。")
        st.code(mobile_upload_url, language="text")

        if st.button("スマホで送ったPDFを読み込む", type="primary", use_container_width=True):
            latest_upload = get_latest_mobile_upload()
            if not latest_upload:
                st.warning("まだスマホからPDFが送られていません。")
            else:
                try:
                    with open(latest_upload, "rb") as f:
                        mobile_pdf_bytes = f.read()
                    with st.spinner("スマホから送ったPDFを読み込んでいます。"):
                        loaded_state, found_any = load_pdf_bytes(mobile_pdf_bytes, os.path.basename(latest_upload))
                    st.session_state.pdf_upload_state = loaded_state
                    st.session_state.pdf_scripts_found = found_any
                    st.rerun()
                except FileNotFoundError:
                    st.error("送信されたPDFが見つかりませんでした。もう一度アップロードしてください。")
                except Exception as e:
                    st.error(f"スマホから送ったPDFの読み込みに失敗しました: {e}")

    st.markdown("### 通常アップロード")
    uploaded_pdf = st.file_uploader("PDFをアップロード", type=["pdf"], key="pdf_upload")

    if uploaded_pdf:
        pdf_bytes = uploaded_pdf.getvalue()
        pdf_fingerprint = f"{uploaded_pdf.name}:{len(pdf_bytes)}"
        active_pdf_name = uploaded_pdf.name

        if st.session_state.pdf_upload_state["fingerprint"] != pdf_fingerprint:
            st.info("PDFを選択しました。下のボタンで読み込みを開始してください。")
            if st.button("PDFを読み込む", type="primary", use_container_width=True):
                try:
                    with st.spinner("PDFを読み込んでいます。スマホでは少し時間がかかることがあります。"):
                        loaded_state, found_any = load_pdf_bytes(pdf_bytes, uploaded_pdf.name)

                    st.session_state.pdf_upload_state = loaded_state
                    if found_any:
                        st.session_state.pdf_scripts_found = True
                    else:
                        st.session_state.pdf_scripts_found = False
                    st.rerun()
                except FileNotFoundError:
                    st.error("Poppler(pdftoppm)が見つかりません。インストールしてPATHを設定してください。")
                except Exception as e:
                    st.error(f"PDFの読み込みに失敗しました: {e}")

    images = st.session_state.pdf_upload_state["images"]
    extracted_scripts = st.session_state.pdf_upload_state["extracted_scripts"]
    active_pdf_name = st.session_state.pdf_upload_state.get("pdf_name") or active_pdf_name

    if images:
        st.success(f"PDFを読み込みました。ページ数: {len(images)}")

        if st.session_state.get("pdf_scripts_found"):
           # We use a session state flag to show the info only once or just show it.
           st.info("💡 PDF内の「講義用解説」テキストを自動抽出しました。")

        st.markdown("### 原稿の一括入力・修正")
        with st.expander("📄 講義解説の全文を貼り付けて反映させる", expanded=False):
            st.caption("以下に全文を貼り付け、「原稿を反映」ボタンを押すと、各スライドの原稿欄に自動で振り分けられます。")
            full_text_input = st.text_area("全文貼り付け", height=200, placeholder="例：\nスライド1：タイトル\n講義用解説：本日は...\n\nスライド2：...\n講義用解説：...")
            
            if st.button("原稿を反映", type="primary"):
                if full_text_input:
                    manual_extracted = parse_text_to_scripts(full_text_input, len(images))
                    count = 0
                    for i in range(len(images)):
                        script_key = f"script_{active_pdf_name}_{i}"
                        val = manual_extracted.get(i, "")
                        if val:
                            st.session_state[script_key] = val
                            count += 1
                    st.success(f"{count} 枚のスライドに原稿を反映しました。")
                    st.rerun()
                else:
                    st.warning("テキストを入力してください。")

        st.markdown("### 各スライドの原稿")
        for i in range(len(images)):
            # Use uploaded file name in key to ensure reset on new file
            script_key = f"script_{active_pdf_name}_{i}"
            
            # Default value logic:
            # 1. If key exists in session_state, Streamlit uses it automatically.
            # 2. If NOT in session_state, use `value` argument.
            #    We want the PDF extracted text to be the initial value.
            default_val = extracted_scripts[i] if i < len(extracted_scripts) else ""
            
            script = st.text_area(
                f"スライド {i+1} の原稿",
                value=default_val,
                height=120,
                key=script_key,
                placeholder=f"スライド {i+1} の読み上げ内容",
            )
            scripts.append(script)

    if images:
        st.markdown("### 動画生成")
        st.caption("生成開始後はPC側で処理が続くため、スマホ画面を閉じても大丈夫です。あとでこのURLを開くと完成動画を確認できます。")

        if st.button("🚀 動画生成を開始する", type="primary", use_container_width=True):
            if engine_choice == "pyttsx3 (ローカル)" and pyttsx3 is None:
                st.error("pyttsx3 が未インストールです。`pip install pyttsx3` を実行してください。")
            else:
                settings = {
                    "engine_choice": engine_choice,
                    "voice_lang": voice_lang,
                    "voice_speed": voice_speed,
                    "pyttsx3_voice_id": pyttsx3_voice_id,
                }
                job_id = start_video_job(images, scripts, settings)
                st.session_state.current_job_id = job_id
                st.success("動画生成を開始しました。スマホを閉じても処理は続きます。")
                st.rerun()

    st.markdown("### 生成状況")
    current_job_id = st.session_state.get("current_job_id")
    if current_job_id:
        current_job_dir = os.path.join(JOBS_DIR, current_job_id)
        current_status = read_job_status(current_job_dir)
        if current_status:
            st.write(f"現在のジョブ: `{current_job_id}`")
            st.progress(int(current_status.get("progress", 0)))
            st.info(current_status.get("message", "処理中"))
            if current_status.get("state") == "done" and os.path.exists(current_status.get("output_path", "")):
                with open(current_status["output_path"], "rb") as f:
                    st.download_button(
                        label="📥 完成動画をダウンロード",
                        data=f,
                        file_name="lecture_video.mp4",
                        mime="video/mp4",
                        use_container_width=True,
                    )
                st.video(current_status["output_path"])
            elif current_status.get("state") == "error":
                st.error(current_status.get("message", "動画生成に失敗しました。"))
            else:
                if st.button("状況を更新", use_container_width=True):
                    st.rerun()

    recent_jobs = list_recent_jobs()
    if recent_jobs:
        with st.expander("最近の生成結果", expanded=False):
            for job_dir in recent_jobs:
                status = read_job_status(job_dir)
                job_id = status.get("job_id") or os.path.basename(job_dir)
                state = status.get("state", "unknown")
                message = status.get("message", "")
                st.write(f"`{job_id}`: {state} - {message}")
                output_path = status.get("output_path", "")
                if state == "done" and os.path.exists(output_path):
                    with open(output_path, "rb") as f:
                        st.download_button(
                            label=f"📥 {job_id} をダウンロード",
                            data=f,
                            file_name=f"{job_id}.mp4",
                            mime="video/mp4",
                            key=f"download_{job_id}",
                            use_container_width=True,
                        )

st.markdown("---")
st.markdown(
    """
### 使い方
1. 左の「音声設定」で言語・速度・エンジン・声を選択
2. 「音声読み上げ」タブでブラウザ読み上げを試す（確認用）
3. 「PDF→動画生成」タブでPDFをアップロードし、各スライドの原稿を入力
4. 「🚀 動画を生成する」をクリックして動画を出力
"""
)

if __name__ == "__main__":
    print("Streamlit app is ready: streamlit run app.py")
