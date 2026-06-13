from Ollama_suggestion import SuggestRequest, build_prompt, fallback_suggestion


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
    suggestion = fallback_suggestion(payload)

    required_prompt_words = ["整體妝容方向", "臉型", "眼型", "唇妝建議"]
    missing_prompt_words = [word for word in required_prompt_words if word not in prompt]
    if missing_prompt_words:
        raise RuntimeError(f"prompt missing words: {missing_prompt_words}")

    required_suggestion_words = ["日常自然妝", "底妝", "眼妝"]
    missing_suggestion_words = [word for word in required_suggestion_words if word not in suggestion]
    if missing_suggestion_words:
        raise RuntimeError(f"fallback suggestion missing words: {missing_suggestion_words}")

    print("ollama suggestion smoke test passed")


if __name__ == "__main__":
    main()
