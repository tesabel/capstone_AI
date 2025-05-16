"""
세그먼트 매핑 결과를 슬라이드별로 구조화하여 저장하는 메인 스크립트

이 스크립트는 segment_mapping.py의 결과를 받아서 각 슬라이드별로 구조화된 형태로 변환하고,
결과를 JSON 파일로 저장합니다.
"""

import json
import os
from datetime import datetime
from typing import Dict, Any

from convert_audio import transcribe_audio
from segment_splitter import segment_split
from image_captioning import image_captioning
from segment_mapping import segment_mapping as segment_mapping_main
from summary import create_summary

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
    SKIP_SEGMENT_MAPPING = True
    SKIP_SUMMARY = True

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
    # 결과 디렉토리 생성
    output_dir = "result"
    os.makedirs(output_dir, exist_ok=True)
    
    # 현재 시간을 파일명에 포함
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = os.path.join(output_dir, f"result_{timestamp}.json")
    
    # 결과를 JSON 파일로 저장
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    return output_path

def main() -> Dict[str, Any]:
    """메인 실행 함수"""
    # 1. STT 실행
    stt_result = None
    if not Config.SKIP_STT:
        stt_result = transcribe_audio(Config.AUDIO_PATH)
    else:
        # 가장 최근 STT 결과 파일 찾기
        stt_dir = "data/stt_result"
        stt_files = [f for f in os.listdir(stt_dir) if f.startswith("stt_result_")]
        if stt_files:
            latest_stt = max(stt_files)
            with open(os.path.join(stt_dir, latest_stt), 'r', encoding='utf-8') as f:
                stt_result = json.load(f)

    # 2. 세그먼트 분리 실행
    segment_result = None
    if not Config.SKIP_SEGMENT_SPLIT:
        segment_result = segment_split(
            stt_data=stt_result,
            alpha=Config.ALPHA,
            seg_cnt=Config.SEG_CNT,
            post_process=Config.POST_PROCESS,
            max_size=Config.MAX_SEGMENT_LENGTH,
            min_size=Config.MIN_SEGMENT_LENGTH
        )
    else:
        # 가장 최근 세그먼트 분리 결과 파일 찾기
        segment_dir = "data/segment_split"
        segment_files = [f for f in os.listdir(segment_dir) if f.startswith("segment_split_")]
        if segment_files:
            latest_segment = max(segment_files)
            with open(os.path.join(segment_dir, latest_segment), 'r', encoding='utf-8') as f:
                segment_result = json.load(f)

    # 3. 이미지 캡셔닝 실행
    image_captioning_result = None
    if not Config.SKIP_IMAGE_CAPTIONING:
        image_captioning_result = image_captioning(Config.PDF_PATH)
    else:
        # 가장 최근 이미지 캡셔닝 결과 파일 찾기
        captioning_dir = "data/image_captioning"
        captioning_files = [f for f in os.listdir(captioning_dir) if f.startswith("image_captioning_")]
        if captioning_files:
            latest_captioning = max(captioning_files)
            with open(os.path.join(captioning_dir, latest_captioning), 'r', encoding='utf-8') as f:
                image_captioning_result = json.load(f)

    # 4. 세그먼트 매핑 실행
    mapping_result = None
    if not Config.SKIP_SEGMENT_MAPPING:
        mapping_result = segment_mapping_main(
            pdf_path=Config.PDF_PATH,
            audio_path=Config.AUDIO_PATH,
            skip_segment_split=True,  # 이미 위에서 처리했으므로 스킵
            skip_stt=True,  # 이미 위에서 처리했으므로 스킵
            skip_image_captioning=True,  # 이미 위에서 처리했으므로 스킵
            slide_window=Config.SLIDE_WINDOW,
            max_segment_length=Config.MAX_SEGMENT_LENGTH,
            min_segment_length=Config.MIN_SEGMENT_LENGTH,
            alpha=Config.ALPHA,
            seg_cnt=Config.SEG_CNT,
            post_process=Config.POST_PROCESS,
            max_size=Config.MAX_SIZE,
            min_size=Config.MIN_SIZE
        )
    else:
        # 가장 최근 세그먼트 매핑 결과 파일 찾기
        mapping_dir = "data/segment_mapping"
        mapping_files = [f for f in os.listdir(mapping_dir) if f.startswith("segment_mapping_")]
        if mapping_files:
            latest_mapping = max(mapping_files)
            with open(os.path.join(mapping_dir, latest_mapping), 'r', encoding='utf-8') as f:
                mapping_result = json.load(f)

    # 5. 요약 생성
    summary_result = None
    if not Config.SKIP_SUMMARY:
        summary_result = create_summary(
            image_captioning_data=image_captioning_result,
            segment_mapping_data=mapping_result
        )
    else:
        # 가장 최근 요약 결과 파일 찾기
        summary_dir = "data/summary"
        summary_files = [f for f in os.listdir(summary_dir) if f.startswith("summary_")]
        if summary_files:
            latest_summary = max(summary_files)
            with open(os.path.join(summary_dir, latest_summary), 'r', encoding='utf-8') as f:
                summary_result = json.load(f)

    # 6. 최종 결과 생성
    final_result = {}
    for slide_key in mapping_result.keys():
        if slide_key == "slide0":
            continue
            
        slide_number = int(slide_key.replace("slide", ""))
        if slide_number > len(image_captioning_result):
            continue

        # 해당 슬라이드의 캡셔닝 데이터
        slide_caption = image_captioning_result[slide_number - 1]
        
        # 세그먼트 데이터
        segments = mapping_result[slide_key].get("Segments", {})
        
        # 요약 데이터
        summary = summary_result.get(slide_key, {}) if summary_result else {}
        
        # 최종 결과 구성
        final_result[slide_key] = {
            "Concise Summary Notes": summary.get("Concise Summary Notes", ""),
            "Bullet Point Notes": summary.get("Bullet Point Notes", ""),
            "Keyword Notes": summary.get("Keyword Notes", ""),
            "Chart/Table Summary": summary.get("Chart/Table Summary", {}),
            "Segments": segments
        }

    # 결과 저장
    saved_path = save_results(final_result)
    print(f"[INFO] 결과가 {saved_path}에 저장되었습니다.")
    
    return final_result

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        Config.PDF_PATH = sys.argv[1]
    if len(sys.argv) > 2:
        Config.AUDIO_PATH = sys.argv[2]
    main() 