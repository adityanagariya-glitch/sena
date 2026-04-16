# Gemini Live API Setup Guide — Complete Step-by-Step

This guide walks through every step to get Gemini Live API running from scratch. No prior Google Cloud experience needed.

---

## Phase 1: Get Your API Key (5 minutes)

### Step 1: Go to Google AI Studio
1. Open browser → go to **https://aistudio.google.com**
2. You'll see Google's free AI development console (no Google Cloud account required yet)

### Step 2: Create API Key
1. Click **"Get API Key"** button (top-left or in menu)
2. Choose: **"Create API Key in new Google Cloud project"**
   - This auto-creates a free Google Cloud project for you
3. A popup appears with your **API_KEY** — copy it and save in safe place (like `.env`)
4. Close popup

**Result:** You now have a 40-character API key. Format looks like:
```
AIza... (40 characters)
```

---

## Phase 2: Verify API Key Works (2 minutes)

### Test with curl (Command Line)

Open terminal and run:

```bash
export GEMINI_API_KEY="YOUR_API_KEY_HERE"

curl "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent" \
  -H "x-goog-api-key: $GEMINI_API_KEY" \
  -H 'Content-Type: application/json' \
  -X POST \
  -d '{
    "contents": [
      {
        "parts": [
          {
            "text": "Say hello in one word"
          }
        ]
      }
    ]
  }'
```

**Expected output:** JSON response with `"text": "Hello"` (or similar greeting)

If you see an error, check:
- API key is copied correctly (no extra spaces)
- You have internet connection
- No typos in curl command

---

## Phase 3: Install Python Dependencies

### Install Google Gemini SDK

```bash
pip install google-generativeai
```

Verify install:
```bash
python3 -c "import google.genai; print('✓ Gemini SDK installed')"
```

---

## Phase 4: Test Gemini Live API in Python

### Create test file: `test_gemini_live.py`

```python
import asyncio
from google import genai
from google.genai import types

async def test_gemini_live():
    """Test Gemini Live API connection"""

    # Initialize client (reads GOOGLE_API_KEY from environment)
    client = genai.Client(api_key="YOUR_API_KEY_HERE")

    # Model with audio support
    model = "gemini-2.5-flash-native-audio-preview-09-2025"

    config = {
        "response_modalities": ["TEXT"],  # Start with text responses
        "system_instruction": "You are a helpful assistant. Keep responses brief.",
    }

    print("Connecting to Gemini Live API...")

    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            print("✓ Connected!")

            # Send a text message
            await session.send_realtime_input(
                content=types.Content(
                    parts=[types.Part.from_text("Hello, what is your name?")]
                )
            )

            # Receive response
            async for response in session.receive():
                if response.text:
                    print(f"Response: {response.text}")
                    break

    except Exception as e:
        print(f"✗ Error: {e}")
        print("Troubleshooting:")
        print("- Check API key is valid (test with curl first)")
        print("- Verify internet connection")
        print("- Ensure model name is correct")

if __name__ == "__main__":
    asyncio.run(test_gemini_live())
```

### Run test:
```bash
export GOOGLE_API_KEY="YOUR_API_KEY"
python3 test_gemini_live.py
```

**Expected output:**
```
Connecting to Gemini Live API...
✓ Connected!
Response: I'm Claude, an AI assistant made by Google. How can I help?
```

---

## Phase 5: Audio Input/Output (Optional — Advanced)

### Dependencies for audio processing

```bash
pip install librosa soundfile numpy
```

### Audio example: `test_gemini_live_audio.py`

