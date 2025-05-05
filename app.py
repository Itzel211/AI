from flask import Flask, render_template, request, jsonify
from pydub import AudioSegment
from io import BytesIO
import requests
import websocket
import json
import base64
import google.generativeai as genai
import threading

app = Flask(__name__)

# 語音辨識Token
API_KEY = "902943809fad7b18f22f221d4abe7abbd7b1235a"

def get_token():
    url = "https://asr.api.yating.tw/v1/token"
    headers = {"key": API_KEY, "Content-Type": "application/json"}
    data = {"pipeline": "asr-zh-tw-std"}
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        return response.json().get("auth_token")
    else:
        print("Token獲取失敗:", response.json())
        return None

def recognize_audio_ws(raw_audio, token):
    WS_URL = f"wss://asr.api.yating.tw/ws/v1/?token={token}"
    result = {}

    def on_message(ws, message):
        data = json.loads(message)
        if "pipe" in data and "asr_final" in data["pipe"] and data["pipe"]["asr_final"]:
            result['text'] = data["pipe"]["asr_sentence"]
            ws.close()

    ws = websocket.WebSocketApp(WS_URL, on_message=on_message)
    thread = threading.Thread(target=ws.run_forever)
    thread.start()
    import time
    time.sleep(1)  # 等待連線穩定
    ws.send(raw_audio, opcode=websocket.ABNF.OPCODE_BINARY)

    timeout = 10
    start = time.time()
    while 'text' not in result and time.time() - start < timeout:
        time.sleep(0.1)

    return result.get('text')

def call_gemini(text):
    genai.configure(api_key="AIzaSyDNXmYgU7598r_3zgw23FhRsQJyX8nK1aI")
    try:
        model = genai.GenerativeModel("gemini-1.5-pro")
        response = model.generate_content(text)
        return response.text if hasattr(response, 'text') else "❌ 無回應"
    except Exception as e:
        print("Gemini錯誤:", e)
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
    else:
        print("TTS失敗:", res.status_code, res.text)
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_audio():
    file = request.files.get('audio')
    if not file:
        return jsonify({'error': '未收到音檔'}), 400

    # 音訊轉16kHz / 16bit / mono
    audio = AudioSegment.from_file(file, format="webm")
    audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
    pcm_wav = BytesIO()
    audio.export(pcm_wav, format="wav")
    pcm_wav.seek(0)
    raw_pcm = pcm_wav.read()[44:]  # 去掉WAV header

    token = get_token()
    if not token:
        return jsonify({'error': '語音辨識Token獲取失敗'}), 500

    recognized_text = recognize_audio_ws(raw_pcm, token)
    if not recognized_text:
        return jsonify({'error': '語音辨識失敗'}), 500

    gemini_reply = call_gemini(recognized_text)
    audio_base64 = synthesize_taiwanese(gemini_reply)

    return jsonify({
        "recognized_text": recognized_text,
        "gemini_reply": gemini_reply,
        "audio_base64": audio_base64
    })

if __name__ == '__main__':
    app.run(debug=True)
