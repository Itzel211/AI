import websocket
import pyaudio
import wave
import json
import requests
import google.generativeai as genai
import threading
import time
import base64

#-----------------------------------------------------
API_KEY = "902943809fad7b18f22f221d4abe7abbd7b1235a"
# Token API URL
TOKEN_URL = "https://asr.api.yating.tw/v1/token"

# 設定請求標頭
headers = {
    "key": API_KEY,
    "Content-Type": "application/json"
}

# 設定請求參數
data = {
    "pipeline": "asr-zh-tw-std"  # 選擇適合的語言模型
}

# 發送請求
response = requests.post(TOKEN_URL, headers=headers, json=data)

# 檢查回應
if response.status_code == 201:
    token = response.json().get("auth_token")
    print("取得 Token 成功:", token)
else:
    print("❌ 取得 Token 失敗:", response.json())
    exit(1)  # 如果無法取得 Token，退出程式

# WebSocket 伺服器網址
WS_URL = f"wss://asr.api.yating.tw/ws/v1/?token={token}"
#-----------------------------------------------------
# 設定音訊格式
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 2000

# 初始化 PyAudio
audio = pyaudio.PyAudio()
stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

# 這個標誌用來控制錄音停止
recording = True

#播放語音
def play_audio(file_path):

    chunk = 1024
    wf = wave.open(file_path, 'rb')
    pa = pyaudio.PyAudio()

    stream = pa.open(format=pa.get_format_from_width(wf.getsampwidth()),
                     channels=wf.getnchannels(),
                     rate=wf.getframerate(),
                     output=True)

    data = wf.readframes(chunk)
    while data:
        stream.write(data)
        data = wf.readframes(chunk)

    stream.stop_stream()
    stream.close()
    pa.terminate()
    wf.close()
#-----------------------------------------------------
# 設定 Google Gemini API Key
genai.configure(api_key="AIzaSyDNXmYgU7598r_3zgw23FhRsQJyX8nK1aI")

#回覆
def call_gemini(text):
    try:
        model = genai.GenerativeModel("gemini-1.5-pro")
        prompt = f"請用簡單且聊天自然、溫柔的方式回答:{text}"
        response = model.generate_content(text)
        return response.text if response and hasattr(response, 'text') else "❌ 無回應"
    except Exception as e:
        print(f"Gemini API 呼叫錯誤: {e}")
        return "❌ 呼叫 Gemini 失敗"
#-----------------------------------------------------
def on_message(ws, message):
    try:
        response = json.loads(message)

        if "pipe" in response and "asr_final" in response["pipe"] and response["pipe"]["asr_final"]:
            recognized_text = response["pipe"]["asr_sentence"]
            print(f"📝 最終辨識結果: {recognized_text}")

            # 傳送辨識結果給 Gemini 2.0
            gemini_response = call_gemini(recognized_text)
            print(f"🤖 Gemini 2.0 回應: {gemini_response}")

            # 停止錄音
            global recording
            recording = False
            ws.close()  # 關閉 WebSocket

            # 語音合成 API 設定
            TTS_API_URL = "https://tts.api.yating.tw/v2/speeches/short"
            TTS_API_KEY = "902943809fad7b18f22f221d4abe7abbd7b1235a"  # 請替換為你的金鑰

            # 組成 payload
            payload = {
                "input": {
                    "text": gemini_response,
                    "type": "text"
                },
                "voice": {
                    "model": "tai_female_1",
                    "speed": 0.8,
                    "pitch": 1.3,
                    "energy": 1.0
                },
                "audioConfig": {
                    "encoding": "LINEAR16",
                    "sampleRate": "22K"
                }
            }

            headers = {
                "key": TTS_API_KEY,
                "Content-Type": "application/json"
            }

            # 發送 TTS 請求
            tts_response = requests.post(TTS_API_URL, json=payload, headers=headers)

            if tts_response.status_code == 201:
                audio_base64 = tts_response.json().get("audioContent")
                audio_data = base64.b64decode(audio_base64)

                with open("output_audio.wav", "wb") as f:
                    f.write(audio_data)

                print("🎧 已儲存音檔，播放中...")

                play_audio("output_audio.wav")
            else:
                print(f"❌ TTS 回應錯誤: {tts_response.status_code}")
                print(tts_response.text)

    except Exception as e:
        print("錯誤:", e)

def on_error(ws, error):
    print("WebSocket 錯誤:", error)

def on_close(ws, close_status_code, close_msg):
    print("WebSocket 關閉")
    if stream.is_active():
        stream.stop_stream()
    stream.close()
    audio.terminate()

def on_open(ws):
    print("✅ WebSocket 連線成功！")

    # 開始錄音並傳送音訊數據
    def record_audio():
        global recording
        start_time = time.time()
        frames = []
        try:
            while recording and time.time() - start_time <10 :  # 只錄音 10 秒
                data = stream.read(CHUNK, exception_on_overflow=False)
                if len(data) > 2:
                    frames.append(data)
            print("🔴 停止錄音")
        except Exception as e:
            print("錄音錯誤:", e)

        finally:
            # 這裡可以處理錄音結束後的資料
            if frames:
                print(f"錄音結束，錄製了 {len(frames)} 幀")
                # 如果需要，將錄音資料發送到 WebSocket
                for frame in frames:
                    ws.send(frame, opcode=websocket.ABNF.OPCODE_BINARY)
            else:
                print("沒有音訊資料")
            recording = False  # 停止錄音

    # 在背景線程中啟動錄音
    threading.Thread(target=record_audio).start()

# 建立 WebSocket 連線
ws = websocket.WebSocketApp(WS_URL, on_message=on_message, on_error=on_error, on_close=on_close, on_open=on_open)

# 開始 WebSocket 連線
ws.run_forever()


