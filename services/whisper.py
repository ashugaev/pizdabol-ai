import openai
from config import settings

client = openai.AsyncOpenAI(api_key=settings.openai_api_key)


async def transcribe(audio_path: str) -> str:
    with open(audio_path, "rb") as audio_file:
        response = await client.audio.transcriptions.create(
            model=settings.openai_transcription_model,
            file=audio_file,
            language="ru",
        )
    return response.text
