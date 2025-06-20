"""
세그먼트-슬라이드 매핑 후처리 도구

강의 음성 세그먼트(STT)를 OpenAI 모델을 사용한 키워드 기반 의미적 유사성을 통해
해당하는 강의 슬라이드에 매핑합니다. 중심 슬라이드를 기준으로 이전/현재/다음 슬라이드만 참조합니다.

사용법:
    post_process(
        image_captioning_data: List[Dict[str, Any]],  # 이미지 캡셔닝 결과
        segment_split_data: List[Dict[str, Any]],     # 세그먼트 분리 결과
        centre_slide: int,                            # 중심 슬라이드 번호
        progress_callback=None                        # 진행률 콜백 함수
    )
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI

# ----------------------------------------------------------------------------
# 환경변수 설정
# ----------------------------------------------------------------------------

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://api.openai.com/v1",
)

# ----------------------------------------------------------------------------
# 세그먼트 병합 (메세지 크기 조정)
# ----------------------------------------------------------------------------

def merge_segments(segments: List[Dict[str, Any]]) -> str:
    """
    모든 세그먼트를 하나의 메시지로 병합합니다.
    """
    lines: List[str] = []
    for seg in segments:
        lines.append(f"- Segment ID: {seg['id']}\n  Text: {seg['text']}\n")
    return "\n".join(lines)

def get_relevant_slides(slides: List[Dict[str, Any]], centre: int) -> List[Dict[str, Any]]:
    """중심 슬라이드와 그 전후 슬라이드를 반환합니다."""
    relevant_slides = []
    for s in slides:
        if s["slide_number"] in [centre - 1, centre, centre + 1]:
            relevant_slides.append(s)
    return sorted(relevant_slides, key=lambda x: x["slide_number"])

def build_slide_prompt(slides: List[Dict[str, Any]]) -> str:
    """Format slide metadata exactly as required by the mapping prompt."""
    lines: List[str] = []
    for s in slides:
        lines.append(
            f"- Slide {s['slide_number']}\n"
            f"  - title_keywords: {json.dumps(s['title_keywords'], ensure_ascii=False)}\n"
            f"  - secondary_keywords: {json.dumps(s['secondary_keywords'], ensure_ascii=False)}\n"
            f"  - detail: {s['detail']}"
        )
    return "\n".join(lines)

# ----------------------------------------------------------------------------
# 매핑 API 호출
# ----------------------------------------------------------------------------

def call_mapping_api(
    segments_block: str, 
    slide_block: str,
    centre_slide: int
) -> List[Dict[str, int]]:
    user_content = f"""Slides (each has slide_number, type, title_keywords, secondary_keywords):
{slide_block}

Segments (Korean STT):
{segments_block}

Mapping rules
1. Match by semantic similarity, giving highest weight to title_keywords; use secondary_keywords for tie-breaking.
2. Slide types  
   • code   – segment explains source code / algorithm  
   • image  – segment describes a picture / chart / diagram  
   • content – normal explanatory slide with text or formulas  

