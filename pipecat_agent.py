import os
import json
import base64
import ssl
import certifi
import aiohttp
import asyncio

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"
TTS_URL = "https://api.sarvam.ai/text-to-speech"
CHAT_MODEL = "sarvam-105b-conversations"
TTS_MODEL = "bulbul:v3"

SYSTEM_PROMPT = """आप प्रिया हैं, एक विनम्र, पेशेवर और अनुभवी भारतीय बीमा परामर्शदाता (Insurance Advisor) जो InsureCRM की ओर से बात कर रही हैं।
आप अपने ग्राहकों से उनकी बीमा पॉलिसियों के नवीनीकरण (Policy Renewal), नो-क्लेम बोनस (NCB), प्रीमियम डिस्काउंट और क्लेम सहायता के बारे में स्वाभाविक और आदरपूर्ण हिंदी में बात करती हैं।

नियम:
1. हमेशा स्पष्ट, विनम्र और स्वाभाविक हिंदी बोलें (जैसे: 'नमस्ते सर/मैडम, मैं InsureCRM से प्रिया बोल रही हूँ...')।
2. छोटे, केंद्रित और बातचीत वाले वाक्यों का उपयोग करें (2-3 वाक्य अधिकतम प्रति उत्तर ताकि बातचीत जीवंत लगे)।
3. यदि ग्राहक नवीनीकरण (renewal) के लिए सहमत हो, तो खुशी व्यक्त करें और कहें कि भुगतान लिंक (payment link) तुरंत उनके व्हाट्सएप और ईमेल पर भेज दिया गया है।
4. यदि ग्राहक व्यस्त हो, तो पुनः कॉल करने का सुविधाजनक समय पूछें।
5. यदि ग्राहक पॉलिसी रद्द या असंतुष्ट हो, तो कारण समझें और अतिरिक्त छूट या बेहतर कवर का प्रस्ताव दें।
"""

class SarvamVoiceAgent:
    def __init__(self):
        self.api_key = SARVAM_API_KEY
        self.headers = {
            "Content-Type": "application/json",
            "api-subscription-key": self.api_key
        }
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    async def stream_response(self, messages):
        if not self.api_key:
            yield {"type": "error", "content": "Sarvam AI is not configured"}
            return
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
        
        payload = {
            "model": CHAT_MODEL,
            "messages": messages,
            "stream": True,
            "temperature": 0.3,
            "max_tokens": 250
        }

        connector = aiohttp.TCPConnector(ssl=self.ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.post(CHAT_URL, json=payload, headers=self.headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        yield {"type": "error", "content": f"API Error {response.status}: {error_text}"}
                        return

                    async for raw_line in response.content:
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str == "[DONE]":
                                break
                            if not data_str:
                                continue
                            try:
                                data = json.loads(data_str)
                                if "choices" in data and len(data["choices"]) > 0:
                                    delta = data["choices"][0].get("delta", {})
                                    if "content" in delta and delta["content"]:
                                        yield {"type": "chunk", "content": delta["content"]}
                            except json.JSONDecodeError:
                                pass
            except Exception as e:
                yield {"type": "error", "content": str(e)}
        yield {"type": "done"}

    async def synthesize_speech(self, text):
        if not self.api_key:
            return None
        clean_text = text.strip()
        if not clean_text:
            return None

        payload = {
            "inputs": [clean_text],
            "target_language_code": "hi-IN",
            "speaker": "priya",
            "model": TTS_MODEL,
            "pitch": 0,
            "pace": 1.02,
            "loudness": 1.5,
            "speech_sample_rate": 8000,
            "enable_preprocessing": True
        }
        
        connector = aiohttp.TCPConnector(ssl=self.ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.post(TTS_URL, json=payload, headers=self.headers, timeout=aiohttp.ClientTimeout(total=20)) as response:
                    if response.status != 200:
                        err = await response.text()
                        print(f"TTS Error {response.status}: {err}")
                        return None
                    data = await response.json()
                    if "audios" in data and len(data["audios"]) > 0:
                        return data["audios"][0]
            except Exception as e:
                print(f"TTS Exception: {e}")
                return None
        return None

agent = SarvamVoiceAgent()
