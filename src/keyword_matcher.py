#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
1) 세그먼트·슬라이드 키워드 추출
2) IPA 기반 발음 유사도 비교 (Korean ↔ English)
   - 한국어: g2pk → epitran
   - 영어: eng_to_ipa
필수 패키지
    pip install konlpy g2pk epitran panphon python-Levenshtein eng_to_ipa regex
"""

import json, re
from pathlib import Path
from typing import Dict, List
from collections import defaultdict

# ---------- 1. G2P & IPA ----------
from g2pk import G2p
g2p = G2p()

import epitran
epi_kr = epitran.Epitran('kor-Hang')

def ipa_korean(word: str) -> str:
    """한국어 → 발음 → IPA"""
    pronounced = g2p(word)
    return epi_kr.transliterate(pronounced)

def ipa_english(word: str) -> str:
    """영어 → IPA"""
    clean = re.sub(r"[^A-Za-z]", "", word)  # 숫자·특수문자 제거
    if not clean:
        return ""
    import eng_to_ipa as e2i
    return e2i.convert(clean.lower()) or ""

# ---------- 2. 발음 거리 ----------
from panphon.distance import Distance
dst = Distance()

def phoneme_similarity(p1: str, p2: str) -> float:
    """IPA 기반 발음 유사도 계산 (0~1, 1이 유사)"""
    if not p1 or not p2:
        return 0.0
    dist = dst.weighted_feature_edit_distance(p1, p2)
    similarity = max(0.0, 1.0 - dist / 15.0)  # 15는 대략적 정규화 상한값
    return similarity

def compare_words(korean_words: List[str], english_words: List[str], threshold: float = 0.03) -> List[dict]:
    """한국어-영어 단어 비교"""
    matches = []
    
    for kr_word in korean_words:
        kr_ipa = ipa_korean(kr_word)
        if not kr_ipa:
            continue
            
        word_matches = []
        for en_word in english_words:
            en_ipa = ipa_english(en_word)
            if not en_ipa:
                continue
                
            score = phoneme_similarity(kr_ipa, en_ipa)
            if score >= threshold:
                word_matches.append({
                    "korean_word": kr_word,
                    "english_word": en_word,
                    "score": round(score, 2)
                })
        
        if word_matches:
            matches.extend(word_matches)
    
    return sorted(matches, key=lambda x: x["score"], reverse=True)

def main():
    # 기본 경로 설정
    segment_path = Path("data/word_list/segment_word_list.json")
    image_path = Path("data/word_list/image_word_list.json")
    threshold = 0.01
    
    try:
        print("\n=== 데이터 로드 시작 ===")
        # 데이터 로드
        segment_data = json.loads(segment_path.read_text(encoding="utf-8"))
        image_data = json.loads(image_path.read_text(encoding="utf-8"))
        
        # 매칭할 키워드 추출
        korean_words = segment_data["match_keywords"]
        english_words = []
        for slide_words in image_data.values():
            english_words.extend(slide_words)
        english_words = list(set(english_words))  # 중복 제거
        
        print(f"한국어 키워드: {len(korean_words)}개")
        print(f"영어 키워드: {len(english_words)}개")
        print(f"threshold: {threshold}")
        
        # 단어 비교
        matches = compare_words(korean_words, english_words, threshold)
        
        # 결과 출력
        print("\n=== 매칭 결과 ===")
        for match in matches:
            print(f"한국어: {match['korean_word']} ↔ 영어: {match['english_word']} (유사도: {match['score']})")
        
        print(f"\n총 {len(matches)}개의 매칭 결과가 발견되었습니다.")
        
    except Exception as e:
        print(f"\n오류 발생: {str(e)}")
        import sys
        sys.exit(1)

if __name__ == "__main__":
    main()