Respond with the JSON array ONLY, e.g.:
[
  {{ "segment_id": 12, "slide_id": 5 }},
]
"""

    # 프롬프트 출력
    print("\n[DEBUG] ----- API PROMPT BEGIN -----")
    print(user_content)
    print("[DEBUG] ----- API PROMPT END -----\n")

    messages = [
        {
            "role": "system",
            "content": (
            "You map Korean lecture speech segments to the most relevant English slide. "
            "Prioritize title_keywords, use secondary_keywords as support. Return ONLY the JSON mapping array."
            "Every segment must be mapped to exactly one slide. No segment should be missing, and a single segment must not be mapped to multiple slides."
        ),
        },
        {"role": "user", "content": user_content},
    ]

    functions = [
        {
            "name": "return_segment_mapping",
            "description": "Maps lecture segments to slides.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mappings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "segment_id": {"type": "integer"},
                                "slide_id": {"type": "integer"},
                            },
                            "required": ["segment_id", "slide_id"],
                        },
                    }
                },
                "required": ["mappings"],
            },
        }
    ]

    response = client.chat.completions.create(
        model="gpt-4",
        messages=messages,
        functions=functions,
        function_call={"name": "return_segment_mapping"},
    )

    return json.loads(response.choices[0].message.function_call.arguments)["mappings"]

# ----------------------------------------------------------------------------
# 결과 저장
# ----------------------------------------------------------------------------

def save_results(mappings: List[Dict[str, int]], segments: List[Dict[str, Any]]) -> str:
    # 슬라이드별로 세그먼트 그룹화
    slide_segments = {}
    
    for mapping in mappings:
        slide_id = mapping["slide_id"]
        segment_id = mapping["segment_id"]
        
        # 해당 세그먼트의 텍스트 찾기
        segment_text = next((seg["text"] for seg in segments if seg["id"] == segment_id), "")
        
        # 슬라이드 ID를 문자열 형식으로 변환
        slide_key = "slide0" if slide_id == -1 else f"slide{slide_id}"
        
        if slide_key not in slide_segments:
            slide_segments[slide_key] = {"Segments": {}}
            
        slide_segments[slide_key]["Segments"][f"segment{segment_id}"] = {
            "text": segment_text
        }
    
    # 슬라이드 번호로 정렬 (문자열에서 숫자만 추출하여 정렬)
    sorted_slides = dict(sorted(
        slide_segments.items(),
        key=lambda x: int(x[0].replace("slide", "")) if x[0] != "slide0" else -1  # slide0은 맨 앞으로
    ))
    
    # 각 슬라이드 내의 세그먼트를 ID로 정렬
    for slide_key in sorted_slides:
        sorted_segments = dict(sorted(
            sorted_slides[slide_key]["Segments"].items(),
            key=lambda x: int(x[0].replace("segment", ""))
        ))
        sorted_slides[slide_key]["Segments"] = sorted_segments
    
    os.makedirs("data/segment_mapping", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"data/segment_mapping/segment_mapping_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted_slides, f, ensure_ascii=False, indent=2)
    return path

# ----------------------------------------------------------------------------
# 세그먼트 매핑 메인함수
# ----------------------------------------------------------------------------

def post_process(
    image_captioning_data: List[Dict[str, Any]],
    segment_split_data: List[Dict[str, Any]],
    centre_slide: int,
    progress_callback=None,
) -> Dict[str, Any]:
    """세그먼트 매핑을 수행합니다.
    
    Args:
        image_captioning_data: 이미지 캡셔닝 결과 JSON 데이터
        segment_split_data: 세그먼트 분리 결과 JSON 데이터
        centre_slide: 중심 슬라이드 번호
        progress_callback: 진행률 업데이트 콜백 함수
        
    Returns:
        매핑 결과 JSON 데이터
    """
    # 1. 데이터 준비 -------------------------------------------------------------------
    segments = segment_split_data
    slides = [s for s in image_captioning_data if s.get("type") != "meta"]

    # 2. 세그먼트 메시지 준비 ----------------------------------------------------
    segments_block = merge_segments(segments)

    # 3. 관련 슬라이드 선택 및 매핑 API 호출 -----------------------------------------
    relevant_slides = get_relevant_slides(slides, centre_slide)
    slide_prompt = build_slide_prompt(relevant_slides)
    
    if progress_callback:
        progress_callback(1, 1)
        
    mappings = call_mapping_api(
        segments_block,
        slide_prompt,
        centre_slide
    )

    # 4. 정렬 및 저장 --------------------------------------------------------------
    mappings.sort(key=lambda m: m["segment_id"])
    json_path = save_results(mappings, segments)
    print(f"[INFO] 매핑이 {json_path}에 저장되었습니다")

    return json.loads(open(json_path, "r", encoding="utf-8").read())

if __name__ == "__main__":
    import sys
    from typing import Dict, Any, List
    
    # 기본 경로 설정
    image_captioning_path = "data/image_captioning/image_captioning.json"
    segment_split_path = "data/segment_split/segment_split2.json"
    
    try:
        # 이미지 캡셔닝 데이터 로드
        with open(image_captioning_path, 'r', encoding='utf-8') as f:
            image_captioning_data = json.load(f)
            
        # 세그먼트 분리 데이터 로드
        with open(segment_split_path, 'r', encoding='utf-8') as f:
            segment_split_data = json.load(f)
            # Support both `[{}, …]` and `{segments: […]}` layouts
            if isinstance(segment_split_data, dict) and "segments" in segment_split_data:
                segment_split_data = segment_split_data["segments"]
        
        # 중심 슬라이드 번호 입력 받기
        centre_slide = int(input("중심 슬라이드 번호를 입력하세요: "))
        
        # 매핑 실행
        results = post_process(
            image_captioning_data=image_captioning_data,
            segment_split_data=segment_split_data,
            centre_slide=centre_slide
        )
        print(json.dumps(results, indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        sys.exit(1)