```python
import asyncio
import io
from pathlib import Path
from google import genai
from google.genai import types
import soundfile as sf
import librosa

async def test_gemini_live_audio():
    """Test Gemini Live API with audio input"""

    client = genai.Client(api_key="YOUR_API_KEY")
    model = "gemini-2.5-flash-native-audio-preview-09-2025"

    config = {
        "response_modalities": ["AUDIO"],  # Response as audio
        "system_instruction": "You are a helpful assistant. Keep responses brief.",
    }

    # Create sample audio (16-bit PCM, 16kHz, mono)
    sample_rate = 16000
    duration = 2  # 2 seconds of silence
    audio = np.zeros(int(sample_rate * duration), dtype=np.int16)

    # Convert to bytes
    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, subtype='PCM_16')
    buffer.seek(0)
    audio_bytes = buffer.read()

    async with client.aio.live.connect(model=model, config=config) as session:
        # Send audio
        await session.send_realtime_input(
            audio=types.Blob(
                data=audio_bytes,
                mime_type="audio/pcm;rate=16000"
            )
        )

        # Receive audio response (24kHz)
        audio_response = b""
        async for response in session.receive():
            if response.data:
                audio_response += response.data

        # Save response
        if audio_response:
            with open("response.wav", "wb") as f:
                f.write(audio_response)
            print("✓ Audio response saved to response.wav")

import numpy as np
if __name__ == "__main__":
    asyncio.run(test_gemini_live_audio())
```

---

## Phase 6: Integrate with SENA (Personal Details Flow)

### Key configuration for SENA onboarding:

```python
# In sena-ai/services/voice/src/voice/services/personal_details_service.py

from google import genai
from google.genai import types
import json

class GeminiLivePersonalDetailsService:
    """Replace Bedrock with Gemini Live for personal details collection"""

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.5-flash-native-audio-preview-09-2025"

    async def collect_personal_details(self, session_id: str, audio_data: bytes):
        """
        Process voice input, extract personal details

        Returns:
        {
            "fields": {"name": "...", "dob": "...", "ndis_number": "..."},
            "missing_fields": ["emergency_contact"],
            "completeness_score": 0.85,
            "agent_reply": "Got it. What is the emergency contact name?"
        }
        """

        config = {
            "response_modalities": ["TEXT"],  # Text for structured extraction
            "system_instruction": """You are an NDIS intake assistant.
            Your job is to collect these fields via conversation:
            - name (full name)
            - date_of_birth (YYYY-MM-DD)
            - ndis_number (10 digits)
            - primary_disability
            - emergency_contact_name
            - emergency_contact_phone

            Ask one field at a time. When done, output JSON:
            {"fields": {...}, "missing_fields": [...], "completeness_score": 0.0-1.0}
            """
        }

        async with self.client.aio.live.connect(
            model=self.model,
            config=config
        ) as session:
            # Send audio from user
            await session.send_realtime_input(
                audio=types.Blob(
                    data=audio_data,
                    mime_type="audio/pcm;rate=16000"
                )
            )

            # Get structured response
            async for response in session.receive():
                if response.text:
                    # Parse JSON response
                    return json.loads(response.text)
```

### Environment variable:

Add to `.env`:
```
SENA_AI_GEMINI_API_KEY=YOUR_API_KEY
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `API key invalid` | Copy from https://aistudio.google.com again, no spaces |
| `Connection timeout` | Check internet. Try curl test first. |
| `Model not found` | Use exact model name: `gemini-2.5-flash-native-audio-preview-09-2025` |
| `Audio format error` | Ensure 16-bit PCM, 16kHz, mono (use librosa to convert) |
| `Rate limited` | Free tier has limits. Use small requests to test. |
| `Data residency issue` | Gemini Live uses Google infrastructure (not AU). **Critical for SENA** — requires legal review. |

---

## Data Residency Warning ⚠️

**CRITICAL FOR SENA:** Personal details (name, DOB, NDIS number) are highly sensitive PII. Gemini Live runs on Google infrastructure, NOT Australian servers.

**Before production use:**
1. Verify Gemini Live availability in `australia-southeast1` region
2. Review Google's data processing agreement for NDIS compliance
3. Get legal sign-off on Australian Privacy Act / NDIS data requirements
4. Document data residency in SENA architecture decision log

---

## Next Steps

1. **Test it:** Run `python3 test_gemini_live.py` now
2. **If it works:** Move to Phase 5 (audio)
3. **Integrate:** Add GeminiLivePersonalDetailsService to SENA voice service
4. **Deploy:** Update `.env` in production with real API key (never commit)

---

## Official Docs

- **Gemini API Overview:** https://ai.google.dev/gemini-api/docs/api-overview
- **Gemini Live API Docs:** https://ai.google.dev/gemini-api/docs/live-api
- **Get API Key:** https://aistudio.google.com
- **Python SDK:** https://github.com/googleapis/python-genai

