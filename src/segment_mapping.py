"""
세그먼트-슬라이드 매핑 도구

강의 음성 세그먼트(STT)를 OpenAI 모델을 사용한 키워드 기반 의미적 유사성을 통해
해당하는 강의 슬라이드에 매핑합니다.

사용법 (기본값 표시):
    main(
        skip_segment_split=True,       # 캐시된 세그먼트 분리 결과 사용
        skip_stt=True,                 # 캐시된 STT 결과 사용
        skip_image_captioning=True,    # 캐시된 이미지 캡셔닝 결과 사용
        slide_window=6,                # 현재 중심 슬라이드 전후로 포함할 슬라이드 수
        max_segment_length=2000,       # 병합 후 요청당 최대 문자 수
        min_segment_length=500,        # 마지막 배치가 이보다 짧으면 이전 배치에 추가
        alpha=0.5,                     # 세그먼트 분리 임계값
        seg_cnt=-1,                    # 세그먼트 수 (-1 또는 1 이상)
        post_process=True,             # 후처리 여부
        max_size=2000,                 # 후처리 시 최대 문단 크기
        min_size=200                   # 후처리 시 최소 문단 크기
    )

스크립트는 최종 매핑을 자동으로
``data/segment_mapping/segment_mapping_<YYYYMMDD_HHMM>.json``에 저장하고
메모리 내 매핑 목록을 반환합니다.

각 매핑 요소는 다음과 같은 형식입니다:
```json
{ "segment_id": <int>, "slide_id": <int> }
```
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

def merge_segments(
    segments: List[Dict[str, Any]],
    max_len: int,
    min_len: int,
) -> List[str]:
    """
    인접한 세그먼트를 병합하여 각 요청이 *max_len* 문자 이하가 되도록 병합
    마지막에 남는 세그먼트 길이가 *min_len*보다 짧다면 이전 세그먼트와 병합
    """
    batches: List[str] = []
    cur: List[str] = []
    cur_len = 0

    for seg in segments:
        snippet = f"- Segment ID: {seg['id']}\n  Text: {seg['text']}\n\n"
        if cur and cur_len + len(snippet) > max_len:
            batches.append("".join(cur))
            cur, cur_len = [], 0
        cur.append(snippet)
        cur_len += len(snippet)

    if cur:
        if batches and cur_len < min_len:
            batches[-1] += "".join(cur)
        else:
            batches.append("".join(cur))
    return batches


"""
참조할 슬라이드 크기만큼 메세지 크기 조정
"""
def slice_slides(slides: List[Dict[str, Any]], centre: int, window: int) -> List[Dict[str, Any]]:
    """Return ``slides`` whose *slide_number* is within ``centre±window``."""
    start = max(1, centre - window)
    end = centre + window
    return [s for s in slides if start <= s["slide_number"] <= end]


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
    message_count: int,
    start_slide: int,
    end_slide: int
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
   • non_content – cover / outline / goals / ending; **never map** (use slide_id −1)
3. If a segment does not clearly match any valid slide, or only matches a non_content slide, set slide_id to −1.

Respond with the JSON array ONLY, e.g.:
[
  {{ "segment_id": 12, "slide_id": 5 }},
  {{ "segment_id": 13, "slide_id": -1 }}
]

    """

    # 디버깅
    print("\n[DEBUG] ----- USER MESSAGE BEGIN -----")
    print(f"[DEBUG] 메시지 번호: {message_count}")
    print(f"[DEBUG] 병합된 세그먼트 길이: {len(segments_block)} 문자")
    print(f"[DEBUG] 슬라이드 범위: {start_slide} ~ {end_slide}")
    print(user_content)
    print("[DEBUG] ----- USER MESSAGE END -----\n")

    messages = [
        {
            "role": "system",
            "content": (
            "You map Korean lecture speech segments to the most relevant English slide. "
            "Prioritize title_keywords, use secondary_keywords as support, and NEVER match to slides whose type is "
            "'non_content'. Return ONLY the JSON mapping array."
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
        model="gpt-4o",
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

def segment_mapping(
    image_captioning_data: List[Dict[str, Any]],
    segment_split_data: List[Dict[str, Any]],
    slide_window: int = 6,
    max_segment_length: int = 2000,
    min_segment_length: int = 500,
    progress_callback=None,
) -> Dict[str, Any]:
    """세그먼트 매핑을 수행합니다.
    
    Args:
        image_captioning_data: 이미지 캡셔닝 결과 JSON 데이터
        segment_split_data: 세그먼트 분리 결과 JSON 데이터
        slide_window: 현재 중심 슬라이드 전후로 포함할 슬라이드 수
        max_segment_length: 병합 후 요청당 최대 문자 수
        min_segment_length: 마지막 배치가 이보다 짧으면 이전 배치에 추가
        progress_callback: 진행률 업데이트 콜백 함수 (current_batch, total_batches)
        
    Returns:
        매핑 결과 JSON 데이터
    """
    # 1. 데이터 준비 -------------------------------------------------------------------
    segments = segment_split_data
    slides = [s for s in image_captioning_data if s.get("type") != "meta"]

    # 2. 세그먼트 메시지 준비 ----------------------------------------------------
    batches = merge_segments(segments, max_segment_length, min_segment_length)

    # 3. 모델 반복 호출 --------------------------------------------------
    current_centre = slides[0]["slide_number"] if slides else 1
    all_mappings: List[Dict[str, int]] = []
    message_count = 0
    total_batches = len(batches)

    for i, batch in enumerate(batches, 1):
        # 진행률 콜백 호출
        if progress_callback:
            progress_callback(i, total_batches)
            
        relevant_slides = slice_slides(slides, current_centre, slide_window)
        start_slide = relevant_slides[0]["slide_number"] if relevant_slides else 0
        end_slide = relevant_slides[-1]["slide_number"] if relevant_slides else 0
        message_count += 1
        
        slide_prompt = build_slide_prompt(relevant_slides)
        batch_mappings = call_mapping_api(
            batch, 
            slide_prompt,
            message_count,
            start_slide,
            end_slide
        )
        all_mappings.extend(batch_mappings)

        # 다음 반복을 위한 중심 슬라이드 업데이트 -----------------------------
        if batch_mappings:
            valid_mappings = [m for m in batch_mappings if m["slide_id"] != -1]
            if valid_mappings:
                current_centre = max(m["slide_id"] for m in valid_mappings) - 1

    # 4. 정렬 및 저장 --------------------------------------------------------------
    all_mappings.sort(key=lambda m: m["segment_id"])
    json_path = save_results(all_mappings, segments)
    print(f"[INFO] 매핑이 {json_path}에 저장되었습니다")

    return json.loads(open(json_path, "r", encoding="utf-8").read())


if __name__ == "__main__":
    import sys
    from typing import Dict, Any, List
    
    # 기본 경로 설정
    image_captioning_path = "data/image_captioning/image_captioning.json"
    segment_split_path = "data/segment_split/segment_split.json"
    
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
        
        # 매핑 실행
        results = segment_mapping(
            image_captioning_data=image_captioning_data,
            segment_split_data=segment_split_data,
            slide_window=6,
            max_segment_length=2000,
            min_segment_length=500
        )
        print(json.dumps(results, indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        sys.exit(1)
