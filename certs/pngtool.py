"""纯标准库 PNG 工具: 解析元数据、像素级脱敏、重建派生图。

约束: 仅支持 8-bit、非隔行、RGB/RGBA(颜色类型 2/6)的 PNG,
足以覆盖证书扫描件常见导出格式; 不支持的格式抛出 PngError,
由上层记录 IMAGE_FAILED 事件而不是崩溃。

隐私原则:
  - 原件(含 EXIF/tEXt 等全部元数据)只写入私密目录;
  - 派生图抹除全部文本块, 并对识别出的 PII 区域做像素级遮盖。
"""
from __future__ import annotations

import json
import re
import struct
import zlib

PNG_SIG = b"\x89PNG\r\n\x1a\n"


class PngError(Exception):
    """PNG 解析/处理失败(损坏或格式不支持)。"""


# ---------------------------------------------------------------- 基础编解码

def _chunks(data: bytes):
    if len(data) < 8 or data[:8] != PNG_SIG:
        raise PngError("不是有效的 PNG 文件(签名不匹配)")
    pos = 8
    while pos + 12 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        cdata = data[pos + 8:pos + 8 + length]
        crc = data[pos + 8 + length:pos + 12 + length]
        if len(cdata) != length or len(crc) != 4:
            raise PngError("PNG 块长度损坏")
        expect = zlib.crc32(ctype + cdata) & 0xFFFFFFFF
        (got,) = struct.unpack(">I", crc)
        if expect != got:
            raise PngError(f"PNG 块 {ctype!r} CRC 校验失败")
        yield ctype, cdata
        pos += 12 + length
        if ctype == b"IEND":
            return
    raise PngError("PNG 缺少 IEND 结束块")


def _pack_chunk(ctype: bytes, cdata: bytes) -> bytes:
    return (struct.pack(">I", len(cdata)) + ctype + cdata
            + struct.pack(">I", zlib.crc32(ctype + cdata) & 0xFFFFFFFF))


