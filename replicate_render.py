import argparse
import base64
import json
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import replicate
import requests
from dotenv import load_dotenv


load_dotenv()


REPLICATE_MODEL = "black-forest-labs/flux-kontext-pro"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")


IMAGE_DATA_URL_KEYS = ("imageDataUrl", "image_data_url", "image")
IMAGE_URL_KEYS = ("imageUrl", "image_url", "photoUrl", "photo_url")
IMAGE_PATH_KEYS = ("imagePath", "image_path", "localImagePath", "local_image_path")
FACE_ANALYSIS_KEYS = ("faceAnalysis", "face_analysis", "analysis", "face")
SUGGESTION_KEYS = (
    "ollamaSuggestion",
    "ollama_suggestion",
    "textSuggestion",
    "text_suggestion",
    "suggestion",
)


def load_frontend_package(path: str) -> dict[str, Any]:
    package_path = Path(path)
    if not package_path.exists():
        raise FileNotFoundError(f"Frontend data package not found: {package_path}")
    with package_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("Frontend data package must be a JSON object.")
    return data


def first_string(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def first_dict(data: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return {}


def file_to_data_url(path: str) -> str:
    image_path = Path(path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")
    content_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def url_to_data_url(url: str) -> str:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
    encoded = base64.b64encode(response.content).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def image_from_frontend_package(frontend_package: dict[str, Any]) -> str:
    image_data_url = first_string(frontend_package, IMAGE_DATA_URL_KEYS)
    if image_data_url:
        if not image_data_url.startswith("data:"):
            raise ValueError("imageDataUrl/image must be a data URL when provided directly.")
        return image_data_url

    image_url = first_string(frontend_package, IMAGE_URL_KEYS)
    if image_url:
        return url_to_data_url(image_url)

    image_path = first_string(frontend_package, IMAGE_PATH_KEYS)
    if image_path:
        return file_to_data_url(image_path)

    raise ValueError(
        "Frontend data package must include imageDataUrl, imageUrl, or imagePath."
    )


def face_analysis_from_frontend_package(frontend_package: dict[str, Any]) -> dict[str, Any]:
    return first_dict(frontend_package, FACE_ANALYSIS_KEYS)


def suggestion_from_frontend_package(frontend_package: dict[str, Any]) -> str:
    return first_string(frontend_package, SUGGESTION_KEYS)


def style_from_frontend_package(frontend_package: dict[str, Any]) -> str:
    return first_string(frontend_package, ("style", "styleHint", "style_hint", "makeupStyle", "makeup_style"))


def make_ollama_request_prompt(face_analysis: dict[str, Any], style_hint: str) -> str:
    return (
        "You are a professional makeup recommendation assistant. "
        "Create a concise English makeup suggestion for image generation. "
        "Use the face analysis data and requested style. "
        "Preserve the person's original identity, facial structure, age, ethnicity, and expression. "
        "Return only the makeup suggestion text.\n\n"
        f"Face analysis:\n{json.dumps(face_analysis, ensure_ascii=False, indent=2)}\n\n"
        f"Requested style:\n{style_hint or 'natural flattering makeup'}"
    )


def generate_ollama_suggestion(face_analysis: dict[str, Any], style_hint: str) -> str:
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": make_ollama_request_prompt(face_analysis, style_hint),
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    suggestion = response.json().get("response", "").strip()
    if not suggestion:
        raise RuntimeError("Ollama returned an empty suggestion.")
    return suggestion


def compact_face_context(face_analysis: dict[str, Any]) -> str:
    important_keys = (
        "faceShape", "face_shape",
        "skinTone", "skin_tone",
        "eyeShape", "eye_shape",
        "lipShape", "lip_shape",
        "skinType", "skin_type",
        "features",
    )
    parts: list[str] = []
    for key in important_keys:
        value = face_analysis.get(key)
        if value:
            label = key.replace("_", " ")
            parts.append(f"{label}: {value}")
    return ", ".join(parts)


def build_render_prompt(frontend_package: dict[str, Any], face_analysis: dict[str, Any], suggestion: str) -> str:
    explicit_prompt = first_string(frontend_package, ("renderPrompt", "render_prompt", "imagePrompt", "image_prompt"))
    if explicit_prompt:
        return explicit_prompt

    style_hint = style_from_frontend_package(frontend_package)
    face_context = compact_face_context(face_analysis)

    face_desc = f"This person has {face_context}." if face_context else ""
    makeup_detail = ", ".join(filter(None, [style_hint, suggestion[:300]]))
    ollama_line = f"Makeup reference (translated from advisor): {suggestion[:300].strip()}." if suggestion else ""
    parts = [
        "Apply makeup to this exact person.",
        face_desc,
        f"Only add the following makeup: {makeup_detail or 'natural everyday makeup'}.",
        ollama_line,
        "Do not change anything else.",
        "Keep this person's face shape, eye shape, nose, lips, skin tone, skin texture, pores, wrinkles, hair, body, clothing, background, lighting, camera angle, and expression completely identical to the original photo.",
        "This must look like the same person wearing makeup, not a different person.",
    ]
    return " ".join(p for p in parts if p)


def call_replicate_render(image_data_url: str, prompt: str) -> dict[str, Any]:
    output = replicate.run(
        REPLICATE_MODEL,
        input={
            "prompt": prompt,
            "input_image": image_data_url,
            "output_format": "jpg",
            "output_quality": 90,
            "guidance": 2.5,
        },
    )

    # replicate SDK 1.x: output.url 是字串屬性；舊版才是 callable
    if hasattr(output, "url"):
        url_val = output.url
        after_image_url = url_val() if callable(url_val) else str(url_val)
    elif isinstance(output, list):
        after_image_url = str(output[0])
    else:
        after_image_url = str(output)

    return {
        "status": "completed",
        "afterImageUrl": after_image_url,
        "model": REPLICATE_MODEL,
    }


def render_from_frontend_package(frontend_package: dict[str, Any]) -> dict[str, Any]:
    image_data_url = image_from_frontend_package(frontend_package)
    face_analysis = face_analysis_from_frontend_package(frontend_package)
    style_hint = style_from_frontend_package(frontend_package)
    suggestion = suggestion_from_frontend_package(frontend_package)

    if not suggestion:
        suggestion = generate_ollama_suggestion(face_analysis, style_hint)

    render_prompt = build_render_prompt(frontend_package, face_analysis, suggestion)
    render_result = call_replicate_render(image_data_url, render_prompt)

    return {
        "status": "completed",
        "requestId": frontend_package.get("requestId") or frontend_package.get("request_id"),
        "userId": frontend_package.get("userId") or frontend_package.get("user_id"),
        "sourcePackageId": frontend_package.get("packageId") or frontend_package.get("package_id") or frontend_package.get("id"),
        "afterImageUrl": render_result["afterImageUrl"],
        "renderPrompt": render_prompt,
        "ollamaSuggestion": suggestion,
        "faceAnalysis": face_analysis,
        "model": REPLICATE_MODEL,
        "renderBaseUrl": "replicate",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render makeup from the frontend data package using flux-kontext-pro."
    )
    parser.add_argument("package", help="Path to frontend JSON data package.")
    parser.add_argument("--output", help="Optional path to write the output JSON package.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frontend_package = load_frontend_package(args.package)
    output_package = render_from_frontend_package(frontend_package)

    output_json = json.dumps(output_package, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
    print(output_json)


if __name__ == "__main__":
    main()
