from flask import Flask, render_template, request, jsonify
from pydub import AudioSegment
import requests, websocket, json, base64, google.generativeai as genai, threading

app = Flask(__name__)
API_KEY = "902943809fad7b18f22f221d4abe7abbd7b1235a"
GENAI_KEY = "AIzaSyA5Nw_GAKZbnY0pndNNgxThs_TRk_4MXRQ"

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
        data = json.loads(message)
        if "pipe" in data and data["pipe"].get("asr_final"):
            result["text"] = data["pipe"]["asr_sentence"]
            done_event.set()
            ws.close()

    def on_open(ws):
        ws.send(raw_audio, opcode=websocket.ABNF.OPCODE_BINARY)

    def on_error(ws, error):
        print("WebSocket 錯誤：", error)
        done_event.set()

    ws_app = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=lambda *args: print("WebSocket 已關閉")
    )

    thread = threading.Thread(target=ws_app.run_forever, daemon=True)
    thread.start()
    if not done_event.wait(timeout=10):
        print("語音辨識逾時")
        return None
    return result.get("text")

def call_gemini(text):
    genai.configure(api_key=GENAI_KEY)
    try:
        model = genai.GenerativeModel("gemini-2.0-flash-lite")
        prompt = f"請用簡單且聊天自然、溫柔的方式回答:{text}"
        response = model.generate_content(prompt)
        return response.text if hasattr(response, "text") else "無回應"
    except Exception as e:
        print("Gemini 錯誤:", e)
        return "呼叫失敗"

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

@app.route('/topics')
def topics():
    return render_template('topics.html')

@app.route('/chat')
def chat():
    topic = request.args.get("topic", "")
    prompt = f"開啟一段關於{topic}的聊天，回答簡短一些" if topic else ""
    gemini_reply = ""
    audio_base64 = ""

    if prompt:
        print("[Prompt]", prompt)
        gemini_reply = call_gemini(prompt)
        if gemini_reply:
            audio = synthesize_taiwanese(gemini_reply)
            if audio:
                audio_base64 = f"data:audio/wav;base64,{audio}"
            else:
                print("TTS 失敗")
        else:
            print("Gemini 回應失敗")

    # ✅ 不論怎樣一定要 return
    return render_template(
        "chat.html",
        topic=topic,
        gemini_reply=gemini_reply,
        audio_base64=audio_base64
    )

@app.route('/start-record', methods=['POST'])
def start_record():
    return jsonify({"status": "ok"})

@app.route('/upload', methods=['POST'])
def upload_audio():
    file = request.files.get('audio')
    if not file:
        return jsonify({'error': '未收到音檔'}), 400

    try:
        audio = AudioSegment.from_file(file, format="webm").set_channels(1).set_frame_rate(16000).set_sample_width(2)
        raw_pcm = audio.raw_data
    except Exception as e:
        print("音訊處理錯誤:", e)
        return jsonify({'error': '音訊處理失敗'}), 500

    token = get_token()
    if not token:
        return jsonify({'error': '語音辨識Token獲取失敗'}), 500

    recognized_text = recognize_audio_ws(raw_pcm, token)
    if not recognized_text:
        return jsonify({'error': '語音辨識失敗'}), 500

    # 呼叫 Gemini 回應
    gemini_reply = call_gemini(recognized_text)

    # ✅ 若內容含負面情緒，再在 Gemini 回應後附加建議句子
    negative_keywords = ["心情不好", "心情很差","壓力", "焦慮", "煩", "難過", "悲傷", "情緒", "痛苦", "沮喪", "煩躁", "想哭"]
    suggestion = "或許你可以試試我們的心理健康評估功能，點擊首頁愛心按鈕一起來評估看看吧~"
    if any(word in recognized_text for word in negative_keywords):
        gemini_reply += f"\n\n{suggestion}"

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
