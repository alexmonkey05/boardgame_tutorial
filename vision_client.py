from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

DEFAULT_TIMEOUT_SECONDS = 25.0


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


def build_nvidia_payload(image_bytes: bytes, content_type: str, hint: Optional[str], model: str) -> dict[str, Any]:
    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    safe_content_type = content_type if content_type.startswith("image/") else "application/octet-stream"
    hint_text = hint.strip() if hint else ""
    user_text = (
        "사진 속 보드게임 후보를 식별해 주세요. "
        "카페 보유 게임 DB와 매칭할 수 있도록 한국어 이름과 영어 이름을 모두 추정해 주세요."
    )
    if hint_text:
        user_text += f" 사용자가 입력한 힌트: {hint_text}"

    return {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 700,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You identify board games from photos. Return JSON only. "
                    "Look for board game boxes, titles, logos, components, and visual evidence. "
                    "Do not invent unknown games. Lower confidence when uncertain. "
                    "Return at most 5 candidates with name, nameKo, confidence, and evidence. "
                    "Use this schema: {\"candidates\":[{\"name\":\"Splendor\",\"nameKo\":\"스플렌더\","
                    "\"confidence\":0.86,\"evidence\":\"box title and gem tokens\"}],"
                    "\"needsRetake\":false,\"message\":\"가장 가능성이 높은 후보를 찾았어요.\"}"
                ),
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
) -> dict[str, Any]:
    settings = get_vision_settings()
    if not settings.is_configured:
        raise VisionAPIError("configuration", "이미지 인식 설정이 준비되지 않았습니다.")

    payload = build_nvidia_payload(image_bytes, content_type, hint, settings.model)
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
