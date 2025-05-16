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
# 데이터 로드
# ----------------------------------------------------------------------------

def load_segments(skip_stt: bool = True) -> List[Dict[str, Any]]:
    """Return a list of segments of the form ::
            {"id": int, "text": str}
    If *skip_stt* is **True** the cached file ``data/segment_split/segment_split.json``
    is used. Otherwise ``segment_splitter.main`` is executed.
    """
    if skip_stt:
        path = "data/segment_split/segment_split.json"
        if not os.path.exists(path):
            raise FileNotFoundError(f"STT result not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            cached = json.load(f)

        # Support both `[{}, …]` and `{segments: […]}` layouts
        if isinstance(cached, list):
            return cached
        if "segments" in cached:
            return cached["segments"]
        raise ValueError("Unexpected STT result format – expected list or {'segments': …}")

    # Live STT 실행 -------------------------------------------------------------
    from segment_splitter import main as segment_splitter_main  # type: ignore

    segs = segment_splitter_main(skip_stt=False)
    if isinstance(segs, dict) and "error" in segs:
        raise RuntimeError(segs["error"])
    return segs


def load_slides(skip_image_captioning: bool = True) -> List[Dict[str, Any]]:
    """Load image‑captioning results and drop slides whose *type* == "meta"."""
    if skip_image_captioning:
        path = "data/image_captioning/image_captioning.json"
        if not os.path.exists(path):
            raise FileNotFoundError(f"Captioning result not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            slides = json.load(f)
    else:
        from image_captioning import process_pdf  # type: ignore

        slides = process_pdf(skip_segment_split=True)

    return [s for s in slides if s.get("type") != "meta"]

# ----------------------------------------------------------------------------
# Transformation & prompt‑building 
# ----------------------------------------------------------------------------

def merge_segments(
    segments: List[Dict[str, Any]],
    max_len: int,
    min_len: int,
) -> List[str]:
    """Merge adjacent segments so each request stays under *max_len* characters.
    The merged block keeps **each** segment clearly separated – exactly one
    block per line as in ::
        - Segment ID: 1
        Text: …
    The final short remainder (if any) is appended to the previous batch when
    its length is below *min_len*.
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
            f"  - secondary_keywords: {json.dumps(s['secondary_keywords'], ensure_ascii=False)}"
        )
    return "\n".join(lines)


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

def save_results(mappings: List[Dict[str, int]]) -> str:
    os.makedirs("data/segment_mapping", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"data/segment_mapping/segment_mapping_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mappings, f, ensure_ascii=False, indent=2)
    return path

# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main(
    skip_segment_split: bool = True,
    skip_stt: bool = True,
    skip_image_captioning: bool = True,
    slide_window: int = 6,
    max_segment_length: int = 2000,
    min_segment_length: int = 500,
    alpha: float = 0.5,
    seg_cnt: int = -1,
    post_process: bool = True,
    max_size: int = 2000,
    min_size: int = 200,
) -> List[Dict[str, int]]:
    """엔드투엔드 매핑 루틴. 파라미터 상세는 모듈 독스트링을 참조하세요."""
    # 1. 데이터 로드 -------------------------------------------------------------------
    if skip_segment_split:
        segments = load_segments(skip_stt=True)
    else:
        from segment_splitter import main as segment_splitter_main
        segments = segment_splitter_main(
            skip_stt=skip_stt,
            alpha=alpha,
            seg_cnt=seg_cnt,
            post_process=post_process,
            max_size=max_size,
            min_size=min_size
        )
    
    slides = load_slides(skip_image_captioning)

    # 2. 세그먼트 메시지 준비 ----------------------------------------------------
    batches = merge_segments(segments, max_segment_length, min_segment_length)

    # 3. 모델 반복 호출 --------------------------------------------------
    current_centre = slides[0]["slide_number"] if slides else 1
    all_mappings: List[Dict[str, int]] = []
    message_count = 0

    for batch in batches:
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
    json_path = save_results(all_mappings)
    print(f"[INFO] 매핑이 {json_path}에 저장되었습니다")

    return all_mappings


if __name__ == "__main__":
    main()
