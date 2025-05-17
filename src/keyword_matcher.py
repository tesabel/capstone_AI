#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
1) 세그먼트·슬라이드 키워드 추출
2) 발음 기반 유사도 비교 (Korean ↔ English)
   └ panphon + Hangul->Jamo 변환 + 공통 편집거리

필수 파이썬 패키지
    pip install konlpy panphon python-Levenshtein unidecode jamo
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

# ---- 1. 형태소 분석 기반 키워드 추출 ----------------------
from konlpy.tag import Okt         # 한국어 형태소 분석기
okt = Okt()

def extract_nouns(text: str) -> List[str]:
    """한국어 문장에서 명사·영단어·숫자 등을 뽑아낸다."""
    # Okt: ('단어', 'Noun') 등 반환 → Noun(명사)만 추출
    return [w for w, tag in okt.pos(text) if tag == "Noun"]

# ---- 2. 발음 전처리 ----------------------------------------
from jamo import h2j                # 한글 → 자모
from unidecode import unidecode     # 영단어 → ASCII (예: résumé → resume)
import panphon

ft = panphon.FeatureTable()

def ipa_korean(word: str) -> str:
    """한글 단어를 자모 기준(초성/중성/종성)으로 '가-나-다'처럼 변형."""
    return " ".join(h2j(word))           # 예: '운영체제' → 'ㅇ ㅜ ㄴ ...'

def ipa_english(word: str) -> str:
    """영단어를 발음 특성 벡터로 변환(panphon)."""
    ascii_word = unidecode(word)         # 대충이라도 ASCII로 맞춰주기
    try:
        # 발음 특성 벡터를 문자열로 변환
        features = ft.word_to_feature_vectors(ascii_word.lower())
        if features:
            # 특성 벡터를 문자열로 변환 (0과 1의 시퀀스)
            return "".join(str(int(x)) for vec in features for x in vec)
    except:
        pass
    return ascii_word             # 실패하면 원형 반환

def phoneme_distance(p1: str, p2: str) -> float:
    """편집거리 기반 유사도 (0~1) – 길이 가중 Levenshtein."""
    import Levenshtein as lev
    dist = lev.distance(p1, p2)
    max_len = max(len(p1), len(p2), 1)
    return 1 - (dist / max_len)

# ---- 3. 키워드 매칭 메인 함수 ----------------------------
def keyword_matching(
    seg_json: List[dict],
    slide_json: List[dict],
    threshold: float = 0.1
) -> List[dict]:
    """세그먼트와 슬라이드의 키워드를 추출하고 매칭합니다.
    
    Args:
        seg_json: 세그먼트 분리 결과 JSON 데이터
        slide_json: 이미지 캡셔닝 결과 JSON 데이터
        threshold: 발음 유사도 임계값 (0~1)
        
    Returns:
        매칭 결과 리스트
    """
    print("\n=== 키워드 매칭 시작 ===")
    print(f"세그먼트 수: {len(seg_json)}")
    print(f"슬라이드 수: {len(slide_json)}")
    print(f"유사도 임계값: {threshold}")
    
    # 1. 세그먼트 키워드 추출
    print("\n1. 세그먼트 키워드 추출 중...")
    seg_dict = {}
    for seg in seg_json:
        seg_id = str(seg["id"])
        nouns = extract_nouns(seg["text"])
        seg_dict[seg_id] = nouns
        if len(nouns) > 0:
            print(f"  세그먼트 {seg_id}: {nouns}")

    # 2. 슬라이드 키워드 추출
    print("\n2. 슬라이드 키워드 추출 중...")
    slide_dict = defaultdict(list)
    for slide in slide_json:
        num = str(slide["slide_number"])
        slide_dict[num].extend(slide.get("title_keywords", []))
        slide_dict[num].extend(slide.get("secondary_keywords", []))
        if len(slide_dict[num]) > 0:
            print(f"  슬라이드 {num}: {slide_dict[num]}")
    # 중복 제거
    slide_dict = {k: list(dict.fromkeys(v)) for k, v in slide_dict.items()}

    # 3. 발음 유사도 비교
    print("\n3. 발음 유사도 비교 중...")
    results = []
    # 미리 slide-level 발음 변환 캐시
    slide_phon = {
        s: [(kw, ipa_english(kw)) for kw in kws] for s, kws in slide_dict.items()
    }

    for seg_id, words in seg_dict.items():
        print(f"\n  세그먼트 {seg_id} 처리 중...")
        # 세그먼트 단어들을 IPA/Jamo로 변환
        seg_phon = [(w, ipa_korean(w)) for w in words]
        for slide_num, slide_words in slide_phon.items():
            matches = []
            for seg_word, seg_ipa in seg_phon:
                for kw, kw_ipa in slide_words:
                    score = phoneme_distance(seg_ipa, kw_ipa)
                    # print(f"    비교: '{seg_word}'({seg_ipa}) vs '{kw}'({kw_ipa}) = {score:.2f}")
                    if score >= threshold:
                        matches.append(
                            {
                                "segment_word": seg_word,
                                "matched_keyword": kw,
                                "score": round(score, 2)
                            }
                        )
            if matches:
                print(f"    슬라이드 {slide_num}와 매칭됨: {matches}")
                results.append(
                    {
                        "slide_number": int(slide_num),
                        "segment_id": int(seg_id),
                        "matches": matches
                    }
                )

    print(f"\n=== 매칭 완료: 총 {len(results)}개의 매칭 결과 ===")
    return results

# ------------------------------------------------------------
def main():
    # 기본 경로 설정
    img_path = Path("data/image_captioning/image_captioning.json")
    seg_path = Path("data/segment_split/segment_split.json")
    
    try:
        print("\n=== 데이터 로드 시작 ===")
        # 데이터 로드
        slide_json = json.loads(img_path.read_text(encoding="utf-8"))
        print(f"이미지 캡셔닝 데이터 로드 완료: {len(slide_json)}개 슬라이드")
        
        seg_json = json.loads(seg_path.read_text(encoding="utf-8"))
        print(f"세그먼트 분리 데이터 로드 완료: {len(seg_json)}개 세그먼트")
        
        # 매칭 실행
        matches = keyword_matching(
            seg_json=seg_json,
            slide_json=slide_json,
            threshold=0.1
        )

        # 결과 파일 저장
        output_path = Path("data/keyword_matching/segment_slide_matches.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n=== 매칭 완료 – 결과가 {output_path}에 저장되었습니다 ===")
        
    except Exception as e:
        print(f"\n오류 발생: {str(e)}")
        import sys
        sys.exit(1)

if __name__ == "__main__":
    main()