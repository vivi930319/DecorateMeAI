from Ollama_suggestion import (
    SuggestRequest,
    build_prompt,
)


def main():
    payload = SuggestRequest(
        style="日常自然妝",
        faceAnalysis={
            "faceShape": "oval",
            "browShape": "curved",
            "eyeShape": "peach_blossom",
            "noseFront": "standard",
            "lipShape": "smile",
            "skinTone": {"season": "spring", "level": "白皙自然色"},
        },
    )

    prompt = build_prompt(payload)

    required_prompt_words = [
        "整體妝容方向",
        "底妝建議",
        "眉眼妝建議",
        "唇妝建議",
        "避免事項",
        "總結與建議",
        "臉型",
        "眼型",
    ]
    missing_prompt_words = [word for word in required_prompt_words if word not in prompt]
    if missing_prompt_words:
        raise RuntimeError(f"prompt missing words: {missing_prompt_words}")
    print("ollama suggestion smoke test passed")


if __name__ == "__main__":
    main()
