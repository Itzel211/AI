from flask import Flask, render_template, request, jsonify
from pydub import AudioSegment
from io import BytesIO
import requests
import websocket
import json
import base64
import google.generativeai as genai
import threading
import time

app = Flask(__name__)
API_KEY = "902943809fad7b18f22f221d4abe7abbd7b1235a"
GENAI_KEY = "AIzaSyDNXmYgU7598r_3zgw23FhRsQJyX8nK1aI"

def get_token():
    url = "https://asr.api.yating.tw/v1/token"
    headers = {"key": API_KEY, "Content-Type": "application/json"}
    data = {"pipeline": "asr-zh-tw-std"}
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        return response.json().get("auth_token")
    print("Token獲取失敗:", response.text)
    return None

def recognize_audio_ws(raw_audio, token):
    WS_URL = f"wss://asr.api.yating.tw/ws/v1/?token={token}"
    result = {}
    done_event = threading.Event()

    def on_message(ws, message):
        print("💬 收到 Yating 回應：", message)
        data = json.loads(message)
        if "pipe" in data:
            if data["pipe"].get("asr_final"):
                result["text"] = data["pipe"]["asr_sentence"]
                done_event.set()
                ws.close()

    def on_open(ws):
        print("🔗 WebSocket 已連線，開始送音訊")
        ws.send(raw_audio, opcode=websocket.ABNF.OPCODE_BINARY)

    def on_error(ws, error):
        print("❌ WebSocket 錯誤：", error)
        done_event.set()

    ws_app = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=lambda *args: print("🔚 WebSocket 已關閉")
    )

    thread = threading.Thread(target=ws_app.run_forever, daemon=True)
    thread.start()

    # 最多等 10 秒
    if not done_event.wait(timeout=10):
        print("⚠️ 語音辨識逾時")
        return None

    return result.get("text")


def call_gemini(text):
    genai.configure(api_key=GENAI_KEY)
    try:
        model = genai.GenerativeModel("gemini-1.5-pro")
        response = model.generate_content(text)
        return response.text if hasattr(response, "text") else "❌ 無回應"
    except Exception as e:
        print("Gemini 錯誤:", e)
        return "❌ 呼叫失敗"

def synthesize_taiwanese(text):
    TTS_URL = "https://tts.api.yating.tw/v2/speeches/short"
    headers = {"key": API_KEY, "Content-Type": "application/json"}
    payload = {
        "input": {"text": text, "type": "text"},
        "voice": {"model": "tai_female_1", "speed": 0.8, "pitch": 1.3, "energy": 1.0},
        "audioConfig": {"encoding": "LINEAR16", "sampleRate": "22K"}
    }
    res = requests.post(TTS_URL, json=payload, headers=headers)
    if res.status_code == 201:
        return res.json().get("audioContent")
    print("TTS 失敗:", res.status_code, res.text)
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start-record', methods=['POST'])
def start_record():
    print("✅ 收到 /start-record")
    return jsonify({"status": "ok"})

@app.route('/upload', methods=['POST'])
def upload_audio():
    print("🎤 收到音訊")
    file = request.files.get('audio')
    if not file:
        return jsonify({'error': '未收到音檔'}), 400

    try:
        audio = AudioSegment.from_file(file, format="webm")
        audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        raw_pcm = audio.raw_data
        print("🔊 傳送音訊長度：", len(raw_pcm))

    except Exception as e:
        print("音訊處理錯誤:", e)
        return jsonify({'error': '音訊處理失敗'}), 500

    token = get_token()
    if not token:
        return jsonify({'error': '語音辨識Token獲取失敗'}), 500

    recognized_text = recognize_audio_ws(raw_pcm, token)
    if not recognized_text:
        return jsonify({'error': '語音辨識失敗'}), 500

    gemini_reply = call_gemini(recognized_text)
    audio_base64 = synthesize_taiwanese(gemini_reply)
    if not audio_base64:
        return jsonify({'error': 'TTS 失敗'}), 500

    return jsonify({
        "recognized_text": recognized_text,
        "gemini_reply": gemini_reply,
        "audio_base64": f"data:audio/wav;base64,{audio_base64}"
    })

if __name__ == '__main__':
    app.run(debug=True)
