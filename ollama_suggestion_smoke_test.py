from Ollama_suggestion import (
    SuggestRequest,
    build_prompt,
    build_render_prompt,
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
    render_prompt = build_render_prompt(payload)

    required_prompt_words = ["整體妝容方向", "臉型", "眼型", "唇妝建議"]
    missing_prompt_words = [word for word in required_prompt_words if word not in prompt]
    if missing_prompt_words:
        raise RuntimeError(f"prompt missing words: {missing_prompt_words}")

    required_render_words = ["English rendering prompt", "Preserve the person's identity", "makeup only"]
    missing_render_words = [word for word in required_render_words if word not in render_prompt]
    if missing_render_words:
        raise RuntimeError(f"render prompt missing words: {missing_render_words}")
    print("ollama suggestion smoke test passed")


if __name__ == "__main__":
    main()
