# -*- coding: utf-8 -*-
"""
Streamlit app that combines:
- Browser-based text-to-speech preview (Web Speech API)
- PDF -> narrated video generator with selectable voices (gTTS or local pyttsx3)
"""
import os
import shutil
import tempfile

import streamlit as st
import streamlit.components.v1 as components
from gtts import gTTS
from pdf2image import convert_from_path
from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips

try:
    import pyttsx3
except ImportError:  # pyttsx3 is optional
    pyttsx3 = None

PAGE_TITLE = "講義動画＆音声読み上げツール"
DPI = 200
FPS = 24
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"

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


def build_video_clips(scripts, slides_dir: str, audio_dir: str):
    """Combine slide images and audio into moviepy clips."""
    clips = []
    for idx in range(len(scripts)):
        image_path = os.path.join(slides_dir, f"slide_{idx+1:03d}.png")
        audio_path = os.path.join(audio_dir, f"audio_{idx+1:03d}.mp3")
        wav_path = os.path.join(audio_dir, f"audio_{idx+1:03d}.wav")
        audio_file = audio_path if os.path.exists(audio_path) else wav_path
        if not (os.path.exists(image_path) and os.path.exists(audio_file)):
            continue
        audio_clip = AudioFileClip(audio_file)
        duration = max(0.2, audio_clip.duration)
        clip = ImageClip(image_path).set_duration(duration).set_audio(audio_clip)
        clips.append(clip)
    return clips


# -------------- UI --------------
st.set_page_config(page_title=PAGE_TITLE, page_icon="🎬", layout="wide")
st.title(PAGE_TITLE)
st.caption("PDFから動画作成とテキスト読み上げを一つの画面で実行できます。")

with st.sidebar:
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
(tab_tts, tab_video) = st.tabs(["音声読み上げ", "PDF→動画生成"])

# ----- Tab: browser TTS -----
with tab_tts:
    st.subheader("ブラウザで読み上げを確認")
    st.write("入力したテキストをWeb Speech APIで即座に読み上げます。インストール不要。")
    components.html(TTS_COMPONENT, height=480, scrolling=False)


# ----- Tab: PDF to video -----
with tab_video:
    st.subheader("PDFから講義動画を作成")
    st.write("PDFの各スライドに原稿を付けてナレーション付き動画を生成します。")

    uploaded_pdf = st.file_uploader("PDFをアップロード", type=["pdf"], key="pdf_upload")

    images = []
    scripts = []

    if uploaded_pdf:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
            tmp_pdf.write(uploaded_pdf.getbuffer())
            pdf_path = tmp_pdf.name

        try:
            images = convert_from_path(pdf_path, dpi=DPI)
            st.success(f"PDFを読み込みました。ページ数: {len(images)}")

            st.markdown("### 各スライドの原稿")
            for i in range(len(images)):
                script = st.text_area(
                    f"スライド {i+1} の原稿",
                    height=100,
                    key=f"script_{i}",
                    placeholder="このスライドで読み上げる内容を入力",
                )
                scripts.append(script)
        except FileNotFoundError:
            st.error("Poppler(pdftoppm)が見つかりません。インストールしてPATHを設定してください。")
        except Exception as e:
            st.error(f"PDFの読み込みに失敗しました: {e}")
        finally:
            try:
                if os.path.exists(pdf_path):
                    os.unlink(pdf_path)
            except Exception:
                pass

    if images and st.button("🚀 動画を生成する", type="primary", use_container_width=True):
        if engine_choice == "pyttsx3 (ローカル)" and pyttsx3 is None:
            st.error("pyttsx3 が未インストールです。`pip install pyttsx3` を実行してください。")
        elif any(not (s or "").strip() for s in scripts):
            st.error("すべてのスライドに原稿を入力してください。空欄は作成できません。")
        else:
            progress_bar = st.progress(0)
            status = st.empty()
            video_clips = []

            try:
                with tempfile.TemporaryDirectory() as work_dir:
                    slides_dir = os.path.join(work_dir, "slides")
                    audio_dir = os.path.join(work_dir, "audio")
                    os.makedirs(slides_dir, exist_ok=True)
                    os.makedirs(audio_dir, exist_ok=True)

                    status.text("PDFをスライド画像に変換中…")
                    for idx, img in enumerate(images):
                        img_path = os.path.join(slides_dir, f"slide_{idx+1:03d}.png")
                        img.save(img_path, "PNG")
                    progress_bar.progress(20)

                    status.text("音声を生成中…")
                    for idx, script in enumerate(scripts):
                        script_text = (script or "").strip()
                        audio_path_mp3 = os.path.join(audio_dir, f"audio_{idx+1:03d}.mp3")
                        audio_path_wav = os.path.join(audio_dir, f"audio_{idx+1:03d}.wav")
                        if engine_choice == "pyttsx3 (ローカル)" and pyttsx3 is not None:
                            target_path = audio_path_wav
                            generate_audio_pyttsx3(script_text, target_path, pyttsx3_voice_id, voice_speed)
                        else:
                            target_path = audio_path_mp3
                            generate_audio_gtts(script_text, target_path, voice_lang, voice_speed)
                        progress_bar.progress(20 + int((idx + 1) / len(scripts) * 30))

                    status.text("クリップを作成中…")
                    video_clips = build_video_clips(scripts, slides_dir, audio_dir)
                    if not video_clips:
                        raise RuntimeError("生成できるクリップがありません。原稿が空か、音声生成に失敗しました。")
                    progress_bar.progress(70)

                    status.text("動画を書き出し中…")
                    final_video = concatenate_videoclips(video_clips, method="compose")

                    temp_output_path = os.path.join(work_dir, "lecture_video.mp4")
                    project_output_path = os.path.join(os.getcwd(), "lecture_video.mp4")

                    final_video.write_videofile(
                        temp_output_path,
                        fps=FPS,
                        codec=VIDEO_CODEC,
                        audio_codec=AUDIO_CODEC,
                        verbose=False,
                        logger=None,
                    )

                    shutil.copy2(temp_output_path, project_output_path)

                    progress_bar.progress(100)
                    status.text("動画生成が完了しました")
                    st.success("🎉 動画を生成しました")
                    st.info(f"保存場所: {project_output_path}")

                    with open(temp_output_path, "rb") as f:
                        st.download_button(
                            label="📥 動画をダウンロード",
                            data=f,
                            file_name="lecture_video.mp4",
                            mime="video/mp4",
                            use_container_width=True,
                        )

                    st.video(temp_output_path)

                    final_video.close()
                    for clip in video_clips:
                        clip.close()

            except FileNotFoundError:
                st.error("FFmpegが見つかりません。インストールしてPATHを設定してください。")
                st.code("where ffmpeg", language="powershell")
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
                st.exception(e)
            finally:
                try:
                    for clip in video_clips:
                        clip.close()
                except Exception:
                    pass

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
