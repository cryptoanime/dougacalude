# -*- coding: utf-8 -*-
import os
import socket
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MOBILE_UPLOAD_PORT = 8502
MOBILE_UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "lecture_mobile_uploads")


def get_lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


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
        os.makedirs(MOBILE_UPLOAD_DIR, exist_ok=True)
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


if __name__ == "__main__":
    os.makedirs(MOBILE_UPLOAD_DIR, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", MOBILE_UPLOAD_PORT), MobileUploadHandler)
    print(f"Mobile PDF upload server: http://{get_lan_ip()}:{MOBILE_UPLOAD_PORT}")
    server.serve_forever()
