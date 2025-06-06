"""
WebSocket 기반 실시간 STT 스트리밍 서버

기존 Flask 서버와 병행 운영되는 WebSocket 서버로,
실시간 오디오 스트리밍과 슬라이드별 음성 인식 결과를 처리합니다.
"""

import asyncio
import websockets
import json
import base64
import os
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional
import logging

from google.cloud import speech
from openai import OpenAI
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class STTSession:
    """WebSocket 연결별 STT 세션 관리 클래스"""
    
    def __init__(self, websocket, job_id: str):
        self.websocket = websocket # 웹소켓 연결 객체
        self.job_id = job_id # 작업 ID 
        self.slide_data: Dict[str, Any] = {} # 슬라이드 데이터
        self.current_slide: Optional[int] = None # 현재 슬라이드 번호
        self.last_activity_time = datetime.now() # 마지막 활동 시간
        self.speech_client = None # 구글 클라우드 스트리밍 클라이언트
        self.recognize_stream = None # 인식 스트림
        self.openai_client = None # OpenAI 클라이언트
        self.temp_audio_buffer = bytearray() # 임시 오디오 버퍼
        
        # 구글 클라우드 또는 OpenAI 클라이언트 초기화
        self.init_stt_client()
    
    def init_stt_client(self):
        """STT 클라이언트 초기화 (Google Cloud 또는 OpenAI)"""
        try:
            # Google Cloud Speech-to-Text 시도
            if os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
                self.speech_client = speech.SpeechClient()
                self.setup_google_stream()
                logger.info("Google Cloud Speech-to-Text 초기화 완료")
            else:
                # OpenAI Whisper 사용
                api_key = os.getenv('OPENAI_API_KEY')
                if api_key:
                    self.openai_client = OpenAI(api_key=api_key)
                    logger.info("OpenAI Whisper 초기화 완료")
                else:
                    raise ValueError("GOOGLE_APPLICATION_CREDENTIALS 또는 OPENAI_API_KEY가 설정되지 않았습니다.")
        except Exception as e:
            logger.error(f"STT 클라이언트 초기화 실패: {e}")
            raise
    
    def setup_google_stream(self):
        """Google Cloud Speech-to-Text 스트림 설정 - 간단한 방식"""
        if not self.speech_client:
            return
            
        try:
            # 기본 설정
            self.google_config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000, # 샘플 레이트 16kHz (추천 값)
                language_code="ko-KR",
                enable_automatic_punctuation=False, # 자동 구두점 사용
            )
            
            logger.info("Google Cloud Speech-to-Text 설정 완료")
            
        except Exception as e:
            logger.error(f"Google 설정 실패: {e}")
            self.speech_client = None
    
    async def process_google_audio_chunk(self, audio_data: bytes):
        """Google Cloud Speech-to-Text로 오디오 청크 처리 (배치 방식)"""
        if not self.speech_client or not hasattr(self, 'google_config'):
            return
            
        try:
            # 오디오 데이터가 충분히 클 때만 처리 (1초 이상)
            if len(audio_data) < 16000 * 2:  # 16kHz * 2bytes * 1초
                return
                
            # 동기식 음성 인식
            audio = speech.RecognitionAudio(content=audio_data)
            
            response = self.speech_client.recognize(
                config=self.google_config, 
                audio=audio
            )
            
            # 결과 처리
            for result in response.results:
                transcript = result.alternatives[0].transcript
                if transcript.strip():
                    await self.handle_stt_result(transcript, True)
                    logger.info(f"Google STT 결과: {transcript}")
                    
        except Exception as e:
            logger.error(f"Google 음성 인식 오류: {e}")
            # Google 실패 시 OpenAI로 fallback
            await self.process_openai_audio(audio_data)
    
    async def process_openai_audio(self, audio_data: bytes):
        """OpenAI Whisper로 오디오 처리"""
        if not self.openai_client:
            return
            
        try:
            # WAV 헤더 생성 (16kHz, 16-bit, mono)
            wav_data = self.create_wav_header(len(audio_data)) + audio_data
            
            # 임시 파일로 오디오 저장
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_file.write(wav_data)
                temp_file_path = temp_file.name
            
            # Whisper API 호출
            with open(temp_file_path, "rb") as audio_file:
                transcript = self.openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text",
                    language="ko"
                )
            
            # 임시 파일 삭제
            os.unlink(temp_file_path)
            
            # 결과 처리 (최종 결과로 처리)
            await self.handle_stt_result(str(transcript), True)
            
        except Exception as e:
            logger.error(f"OpenAI 처리 오류: {e}")
    
    def create_wav_header(self, data_length: int) -> bytes: # WAV 헤더 생성 (Whisper 전용)
        """WAV 헤더 생성 (16kHz, 16-bit, mono)"""
        import struct
        
        sample_rate = 16000
        bits_per_sample = 16
        channels = 1
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8
        
        # WAV 헤더 구성
        header = struct.pack('<4sI4s',
                            b'RIFF',
                            36 + data_length,  # ChunkSize
                            b'WAVE')
        
        header += struct.pack('<4sIHHIIHH',
                            b'fmt ',
                            16,  # Subchunk1Size
                            1,   # AudioFormat (PCM)
                            channels,
                            sample_rate,
                            byte_rate,
                            block_align,
                            bits_per_sample)
        
        header += struct.pack('<4sI',
                            b'data',
                            data_length)
        
        return header
    
    async def handle_stt_result(self, transcript: str, is_final: bool): # 음성 인식 json 형식 처리 (기존 코드와 동일)
        """STT 결과 처리 및 클라이언트 전송"""
        if not self.current_slide or not transcript.strip():
            return
        
        slide_key = f"slide{self.current_slide}"
        segment_key = f"segment{self.current_slide}"
        
        # 슬라이드 데이터 초기화
        if slide_key not in self.slide_data:
            self.slide_data[slide_key] = {
                "Concise Summary Notes": "",
                "Bullet Point Notes": "",
                "Keyword Notes": "",
                "Chart/Table Summary": "",
                "Segments": {}
            }
        
        # 세그먼트가 없으면 생성
        if segment_key not in self.slide_data[slide_key]["Segments"]:
            self.slide_data[slide_key]["Segments"][segment_key] = {
                "text": "",
                "isImportant": "false",
                "reason": "",
                "linkedConcept": "",
                "pageNumber": str(self.current_slide)
            }
        
        # 기존 텍스트에 새로운 텍스트 추가
        current_text = self.slide_data[slide_key]["Segments"][segment_key]["text"]
        if current_text:
            self.slide_data[slide_key]["Segments"][segment_key]["text"] = f"{current_text} {transcript.strip()}"
        else:
            self.slide_data[slide_key]["Segments"][segment_key]["text"] = transcript.strip()
        
        # result.json 저장
        await self.save_result_json()
        
        # 클라이언트에 전송
        await self.send_update()
    
    async def process_audio_chunk(self, slide: int, audio_base64: str):
        """오디오 청크 처리"""
        try:
            self.current_slide = slide
            self.last_activity_time = datetime.now()
            
            # Base64 디코딩
            audio_data = base64.b64decode(audio_base64)
            
            if self.speech_client:
                # Google Cloud Speech-to-Text 사용
                self.temp_audio_buffer.extend(audio_data)
                
                # 일정 크기 이상일 때 처리 (예: 32KB = 1초 오디오)
                if len(self.temp_audio_buffer) >= 32000:
                    await self.process_google_audio_chunk(bytes(self.temp_audio_buffer))
                    self.temp_audio_buffer = bytearray()
            else:
                # OpenAI Whisper 사용 (버퍼링 후 일정 크기마다 처리)
                self.temp_audio_buffer.extend(audio_data)
                
                # 일정 크기 이상일 때 처리 (예: 64KB)
                if len(self.temp_audio_buffer) >= 65536:
                    await self.process_openai_audio(bytes(self.temp_audio_buffer))
                    self.temp_audio_buffer = bytearray()
                    
        except Exception as e:
            logger.error(f"오디오 청크 처리 오류: {e}")
            await self.send_error(f"오디오 처리 오류: {str(e)}")
    
    async def save_result_json(self):
        """result.json 파일 저장"""
        try:
            job_dir = os.path.join("file", self.job_id)
            os.makedirs(job_dir, exist_ok=True)
            
            result_path = os.path.join(job_dir, "result.json")
            with open(result_path, 'w', encoding='utf-8') as f:
                json.dump(self.slide_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"result.json 저장 오류: {e}")
    
    async def send_update(self):
        """클라이언트에 업데이트 전송"""
        try:
            await self.websocket.send(json.dumps(self.slide_data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"업데이트 전송 오류: {e}")
    
    async def send_error(self, error_message: str):
        """에러 메시지 전송"""
        try:
            error_data = {"error": error_message}
            await self.websocket.send(json.dumps(error_data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"에러 전송 실패: {e}")
    
    def cleanup(self):
        """세션 정리"""
        try:
            if self.recognize_stream:
                self.recognize_stream.cancel()
            if self.temp_audio_buffer:
                # 남은 버퍼 처리
                if self.openai_client and len(self.temp_audio_buffer) > 0:
                    asyncio.create_task(self.process_openai_audio(bytes(self.temp_audio_buffer)))
        except Exception as e:
            logger.error(f"세션 정리 오류: {e}")

# 활성 세션 관리
active_sessions: Dict[str, STTSession] = {}

async def handle_websocket(websocket):
    """WebSocket 연결 처리"""
    session = None
    try:
        logger.info(f"새 WebSocket 연결: {websocket.remote_address}")
        
        # 초기 메시지에서 jobId 받기
        initial_message = await websocket.recv()
        try:
            init_data = json.loads(initial_message)
            job_id = init_data.get("jobId")
            if not job_id:
                await websocket.send(json.dumps({"error": "jobId가 필요합니다."}))
                return
        except json.JSONDecodeError:
            await websocket.send(json.dumps({"error": "잘못된 JSON 형식입니다."}))
            return
        
        # 세션 생성
        session = STTSession(websocket, job_id)
        active_sessions[job_id] = session
        
        # 연결 성공 응답
        await websocket.send(json.dumps({"status": "connected", "jobId": job_id}))
        
        # 메시지 처리 루프
        async for message in websocket:
            try:
                data = json.loads(message)
                slide = data.get("slide")
                audio = data.get("audio")
                
                if slide is not None and audio:
                    await session.process_audio_chunk(slide, audio)
                else:
                    await session.send_error("slide와 audio 데이터가 필요합니다.")
                    
            except json.JSONDecodeError:
                await session.send_error("잘못된 JSON 형식입니다.")
            except Exception as e:
                logger.error(f"메시지 처리 오류: {e}")
                await session.send_error(f"메시지 처리 오류: {str(e)}")
                
    except websockets.exceptions.ConnectionClosed:
        logger.info("WebSocket 연결이 종료되었습니다.")
    except Exception as e:
        logger.error(f"WebSocket 처리 오류: {e}")
    finally:
        # 세션 정리
        if session:
            session.cleanup()
            if session.job_id in active_sessions:
                del active_sessions[session.job_id]

async def cleanup_inactive_sessions():
    """비활성 세션 정리"""
    while True:
        try:
            current_time = datetime.now()
            inactive_sessions = []
            
            for job_id, session in active_sessions.items():
                if (current_time - session.last_activity_time).seconds > 3600:  # 1시간
                    inactive_sessions.append(job_id)
            
            for job_id in inactive_sessions:
                if job_id in active_sessions:
                    active_sessions[job_id].cleanup()
                    del active_sessions[job_id]
                    logger.info(f"비활성 세션 정리: {job_id}")
            
            await asyncio.sleep(300)  # 5분마다 체크
        except Exception as e:
            logger.error(f"세션 정리 오류: {e}")

async def main_async():
    """비동기 메인 함수"""
    # 데이터 디렉토리 생성
    os.makedirs("file", exist_ok=True)
    
    # 서버 설정
    host = "0.0.0.0"
    port = 8001
    
    logger.info(f"WebSocket 스트리밍 STT 서버 시작: ws://{host}:{port}")
    
    # 비활성 세션 정리 태스크 시작
    cleanup_task = asyncio.create_task(cleanup_inactive_sessions())
    
    # WebSocket 서버 시작
    try:
        async with websockets.serve(handle_websocket, host, port):
            logger.info("서버가 시작되었습니다.")
            await asyncio.Future()  # 무한 대기
    except KeyboardInterrupt:
        logger.info("서버가 종료되었습니다.")
        cleanup_task.cancel()
    except Exception as e:
        logger.error(f"서버 오류: {e}")
        cleanup_task.cancel()

def main():
    """메인 서버 실행"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("서버 종료")
    except Exception as e:
        logger.error(f"메인 함수 오류: {e}")

if __name__ == "__main__":
    main()