"""
WebSocket 스트리밍 STT 서버 테스트 스크립트
"""

import asyncio
import websockets
import json
import base64
import os
import wave
import struct

async def create_test_audio():
    """테스트용 PCM 오디오 데이터 생성 (16kHz, 16-bit, mono)"""
    # 1초간의 440Hz 톤 생성
    sample_rate = 16000
    duration = 1.0
    frequency = 440.0
    
    samples = []
    for i in range(int(sample_rate * duration)):
        # 16-bit 범위의 사인파 생성 (범위 제한)
        import math
        sample_value = 32767 * 0.3 * math.sin(2.0 * math.pi * frequency * i / sample_rate)
        sample = max(-32768, min(32767, int(sample_value)))
        samples.append(sample)
    
    # Int16 PCM 데이터로 변환
    audio_data = b''.join(struct.pack('<h', sample) for sample in samples)
    return audio_data

async def test_websocket_connection():
    """WebSocket 연결 및 스트리밍 테스트"""
    uri = "ws://localhost:8001"
    
    try:
        print("WebSocket 서버에 연결 중...")
        async with websockets.connect(uri) as websocket:
            print("연결 성공!")
            
            # 초기 연결 메시지 전송 (jobId 포함)
            init_message = {
                "jobId": "test_20241230_1200"
            }
            await websocket.send(json.dumps(init_message))
            
            # 연결 응답 수신
            response = await websocket.recv()
            print(f"연결 응답: {response}")
            
            # 테스트 오디오 데이터 생성
            test_audio = await create_test_audio()
            
            # 여러 슬라이드로 테스트 메시지 전송
            for slide_num in range(1, 4):
                print(f"\n슬라이드 {slide_num} 테스트 중...")
                
                # 오디오를 5개 청크로 분할 (바이너리 레벨에서)
                audio_chunk_size = len(test_audio) // 5
                for i in range(5):
                    start_idx = i * audio_chunk_size
                    end_idx = start_idx + audio_chunk_size if i < 4 else len(test_audio)
                    audio_chunk = test_audio[start_idx:end_idx]
                    
                    # 각 청크를 base64로 인코딩
                    chunk_base64 = base64.b64encode(audio_chunk).decode('utf-8')
                    
                    message = {
                        "slide": slide_num,
                        "audio": chunk_base64
                    }
                    
                    await websocket.send(json.dumps(message))
                    print(f"  청크 {i+1}/5 전송 완료")
                    
                    # 응답 수신 (논블로킹)
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        print(f"  응답: {response[:100]}...")
                    except asyncio.TimeoutError:
                        print("  응답 대기 타임아웃")
                    
                    # 잠시 대기 (실시간 스트리밍 시뮬레이션)
                    await asyncio.sleep(0.5)
            
            print("\n테스트 완료!")
            
    except (ConnectionRefusedError, OSError):
        print("연결 실패: 서버가 실행 중인지 확인하세요.")
        print("서버 실행: python streaming_server.py")
    except Exception as e:
        print(f"테스트 오류: {e}")

async def test_message_format():
    """메시지 형식 테스트"""
    print("\n=== 메시지 형식 테스트 ===")
    
    # 올바른 메시지 형식
    valid_message = {
        "slide": 1,
        "audio": "dGVzdCBhdWRpbyBkYXRh"  # "test audio data"의 base64
    }
    print(f"올바른 메시지: {json.dumps(valid_message, indent=2)}")
    
    # 잘못된 메시지 형식들
    invalid_messages = [
        {"slide": 1},  # audio 누락
        {"audio": "dGVzdA=="},  # slide 누락
        {"slide": "invalid", "audio": "dGVzdA=="},  # slide가 숫자가 아님
        "invalid json"  # JSON이 아님
    ]
    
    print("\n잘못된 메시지 형식들:")
    for i, msg in enumerate(invalid_messages):
        print(f"{i+1}. {msg}")

def main():
    """메인 테스트 함수"""
    print("=== WebSocket 스트리밍 STT 테스트 ===")
    
    # 메시지 형식 테스트
    asyncio.run(test_message_format())
    
    # 실제 WebSocket 연결 테스트
    print("\n=== 실제 연결 테스트 ===")
    asyncio.run(test_websocket_connection())

if __name__ == "__main__":
    main()