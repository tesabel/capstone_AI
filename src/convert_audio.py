import os
from openai import OpenAI
from dotenv import load_dotenv
import json
from datetime import datetime
from pydub import AudioSegment
import math

# .env 파일에서 환경 변수 로드
load_dotenv()

def split_audio_file(input_file, max_size_mb=24):
    """오디오 파일을 최대 크기 제한에 맞게 분할합니다."""
    # 파일 크기 확인
    file_size = os.path.getsize(input_file)
    max_size_bytes = max_size_mb * 1024 * 1024  # MB를 bytes로 변환
    
    if file_size <= max_size_bytes:
        return [input_file]
    
    # 오디오 파일 로드
    audio = AudioSegment.from_file(input_file)
    
    # 분할된 파일들을 저장할 리스트
    split_files = []
    
    # 10분 단위로 분할 (약 24MB)
    segment_length = 10 * 60 * 1000  # 10분을 밀리초로 변환
    num_segments = math.ceil(len(audio) / segment_length)
    
    for i in range(num_segments):
        start = i * segment_length
        end = min((i + 1) * segment_length, len(audio))
        segment = audio[start:end]
        
        # 임시 파일로 저장
        temp_file = f"temp_segment_{i}.mp4"
        segment.export(temp_file, format="mp4")
        split_files.append(temp_file)
    
    return split_files

def transcribe_audio(audio_file_path: str = "assets/os_35.m4a"):
    # API 키 확인
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
    
    print(f"API 키가 로드되었습니다: {api_key[:8]}...")
    
    # OpenAI 클라이언트 초기화
    client = OpenAI(api_key=api_key)
    
    # 출력 디렉토리 생성
    output_dir = "data/stt_result"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    try:
        # 오디오 파일 분할
        split_files = split_audio_file(audio_file_path)
        full_transcript = []
        
        for file_path in split_files:
            with open(file_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text",
                    language="ko"
                )
                full_transcript.append(transcript)
            
            # 임시 파일 삭제
            if file_path != audio_file_path:
                os.remove(file_path)
        
        # 전체 텍스트 합치기
        complete_transcript = "\n".join(full_transcript)
        
        # JSON 데이터 생성
        json_data = {
            "text": complete_transcript
        }
        
        # 현재 시간을 파일명에 포함
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_file = os.path.join(output_dir, f"stt_result_{timestamp}.json")
        
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
    audio_path = "assets/audio.wav"
    transcribe_audio(audio_path)
