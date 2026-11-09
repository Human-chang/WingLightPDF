# -*- coding: utf-8 -*-
"""
Windows 內建 OCR (Windows.Media.Ocr) 封裝 — 輕量版使用，不需打包任何辨識模型。
1. 優先使用繁體中文（台灣）辨識語言；系統未安裝時改用使用者設定的語言
2. 回傳格式與 RapidOCR 相同：[(四角像素座標 [[x,y]...], 文字, 信心值), ...]
   （Windows OCR 不提供信心值，固定為 1.0）
"""

from __future__ import annotations
import asyncio
import io
from typing import List, Tuple

PREFERRED_LANGUAGES = ("zh-Hant-TW", "zh-Hant", "zh-TW")

INSTALL_HINT = (
    "此電腦沒有安裝 Windows OCR 辨識語言。\n"
    "請到「設定 → 時間與語言 → 語言與地區 → 中文(台灣) → 語言選項」安裝「光學字元辨識」後再試一次。"
)


def _is_ascii_word_char(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _join_words(words) -> str:
    """Windows OCR 會把中文逐字拆成獨立 word，只在英數字之間補空白"""
    out = ""
    for w in words:
        t = w.text
        if out and t and _is_ascii_word_char(out[-1]) and _is_ascii_word_char(t[0]):
            out += " "
        out += t
    return out


class WindowsOCR:
    def __init__(self) -> None:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        engine = None
        for tag in PREFERRED_LANGUAGES:
            lang = Language(tag)
            if OcrEngine.is_language_supported(lang):
                engine = OcrEngine.try_create_from_language(lang)
                if engine is not None:
                    break
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError(INSTALL_HINT)

        self._engine = engine
        self.language_tag: str = engine.recognizer_language.language_tag
        self.engine_name = f"Windows OCR ({self.language_tag})"
        self._max_dim: int = OcrEngine.max_image_dimension

    def __call__(self, img_np) -> List[Tuple[list, str, float]]:
        return asyncio.run(self._recognize(img_np))

    async def _recognize(self, img_np) -> List[Tuple[list, str, float]]:
        from PIL import Image
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        img = Image.fromarray(img_np)
        scale = 1.0
        if max(img.size) > self._max_dim:
            scale = self._max_dim / max(img.size)
            img = img.resize(
                (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                Image.Resampling.LANCZOS,
            )
        png = io.BytesIO()
        img.save(png, "PNG", compress_level=1)

        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(png.getvalue())
        await writer.store_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await self._engine.recognize_async(bitmap)

        items: List[Tuple[list, str, float]] = []
        for line in result.lines:
            words = list(line.words)
            text = _join_words(words)
            if not words or not text.strip():
                continue
            rects = [w.bounding_rect for w in words]
            x0 = min(r.x for r in rects) / scale
            y0 = min(r.y for r in rects) / scale
            x1 = max(r.x + r.width for r in rects) / scale
            y1 = max(r.y + r.height for r in rects) / scale
            items.append(([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], text, 1.0))
        return items
