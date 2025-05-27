import os
from openai import OpenAI
from dotenv import load_dotenv
import json
from datetime import datetime

# .env 파일에서 환경 변수 로드
load_dotenv()

def transcribe_audio_with_timestamps(audio_file_path: str = "assets/os_35.m4a"):
    # API 키 확인
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
    
    print(f"API 키가 로드되었습니다: {api_key[:8]}...")
    
    # OpenAI 클라이언트 초기화
    client = OpenAI(api_key=api_key)
    
    # 출력 디렉토리 생성
    output_dir = "data/realtime_convert_audio"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    try:
        with open(audio_file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        
        # JSON 데이터 생성
        json_data = {
            "text": transcript
        }
        
        # 현재 시간을 파일명에 포함
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_file = os.path.join(output_dir, f"realtime_stt_result_{timestamp}.json")
        
        # 결과를 JSON 파일로 저장
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        
        print(f"변환이 완료되었습니다. 결과가 {output_file}에 저장되었습니다.")
        print("JSON 결과:")
        print(json.dumps(json_data, ensure_ascii=False, indent=2))
        
        return json_data
        
    except Exception as e:
        print(f"오류가 발생했습니다: {str(e)}")
        return None

if __name__ == "__main__":
    audio_path = "assets/test.m4a"
    transcribe_audio_with_timestamps(audio_path) 