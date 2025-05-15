#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Segment–Slide Mapper

Maps lecture speech segments (STT) to their corresponding lecture slides using
keyword‑based semantic similarity with an OpenAI model.

Usage (default values shown):
    main(
        skip_stt=True,                 # use cached STT result instead of re‑running STT/segmentation
        skip_image_captioning=True,    # use cached image‑captioning result instead of re‑running captioning
        slide_window=6,                # how many slides to include before/after the current centre slide
        max_segment_length=2000,       # max characters per request after merging short segments
        min_segment_length=500         # if the final batch is shorter than this, append it to the previous batch
    )

The script automatically writes the final mapping to
``data/segment_mapping/segment_mapping_<YYYYMMDD_HHMM>.json`` and returns the
in‑memory list of mappings.

Each mapping element is of the form
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
# Environment & client setup
# ----------------------------------------------------------------------------

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://api.openai.com/v1",
)

# ----------------------------------------------------------------------------
# Data‑loading helpers
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

    # Live STT   -------------------------------------------------------------
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
# Transformation & prompt‑building helpers
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


def call_mapping_api(segments_block: str, slide_block: str) -> List[Dict[str, int]]:
    """Send a single mapping request and return the parsed mapping list."""
    user_content = f"""Given the following lecture slides and segments, analyze the content and map each segment to the most relevant slide.\n\nEach slide contains:\n- slide_number\n- title_keywords: core concepts or titles of the slide\n- secondary_keywords: additional specific terms or technical vocabulary mentioned on the slide\n\nSlides:\n{slide_block}\n\nSegments:\n{segments_block}\n\nYour task:\nMatch each segment to the most appropriate slide based on **semantic similarity with title_keywords and secondary_keywords**.\n\nReply ONLY with a JSON array in the following format:\n[\n  {{ \"segment_id\": 9, \"slide_id\": 4 }},\n  ...\n]\n"""

    # ── Debug: print *only* the user message content
    print("\n[DEBUG] ----- USER MESSAGE BEGIN -----")
    print(user_content)
    print("[DEBUG] ----- USER MESSAGE END -----\n")

    messages = [
        {
            "role": "system",
            "content": "You are an assistant that maps lecture segments to their corresponding slides based on content similarity.",
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
# Output helper
# ----------------------------------------------------------------------------

def save_results(mappings: List[Dict[str, int]]) -> str:
    os.makedirs("data/segment_mapping", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"data/segment_mapping/segment_mapping_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mappings, f, ensure_ascii=False, indent=2)
    return path

# ----------------------------------------------------------------------------
# Main driver
# ----------------------------------------------------------------------------

def main(
    skip_stt: bool = True,
    skip_image_captioning: bool = True,
    slide_window: int = 6,
    max_segment_length: int = 2000,
    min_segment_length: int = 500,
) -> List[Dict[str, int]]:
    """End‑to‑end mapping routine. See module docstring for parameter details."""
    # 1. Load data -------------------------------------------------------------------
    segments = load_segments(skip_stt)
    slides = load_slides(skip_image_captioning)

    # 2. Prepare segment messages ----------------------------------------------------
    batches = merge_segments(segments, max_segment_length, min_segment_length)

    # 3. Iteratively call the model --------------------------------------------------
    current_centre = slides[0]["slide_number"] if slides else 1
    all_mappings: List[Dict[str, int]] = []

    for batch in batches:
        relevant_slides = slice_slides(slides, current_centre, slide_window)
        slide_prompt = build_slide_prompt(relevant_slides)
        batch_mappings = call_mapping_api(batch, slide_prompt)
        all_mappings.extend(batch_mappings)

        # Update the centre slide for the next iteration -----------------------------
        if batch_mappings:
            current_centre = max(m["slide_id"] for m in batch_mappings) - 1

    # 4. Sort & persist --------------------------------------------------------------
    all_mappings.sort(key=lambda m: m["segment_id"])
    json_path = save_results(all_mappings)
    print(f"[INFO] Saved mapping to {json_path}")

    return all_mappings


if __name__ == "__main__":
    main()
