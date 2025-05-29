import os
import subprocess
from openai import OpenAI
from dotenv import load_dotenv
import json
from datetime import datetime

# .env 파일에서 환경 변수 로드
load_dotenv()

def convert_audio_to_whisper_format(input_path: str, output_path: str):
    """ffmpeg로 whisper-friendly WAV 형식으로 변환"""
    command = [
        "ffmpeg",
        "-y",  # 기존 파일 덮어쓰기
        "-i", input_path,
        "-ar", "16000",  # 샘플레이트 16kHz
        "-ac", "1",      # 모노
        "-c:a", "pcm_s16le",  # 16-bit PCM
        output_path
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg 변환 실패: {e}")

def transcribe_audio_with_timestamps(audio_file_path: str):
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
    
    print(f"API 키가 로드되었습니다: {api_key[:8]}...")
    
    client = OpenAI(api_key=api_key)
    
    output_dir = "data/realtime_convert_audio"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 변환된 파일 경로
    converted_path = audio_file_path.replace(".wav", "_converted.wav")
    convert_audio_to_whisper_format(audio_file_path, converted_path)

    try:
        with open(converted_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        
        json_data = {
            "text": transcript
        }
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_file = os.path.join(output_dir, f"realtime_stt_result_{timestamp}.json")
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        
        print(f"변환이 완료되었습니다. 결과가 {output_file}에 저장되었습니다.")
        print("JSON 결과:")
        print(json.dumps(json_data, ensure_ascii=False, indent=2))

        return json_data
        
    except Exception as e:
        print(f"오류가 발생했습니다: {str(e)}")
        return None
    finally:
        if os.path.exists(converted_path):
            os.remove(converted_path)

if __name__ == "__main__":
    audio_path = "assets/audio.wav"
    transcribe_audio_with_timestamps(audio_path)
