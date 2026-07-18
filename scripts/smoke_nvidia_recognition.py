from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vision_client import VisionAPIError, recognize_boardgame_image


def write_test_png(path: Path) -> None:
    width, height = 360, 220
    font = {
        "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
        "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
        "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
        "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
        "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
        "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
        "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
        "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    }
    pixels = []
    for y in range(height):
        row = []
        for x in range(width):
            if 18 < x < width - 18 and 18 < y < height - 18:
                color = (44, 82, 132)
            else:
                color = (238, 232, 206)
            if 64 < x < 296 and 60 < y < 134:
                color = (245, 236, 184)
            row.append(color)
        pixels.append(row)

    x0, y0, scale = 48, 82, 8
    cursor = x0
    for letter in "SPLENDOR":
        pattern = font[letter]
        for py, line in enumerate(pattern):
            for px, bit in enumerate(line):
                if bit == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            x = cursor + px * scale + dx
                            y = y0 + py * scale + dy
                            if 0 <= x < width and 0 <= y < height:
                                pixels[y][x] = (32, 43, 64)
        cursor += 6 * scale

    for cx, cy, color in [
        (98, 165, (210, 55, 68)),
        (146, 165, (52, 145, 84)),
        (194, 165, (64, 108, 200)),
        (242, 165, (230, 174, 55)),
    ]:
        for y in range(cy - 15, cy + 16):
            for x in range(cx - 15, cx + 16):
                if (x - cx) ** 2 + (y - cy) ** 2 <= 225 and 0 <= x < width and 0 <= y < height:
                    pixels[y][x] = color

    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            r, g, b = pixels[y][x]
            row.extend([r, g, b])
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    raw = b"".join(rows)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


async def direct_vision_check(image_path: Path) -> dict[str, object]:
    try:
        image_bytes = image_path.read_bytes()
        response = await recognize_boardgame_image(image_bytes, "image/png", "splendor")
        content = response.get("content") or ""
        return {"ok": True, "contentLength": len(content)}
    except VisionAPIError as exc:
        return {"ok": False, "errorKind": exc.kind}


def main() -> None:
    root = ROOT
    python_path = root / ".venv" / "Scripts" / "python.exe"
    image_path = Path(tempfile.gettempdir()) / "splendor_smoke_boardgame.png"
    write_test_png(image_path)

    import asyncio

    direct_summary = asyncio.run(direct_vision_check(image_path))
    proc = subprocess.Popen(
        [str(python_path), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(5)
        with image_path.open("rb") as image_file:
            files = {"image": (image_path.name, image_file, "image/png")}
            response = httpx.post(
                "http://127.0.0.1:8000/recognitions?hint=splendor",
                files=files,
                timeout=60,
            )
        body = response.json()
        top = body.get("topCandidate") or {}
        game = top.get("game") or {}
        summary = {
            "directVision": direct_summary,
            "statusCode": response.status_code,
            "externalUsed": body.get("externalProcessing", {}).get("used"),
            "provider": body.get("externalProcessing", {}).get("provider"),
            "topGameId": game.get("id"),
            "candidateCount": len(body.get("candidates", [])),
            "unmatchedCount": len(body.get("unmatchedCandidates", [])),
            "needsRetake": body.get("needsRetake"),
        }
        print(json.dumps(summary, ensure_ascii=False))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            image_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
