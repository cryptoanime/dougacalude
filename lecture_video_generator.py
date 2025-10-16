import streamlit as st
from gtts import gTTS
from pdf2image import convert_from_path
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
import os
import tempfile
import shutil

st.set_page_config(page_title="講義動画自動生成システム", page_icon="🎬", layout="wide")

st.title("🎬 講義動画自動生成システム")
st.markdown("---")

with st.sidebar:
    st.header("⚙️ 設定")
    voice_lang = st.selectbox("音声言語", ["ja", "en"], format_func=lambda x: "日本語" if x == "ja" else "英語")
    voice_speed = st.slider("音声速度", 0.5, 2.0, 1.0, 0.1)

col1, col2 = st.columns([1, 1])

with col1:
    st.header("📁 Step 1: PDFアップロード")
    uploaded_pdf = st.file_uploader("講義スライドのPDFをアップロード", type=['pdf'])

with col2:
    st.header("📝 Step 2: 原稿入力")
    scripts = []
    num_pages = 0

    if uploaded_pdf:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            tmp_file.write(uploaded_pdf.read())
            pdf_path = tmp_file.name

        try:
            all_images = convert_from_path(pdf_path, dpi=150)
            num_pages = len(all_images)
            st.success(f"✅ PDF読み込み完了！（{num_pages}ページ）")

            st.markdown("### 各スライドの読み上げ原稿を入力")
            for i in range(num_pages):
                script = st.text_area(f"スライド {i+1} の原稿", height=100, key=f"script_{i}", placeholder="このスライドで読み上げる内容を入力...")
                scripts.append(script)
        except Exception as e:
            st.error(f"❌ PDFの読み込みに失敗: {str(e)}")

st.markdown("---")
st.header("🎬 Step 3: 動画生成")

if uploaded_pdf and st.button("🚀 動画を生成する", type="primary", use_container_width=True):
    if not all(scripts):
        st.error("❌ すべてのスライドの原稿を入力してください")
    else:
        try:
            work_dir = tempfile.mkdtemp()
            slides_dir = os.path.join(work_dir, "slides")
            audio_dir = os.path.join(work_dir, "audio")
            os.makedirs(slides_dir, exist_ok=True)
            os.makedirs(audio_dir, exist_ok=True)

            progress_bar = st.progress(0)
            status_text = st.empty()

            status_text.text("📄 PDFをスライド画像に変換中...")
            images = convert_from_path(pdf_path, dpi=200)
            for idx, image in enumerate(images):
                image_path = os.path.join(slides_dir, f"slide_{idx+1:03d}.png")
                image.save(image_path, 'PNG')
            progress_bar.progress(20)

            status_text.text("🎙️ 音声ファイルを生成中...")
            for idx, script in enumerate(scripts):
                if script.strip():
                    audio_path = os.path.join(audio_dir, f"audio_{idx+1:03d}.mp3")
                    tts = gTTS(text=script, lang=voice_lang, slow=(voice_speed < 1.0))
                    tts.save(audio_path)
                progress_bar.progress(20 + int((idx + 1) / len(scripts) * 30))

            status_text.text("🎬 動画を生成中...")
            video_clips = []
            for idx in range(len(scripts)):
                image_path = os.path.join(slides_dir, f"slide_{idx+1:03d}.png")
                audio_path = os.path.join(audio_dir, f"audio_{idx+1:03d}.mp3")

                if os.path.exists(audio_path):
                    audio_clip = AudioFileClip(audio_path)
                    duration = audio_clip.duration
                    image_clip = ImageClip(image_path, duration=duration)
                    video_clip = image_clip.set_audio(audio_clip)
                    video_clips.append(video_clip)

                progress_bar.progress(50 + int((idx + 1) / len(scripts) * 40))

            status_text.text("🔗 動画を結合中...")
            final_video = concatenate_videoclips(video_clips, method="compose")
            output_path = os.path.join(work_dir, "lecture_video.mp4")

            final_video.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac', verbose=False, logger=None)

            progress_bar.progress(100)
            status_text.text("✅ 動画生成完了！")

            st.success("🎉 動画が完成しました！")
            with open(output_path, 'rb') as video_file:
                st.download_button(label="📥 動画をダウンロード", data=video_file, file_name="lecture_video.mp4", mime="video/mp4", use_container_width=True)

            st.video(output_path)

            final_video.close()
            for clip in video_clips:
                clip.close()

        except Exception as e:
            st.error(f"❌ エラーが発生しました: {str(e)}")
            st.exception(e)
        finally:
            try:
                if 'pdf_path' in locals() and os.path.exists(pdf_path):
                    os.unlink(pdf_path)
                if 'work_dir' in locals() and os.path.exists(work_dir):
                    shutil.rmtree(work_dir)
            except:
                pass

st.markdown("---")
st.markdown("""
### 💡 使い方
1. PDFファイルをアップロード
2. 各スライドの読み上げ原稿を入力
3. 動画を生成ボタンをクリック
4. 完成した動画をダウンロード
""")
