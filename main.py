"""
세그먼트 매핑 결과를 슬라이드별로 구조화하여 저장하는 메인 스크립트

이 스크립트는 segment_mapping.py의 결과를 받아서 각 슬라이드별로 구조화된 형태로 변환하고,
결과를 JSON 파일로 저장합니다.
"""

import json
import os
from datetime import datetime
from typing import Dict, Any

from segment_mapping import segment_mapping as segment_mapping_main

# 설정값 정의
class Config:
    # ---------------------------- 파일 경로 설정 ----------------------------
    # PDF 파일 경로
    PDF_PATH = "assets/os_35.pdf"
    # 오디오 파일 경로
    AUDIO_PATH = "assets/os_35.m4a"

    # ---------------------------- 과정 스킵 여부 ----------------------------
    SKIP_SEGMENT_SPLIT = True
    SKIP_STT = True
    SKIP_IMAGE_CAPTIONING = True

    # ---------------------------- 클로바 세그먼트 분리 파라미터 ----------------------------
    # 민감도 조정 파라미터 (-1.5 ~ 1.5)
    # 클수록 더 많은 세그먼트로 분리
    ALPHA = 0.5

    # 세그먼트 개수 (-1 = 자동)
    SEG_CNT = -1

    # 후처리 여부
    POST_PROCESS = True

    # 세그먼트 최대 문자 수 (후처리)
    MAX_SEGMENT_LENGTH = 2000
    # 세그먼트 최소 문자 수 (후처리)
    MIN_SEGMENT_LENGTH = 500

    # ---------------------------- 프롬프트 메세지 단위 크기 조정 ----------------------------
    # 관찰할 슬라이드 개수 
    SLIDE_WINDOW = 6
    # 최대 문자 수  
    MAX_SIZE = 2000
    # 마지막 세그먼트 최소 문자 수 (조건 충족 시 이전 세그먼트와 병합)
    MIN_SIZE = 200

def save_results(result: Dict[str, Any]) -> str:
    """결과를 JSON 파일로 저장합니다."""
    os.makedirs("data/result", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"data/result/result_{timestamp}.json"
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    return filename

def main() -> Dict[str, Any]:
    """메인 실행 함수"""
    # 1. 세그먼트 매핑 실행
    result = segment_mapping_main(
        pdf_path=Config.PDF_PATH,
        audio_path=Config.AUDIO_PATH,
        skip_segment_split=Config.SKIP_SEGMENT_SPLIT,
        skip_stt=Config.SKIP_STT,
        skip_image_captioning=Config.SKIP_IMAGE_CAPTIONING,
        slide_window=Config.SLIDE_WINDOW,
        max_segment_length=Config.MAX_SEGMENT_LENGTH,
        min_segment_length=Config.MIN_SEGMENT_LENGTH,
        alpha=Config.ALPHA,
        seg_cnt=Config.SEG_CNT,
        post_process=Config.POST_PROCESS,
        max_size=Config.MAX_SIZE,
        min_size=Config.MIN_SIZE
    )
    
    # 2. 결과 저장
    saved_path = save_results(result)
    print(f"[INFO] 결과가 {saved_path}에 저장되었습니다.")
    
    return result

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        Config.PDF_PATH = sys.argv[1]
    if len(sys.argv) > 2:
        Config.AUDIO_PATH = sys.argv[2]
    main() 