def read_png(data: bytes) -> dict:
    """解析 PNG -> {width,height,color_type,bit_depth,interlace,texts,idat}。"""
    ihdr = None
    texts: dict[str, str] = {}
    idat = bytearray()
    for ctype, cdata in _chunks(data):
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", cdata)
        elif ctype == b"IDAT":
            idat += cdata
        elif ctype == b"tEXt":
            key, _, val = cdata.partition(b"\x00")
            texts[key.decode("latin-1")] = val.decode("latin-1")
        elif ctype == b"zTXt":
            key, _, rest = cdata.partition(b"\x00")
            if rest and rest[0] == 0:
                texts[key.decode("latin-1")] = zlib.decompress(rest[1:]).decode("utf-8", "replace")
        elif ctype == b"iTXt":
            key, _, rest = cdata.partition(b"\x00")
            if len(rest) >= 2:
                compressed = rest[0] == 1
                body = rest[2:]
                # 跳过语言标记与译文关键字两个 NUL 终止字段
                _lang, _, body = body.partition(b"\x00")
                _trans, _, body = body.partition(b"\x00")
                if compressed:
                    body = zlib.decompress(body)
                texts[key.decode("latin-1")] = body.decode("utf-8", "replace")
    if ihdr is None:
        raise PngError("PNG 缺少 IHDR")
    width, height, bit_depth, color_type, _comp, _filt, interlace = ihdr
    return {
        "width": width, "height": height, "bit_depth": bit_depth,
        "color_type": color_type, "interlace": interlace,
        "texts": texts, "idat": bytes(idat),
    }


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_pixels(meta: dict) -> tuple[bytearray, int]:
    """把 IDAT 解压并还原滤镜 -> (像素字节, 每像素字节数 bpp)。"""
    if meta["bit_depth"] != 8 or meta["interlace"] != 0 or meta["color_type"] not in (2, 6):
        raise PngError(
            f"不支持的 PNG 格式(bit_depth={meta['bit_depth']}, "
            f"color_type={meta['color_type']}, interlace={meta['interlace']})")
    bpp = 3 if meta["color_type"] == 2 else 4
    width, height = meta["width"], meta["height"]
    stride = width * bpp
    try:
        raw = zlib.decompress(meta["idat"])
    except zlib.error as exc:
        raise PngError(f"IDAT 解压失败: {exc}") from exc
    if len(raw) != (stride + 1) * height:
        raise PngError("IDAT 数据长度与图像尺寸不符")
    out = bytearray(width * height * bpp)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        f = raw[pos]; pos += 1
        line = bytearray(raw[pos:pos + stride]); pos += stride
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(a, b, c)) & 0xFF
        elif f != 0:
            raise PngError(f"未知滤镜类型 {f}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out, bpp


def encode_png(width: int, height: int, color_type: int,
               pixels: bytes | bytearray) -> bytes:
    """以 filter 0 重新编码(派生图不携带任何文本元数据)。"""
    bpp = 3 if color_type == 2 else 4
    stride = width * bpp
    if len(pixels) != stride * height:
        raise PngError("像素数据长度与尺寸不符")
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += pixels[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (PNG_SIG + _pack_chunk(b"IHDR", ihdr)
            + _pack_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _pack_chunk(b"IEND", b""))


# ---------------------------------------------------------------- PII 识别与脱敏

RE_ID_CARD = re.compile(r"\b\d{17}[\dXx]\b")                      # 18 位身份证号
RE_CERT_NO = re.compile(r"(?:证书编号|证书号|编号|Certificate\s*No\.?|Cert\s*No\.?|NO\.?)"
                        r"\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-]{3,31})")
RE_HOLDER = re.compile(r"(?:姓名|持证人|Name)\s*[:：]\s*([一-龥A-Za-z·]{2,20})")


def extract_metadata(texts: dict[str, str]) -> dict:
    """从图片文本元数据(扫描件 OCR 结果/EXIF 备注)中识别个人编号等。

    真实部署中 OCR 由引擎完成; 这里以 tEXt 块 `ocr_text` 作为识别输入,
    提取逻辑(正则规则)与生产一致。
    """
    ocr_text = texts.get("ocr_text", "")
    id_cards = sorted(set(RE_ID_CARD.findall(ocr_text)))
    cert_no = None
    m = RE_CERT_NO.search(ocr_text)
    if m:
        cert_no = m.group(1)
    holder = None
    m = RE_HOLDER.search(ocr_text)
    if m:
        holder = m.group(1)
    boxes: list[dict] = []
    if "pii_boxes" in texts:
        try:
            boxes = [b for b in json.loads(texts["pii_boxes"])
                     if isinstance(b, dict) and "x" in b and "y" in b]
        except (ValueError, TypeError):
            boxes = []
    return {
        "personal_ids": id_cards,          # 个人编号(身份证号等)
        "certificate_no": cert_no,         # 证书编号
        "holder_name": holder,             # 持证人姓名
        "ocr_text_len": len(ocr_text),
        "text_keys": sorted(texts.keys()), # 原件携带的元数据键
        "pii_boxes": boxes,
    }


def redact(meta: dict, pixels: bytearray, bpp: int,
           boxes: list[dict]) -> list[dict]:
    """对指定区域做像素级遮盖(纯黑), 返回实际应用的区域列表。"""
    width, height = meta["width"], meta["height"]
    applied = []
    for b in boxes:
        x0 = max(0, int(b.get("x", 0)))
        y0 = max(0, int(b.get("y", 0)))
        x1 = min(width, x0 + max(0, int(b.get("w", 0))))
        y1 = min(height, y0 + max(0, int(b.get("h", 0))))
        if x1 <= x0 or y1 <= y0:
            continue
        for y in range(y0, y1):
            row = y * width * bpp
            for x in range(x0, x1):
                i = row + x * bpp
                for c in range(bpp):
                    pixels[i + c] = 0 if c < 3 else 255  # RGB 黑, alpha 不透明
        applied.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
    return applied


def make_derived(original: bytes) -> tuple[bytes, dict, list[dict]]:
    """原件 -> (派生图字节, 识别出的元数据, 实际脱敏区域)。

    派生图: 抹除全部文本元数据 + PII 区域像素遮盖。
    """
    meta = read_png(original)
    extracted = extract_metadata(meta["texts"])
    pixels, bpp = decode_pixels(meta)
    applied = redact(meta, pixels, bpp, extracted["pii_boxes"])
    derived = encode_png(meta["width"], meta["height"], meta["color_type"], pixels)
    return derived, extracted, applied


# ---------------------------------------------------------------- 测试辅助

def make_png(width: int, height: int, rgb=(200, 200, 200),
             texts: dict[str, str] | None = None,
             color_type: int = 2) -> bytes:
    """生成测试用 PNG(可携带 tEXt 元数据)。"""
    bpp = 3 if color_type == 2 else 4
    px = bytearray()
    for _y in range(height):
        for _x in range(width):
            px += bytes(rgb) + (b"\xff" if bpp == 4 else b"")
    out = bytearray(PNG_SIG)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    out += _pack_chunk(b"IHDR", ihdr)
    for k, v in (texts or {}).items():
        try:
            v.encode("latin-1")
            out += _pack_chunk(b"tEXt", k.encode("latin-1") + b"\x00" + v.encode("latin-1"))
        except UnicodeEncodeError:
            # 非 latin-1 文本走 iTXt(UTF-8, 未压缩)
            body = (k.encode("latin-1") + b"\x00" + b"\x00\x00"
                    + b"\x00" + b"\x00" + v.encode("utf-8"))
            out += _pack_chunk(b"iTXt", body)
    raw = bytearray()
    stride = width * bpp
    for y in range(height):
        raw.append(0)
        raw += px[y * stride:(y + 1) * stride]
    out += _pack_chunk(b"IDAT", zlib.compress(bytes(raw)))
    out += _pack_chunk(b"IEND", b"")
    return bytes(out)
