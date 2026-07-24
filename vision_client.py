from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

DEFAULT_TIMEOUT_SECONDS = 25.0


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name) or default)
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


DEFAULT_MAX_TOKENS = _env_int("VISION_MAX_TOKENS", 280, 120, 700)
DEFAULT_CANDIDATE_LIMIT = _env_int("VISION_CANDIDATE_LIMIT", 3, 1, 5)
DEFAULT_CATALOG_LIMIT = _env_int("VISION_CATALOG_LIMIT", 80, 10, 200)


@dataclass(frozen=True)
class VisionSettings:
    provider: str
    api_key: str
    endpoint: str
    model: str

    @property
    def is_configured(self) -> bool:
        return self.provider.lower() == "nvidia" and bool(self.api_key and self.endpoint and self.model)


class VisionAPIError(Exception):
    def __init__(self, kind: str, user_message: str):
        super().__init__(user_message)
        self.kind = kind
        self.user_message = user_message


def get_vision_settings() -> VisionSettings:
    return VisionSettings(
        provider=os.getenv("VISION_API_PROVIDER") or "mock",
        api_key=os.getenv("VISION_API_KEY") or "",
        endpoint=os.getenv("VISION_API_ENDPOINT") or "",
        model=os.getenv("VISION_MODEL") or "",
    )


def is_vision_configured() -> bool:
    return get_vision_settings().is_configured


def _catalog_prompt(catalog_options: Optional[list[dict[str, Any]]]) -> str:
    if not catalog_options:
        return ""
    lines = []
    for item in catalog_options[:DEFAULT_CATALOG_LIMIT]:
        aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
        alias_text = ", ".join(str(alias) for alias in aliases[:4] if alias)
        line = f"- {item.get('id')} | ko: {item.get('nameKo')} | en: {item.get('nameEn') or ''}"
        if alias_text:
            line += f" | aliases: {alias_text}"
        lines.append(line)
    return (
        "다음 catalog 안에서만 후보를 선택하세요. 사진과 맞는 항목이 없으면 candidates를 빈 배열로 반환하세요. "
        "반드시 catalog의 id를 gameId에 그대로 넣으세요.\n"
        + "\n".join(lines)
    )


def build_nvidia_payload(
    image_bytes: bytes,
    content_type: str,
    hint: Optional[str],
    model: str,
    catalog_options: Optional[list[dict[str, Any]]] = None,
    mode: str = "catalog",
) -> dict[str, Any]:
    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    safe_content_type = content_type if content_type.startswith("image/") else "application/octet-stream"
    hint_text = hint.strip() if hint else ""
    if mode == "ocr":
        user_text = (
            "사진 속 보드게임 박스에서 가장 크게 보이는 제목 글자만 OCR로 읽어 주세요. "
            "게임을 추측하지 말고, 커버 그림이나 색상보다 실제 글자 모양을 우선하세요. "
            "한국어 한글 제목, 영어 제목, 로고 주변 텍스트를 가능한 그대로 반환하세요."
        )
        if hint_text:
            user_text += f" 참고 힌트: {hint_text}"
    else:
        user_text = (
            "사진 속 보드게임 후보를 식별해 주세요. 먼저 박스에서 가장 크게 보이는 제목 글자를 정확히 읽고, "
            "그 다음 보드게임 DB와 매칭할 수 있도록 한국어 이름과 영어 이름을 짧게 추정해 주세요."
        )
        if hint_text:
            user_text += f" 사용자가 입력한 힌트: {hint_text}"
        catalog_text = _catalog_prompt(catalog_options)
        if catalog_text:
            user_text += "\n\n" + catalog_text

    if mode == "ocr":
        system_text = (
            "You perform OCR for board game box photos. Return JSON only. "
            "Transcribe the largest visible title text exactly, especially Korean Hangul. "
            "Do not identify the game from artwork, colors, theme, gems, or components. "
            "Return at most 3 text candidates with visibleText, confidence, and short evidence. "
            "Use this schema: {\"candidates\":[{\"visibleText\":\"스플렌더\","
            "\"confidence\":0.86,\"evidence\":\"largest title text\"}],"
            "\"needsRetake\":false,\"message\":\"제목 글자를 읽었어요.\"}"
        )
    else:
        system_text = (
            "You identify board games from photos. Return JSON only. "
            "Use an OCR-first process: first transcribe the largest visible title text exactly, "
            "especially Korean Hangul letters, then identify the board game. "
            "Do not infer from theme, colors, gems, components, or cover art before reading the title. "
            "Do not invent unknown games. Lower confidence when uncertain. "
            "If a catalog is provided, choose only catalog games and copy gameId exactly. "
            "If the visible title resembles a catalog Korean name, English name, or alias, prefer that catalog game. "
            f"Return at most {DEFAULT_CANDIDATE_LIMIT} candidates with gameId, visibleText, name, nameKo, confidence, and short evidence. "
            "Use this schema: {\"candidates\":[{\"gameId\":\"splendor\",\"visibleText\":\"스플렌더\","
            "\"name\":\"Splendor\",\"nameKo\":\"스플렌더\",\"confidence\":0.86,"
            "\"evidence\":\"largest title text matches catalog\"}],"
            "\"needsRetake\":false,\"message\":\"가장 가능성이 높은 후보를 찾았어요.\"}"
        )

    return {
        "model": model,
        "temperature": 0 if mode == "ocr" else 0.1,
        "max_tokens": min(DEFAULT_MAX_TOKENS, 220) if mode == "ocr" else DEFAULT_MAX_TOKENS,
        "messages": [
            {
                "role": "system",
                "content": system_text,
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": f"data:{safe_content_type};base64,{encoded_image}"}},
                ],
            },
        ],
    }


def _classify_status(status_code: int) -> str:
    if status_code in {401, 403}:
        return "auth"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "upstream"
    return "bad_request"


async def recognize_boardgame_image(
    image_bytes: bytes,
    content_type: str,
    hint: str | None = None,
    catalog_options: Optional[list[dict[str, Any]]] = None,
    mode: str = "catalog",
) -> dict[str, Any]:
    settings = get_vision_settings()
    if not settings.is_configured:
        raise VisionAPIError("configuration", "이미지 인식 설정이 준비되지 않았습니다.")

    payload = build_nvidia_payload(image_bytes, content_type, hint, settings.model, catalog_options, mode)
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.endpoint, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise VisionAPIError("timeout", "이미지 인식 응답이 지연되고 있습니다.") from exc
    except httpx.RequestError as exc:
        raise VisionAPIError("network", "이미지 인식 서비스에 연결하지 못했습니다.") from exc

    if response.status_code >= 400:
        raise VisionAPIError(_classify_status(response.status_code), "이미지 인식 서비스를 잠시 사용할 수 없습니다.")

    try:
        body = response.json()
    except ValueError as exc:
        raise VisionAPIError("invalid_response", "이미지 인식 응답을 해석하지 못했습니다.") from exc

    content = ""
    choices = body.get("choices") if isinstance(body, dict) else None
    if choices and isinstance(choices, list):
        first = choices[0] if choices else {}
        message = first.get("message") if isinstance(first, dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""

    return {
        "provider": settings.provider,
        "content": content,
        "raw": body,
    }
