# -*- coding: utf-8 -*-
import os
import shutil
import tempfile

import streamlit as st
from gtts import gTTS
from pdf2image import convert_from_path
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# ---------------- Constants ----------------
DPI = 200
FPS = 24
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"

# ---------------- Helpers ----------------
def convert_pdf_to_images(pdf_path: str, dpi: int = DPI):
    """PDF -> PIL.Image のリスト"""
    return convert_from_path(pdf_path, dpi=dpi)

def save_slide_images(images, slides_dir: str):
    """画像を連番PNGで保存"""
    os.makedirs(slides_dir, exist_ok=True)
    paths = []
    for idx, image in enumerate(images):
        image_path = os.path.join(slides_dir, f"slide_{idx+1:03d}.png")
        image.save(image_path, "PNG")
        paths.append(image_path)
    return paths

def generate_tts_files(scripts, audio_dir: str, lang: str, speed: float):
    """テキスト -> MP3。gTTSは normal/slow だけなので speed<1.0 を slow に割当て"""
    os.makedirs(audio_dir, exist_ok=True)
    paths = []
    for idx, script in enumerate(scripts):
        text = (script or "").strip()
        if not text:
            # 空行はスキップ（該当スライドは無音・スキップ）
            paths.append(None)
            continue
        audio_path = os.path.join(audio_dir, f"audio_{idx+1:03d}.mp3")
        tts = gTTS(text=text, lang=lang, slow=(speed < 1.0))
        tts.save(audio_path)
        paths.append(audio_path)
    return paths

def build_video_clips(scripts, slides_dir: str, audio_dir: str):
    """各スライド画像と音声からクリップをつくる（音声や画像が無いスライドは飛ばす）"""
    clips = []
    for idx in range(len(scripts)):
        image_path = os.path.join(slides_dir, f"slide_{idx+1:03d}.png")
        audio_path = os.path.join(audio_dir, f"audio_{idx+1:03d}.mp3")
        if not (os.path.exists(image_path) and os.path.exists(audio_path)):
            continue
        audio_clip = AudioFileClip(audio_path)
        duration = max(0.2, audio_clip.duration)  # 万一の極短回避
        image_clip = ImageClip(image_path).set_duration(duration)
        clips.append(image_clip.set_audio(audio_clip))
    return clips

def safe_unlink(path: str | None):
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass

# -------------------- UI --------------------
st.set_page_config(page_title="講義動画自動生成システム", page_icon="🎬", layout="wide")

st.title("🎥 講義動画自動生成システム")
st.markdown("---")

with st.sidebar:
    st.header("⚙ 設定")
    voice_lang = st.selectbox("音声言語", ["ja", "en"], format_func=lambda x: "日本語" if x == "ja" else "English")
    voice_speed = st.slider("音声速度", 0.5, 2.0, 1.0, 0.1)

col1, col2 = st.columns([1, 1])

with col1:
    st.header("📄 Step 1: PDFアップロード")
    uploaded_pdf = st.file_uploader("講義スライドPDFをアップロード", type=["pdf"])

with col2:
    st.header("📝 Step 2: 原稿入力")
    scripts_text = st.text_area("ナレーション原稿（1行＝1スライド）", height=200, placeholder="各スライドで読み上げる内容を1行ずつ記入")
    scripts = [s for s in scripts_text.splitlines() if s.strip()]
    num_pages = 0

# 事前変換（PDFを一度だけ読む）
all_images = None
pdf_path = None
if uploaded_pdf:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_pdf.read())
        pdf_path = tmp_file.name
    try:
        all_images = convert_pdf_to_images(pdf_path, dpi=DPI)
        num_pages = len(all_images)
        st.success(f"✅ PDFを読み込みました（{num_pages} ページ）")
        st.session_state["_pdf_path"] = pdf_path
        st.session_state["_pages"] = num_pages
    except Exception as e:
        st.error(f"⚠️ PDFの読み込みに失敗しました：{e}")

st.markdown("---")
st.header("🎬 Step 3: 動画生成")

clicked = st.button("🚀 動画を生成する", type="primary", use_container_width=True)
if uploaded_pdf and clicked:
    if not scripts:
        st.error("⚠️ スライド原稿を入力してください（空の行は無視されます）。")
    else:
        try:
            with tempfile.TemporaryDirectory() as work_dir:
                slides_dir = os.path.join(work_dir, "slides")
                audio_dir = os.path.join(work_dir, "audio")

                progress_bar = st.progress(0)
                status_text = st.empty()

                # 1) PDF -> images
                status_text.text("📄 PDFをスライド画像に変換中…")
                images_for_save = all_images or convert_pdf_to_images(st.session_state.get("_pdf_path"), dpi=DPI)
                save_slide_images(images_for_save, slides_dir)
                progress_bar.progress(30)

                # 2) TTS
                status_text.text("🎙 音声ファイルを生成中…")
                generate_tts_files(scripts, audio_dir, voice_lang, voice_speed)
                progress_bar.progress(70)

                # 3) クリップ作成
                status_text.text("🎬 クリップを作成中…")
                video_clips = build_video_clips(scripts, slides_dir, audio_dir)
                if not video_clips:
                    raise RuntimeError("生成できるクリップがありません（原稿が空か、TTS生成に失敗した可能性があります）。")
                progress_bar.progress(90)

                # 4) 結合・書き出し
                status_text.text("🔗 動画を結合中…")
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

                # プロジェクト直下にも保存
                shutil.copy2(temp_output_path, project_output_path)

                progress_bar.progress(100)
                status_text.text("✅ 動画生成が完了しました")
                st.success("🎉 動画を生成しました！")
                st.info(f"📁 保存場所: {project_output_path}")

                # ダウンロード＆プレビュー
                with open(temp_output_path, "rb") as f:
                    st.download_button(
                        label="📥 動画をダウンロード",
                        data=f,
                        file_name="lecture_video.mp4",
                        mime="video/mp4",
                        use_container_width=True,
                    )
                st.video(temp_output_path)

                # 後片付け
                final_video.close()
                for c in video_clips:
                    c.close()

        except FileNotFoundError:
            st.error("Poppler（pdf2image用）または FFmpeg（moviepy用）が見つかりません。インストールして PATH に追加してください。")
            st.code("where pdftoppm\nwhere ffmpeg", language="powershell")
        except Exception as e:
            st.error(f"エラーが発生しました：{e}")
            st.exception(e)
        finally:
            safe_unlink(st.session_state.get("_pdf_path"))

st.markdown("---")
st.markdown(
    """
### 💡 使い方
1. PDFファイルをアップロード  
2. 各スライドの原稿を1行ずつ入力（空行は無視）  
3. 「🚀 動画を生成する」をクリック  
4. 完成後に「📥 動画をダウンロード」から保存
"""
)

