"""
세그먼트 매핑 결과를 슬라이드별로 구조화하여 저장하는 메인 스크립트

이 스크립트는 segment_mapping.py의 결과를 받아서 각 슬라이드별로 구조화된 형태로 변환하고,
결과를 JSON 파일로 저장합니다.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Any

from segment_mapping import main as segment_mapping_main

# 설정값 정의
class Config:
    # ---------------------------- 과정 스킵 여부 ----------------------------
    SKIP_SEGMENT_SPLIT = False
    SKIP_STT = False
    SKIP_IMAGE_CAPTIONING = False


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



def load_segments_data() -> List[Dict[str, Any]]:
    """segment_mapping.py의 결과를 로드합니다."""
    return segment_mapping_main(
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

def load_slides_data() -> List[Dict[str, Any]]:
    """슬라이드 데이터를 로드합니다."""
    with open("data/image_captioning/image_captioning.json", "r", encoding="utf-8") as f:
        return json.load(f)

def load_segments_text() -> Dict[int, str]:
    """세그먼트 텍스트를 로드합니다."""
    with open("data/segment_split/segment_split.json", "r", encoding="utf-8") as f:
        segments = json.load(f)
        if isinstance(segments, dict) and "segments" in segments:
            segments = segments["segments"]
        return {seg["id"]: seg["text"] for seg in segments}

def create_slide_summary(slide: Dict[str, Any], segments: List[Dict[str, int]], segments_text: Dict[int, str]) -> Dict[str, Any]:
    """각 슬라이드에 대한 요약 정보를 생성합니다."""
    slide_number = slide["slide_number"]
    slide_segments = [s for s in segments if s["slide_id"] == slide_number]
    
    # 슬라이드와 관련된 세그먼트 정보 수집
    segments_info = {}
    for seg in slide_segments:
        segment_id = seg["segment_id"]
        segments_info[f"segment{segment_id}"] = {
            "text": segments_text.get(segment_id, ""),
            "isImportant": "false",
            "reason": "",
            "linkedConcept": "",
            "pageNumber": ""
        }

    return {
        "Concise Summary Notes": "",
        "Bullet Point Notes": "",
        "Keyword Notes": "",
        "Chart/Table Summary": {
            "주제": slide.get("title_keywords", [""])[0],
            "부주제": slide.get("secondary_keywords", [""])[0] if slide.get("secondary_keywords") else ""
        },
        "Segments": segments_info
    }

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
    # 1. 필요한 데이터 로드
    mappings = load_segments_data()
    slides = load_slides_data()
    segments_text = load_segments_text()
    
    # 2. 결과 구조 생성
    result = {}
    for slide in slides:
        if slide.get("type") == "meta":
            continue
            
        slide_number = slide["slide_number"]
        result[f"slide{slide_number}"] = create_slide_summary(
            slide, mappings, segments_text
        )
    
    # 3. 결과 저장
    saved_path = save_results(result)
    print(f"[INFO] 결과가 {saved_path}에 저장되었습니다.")
    
    return result

if __name__ == "__main__":
    main() 