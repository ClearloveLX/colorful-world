"""媒体文件类型自动识别（纯标准库实现）。

识别策略：
1. 优先读取文件头，按魔数/容器签名判断真实类型（图片/音频/视频）；
2. 签名无法判断或文件不可读时回退到扩展名；
3. 对 MP4/MOV 这类同容器多用途格式，用 ftyp brand + 扩展名共同判定。

所有函数都不应抛异常：识别失败统一返回 ``unknown``。
"""

import os
from typing import Dict, Optional, Tuple

MEDIA_KIND_IMAGE = "image"
MEDIA_KIND_VIDEO = "video"
MEDIA_KIND_AUDIO = "audio"
MEDIA_KIND_UNKNOWN = "unknown"

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".ico", ".heic", ".heif", ".avif",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".mpeg", ".mpg",
    ".m4v", ".ts", ".m2ts", ".3gp", ".flv",
}
AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".m4b", ".wav", ".flac", ".ogg", ".oga", ".opus",
    ".aac", ".wma", ".aiff", ".aif",
}
# 文件头读取长度：足够覆盖常见容器 brand/格式字段
_HEAD_BYTES = 256

_MIME_BY_FORMAT = {
    # 图片
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
    "tif": "image/tiff", "tiff": "image/tiff", "ico": "image/x-icon",
    "heic": "image/heic", "heif": "image/heif", "avif": "image/avif",
    # 视频
    "mp4": "video/mp4", "mov": "video/quicktime", "mkv": "video/x-matroska",
    "webm": "video/webm", "avi": "video/x-msvideo", "wmv": "video/x-ms-wmv",
    "mpeg": "video/mpeg", "mpg": "video/mpeg", "m4v": "video/x-m4v",
    "ts": "video/mp2t", "m2ts": "video/mp2t", "3gp": "video/3gpp",
    "flv": "video/x-flv",
    # 音频
    "mp3": "audio/mpeg", "m4a": "audio/mp4", "m4b": "audio/mp4",
    "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg",
    "oga": "audio/ogg", "opus": "audio/ogg", "aac": "audio/aac",
    "wma": "audio/x-ms-wma", "aiff": "audio/aiff", "aif": "audio/aiff",
}

_ASF_SIGNATURE = bytes.fromhex("3026B2758E66CF11A6D900AA0062CE6C")


def normalize_extension(path: str) -> str:
    """返回小写且带点的扩展名；无扩展名时返回空字符串。"""
    try:
        return os.path.splitext(str(path))[1].lower()
    except Exception:
        return ""


def format_from_extension(path: str) -> Optional[str]:
    """返回不带点的格式名（jpg/mp4/m4a），无扩展名时返回 None。"""
    ext = normalize_extension(path)
    return ext.lstrip(".") if ext else None


def kind_from_extension(path: str) -> str:
    ext = normalize_extension(path)
    if ext in IMAGE_EXTENSIONS:
        return MEDIA_KIND_IMAGE
    if ext in VIDEO_EXTENSIONS:
        return MEDIA_KIND_VIDEO
    if ext in AUDIO_EXTENSIONS:
        return MEDIA_KIND_AUDIO
    return MEDIA_KIND_UNKNOWN


def mime_for_format(fmt: Optional[str]) -> Optional[str]:
    if not fmt:
        return None
    return _MIME_BY_FORMAT.get(str(fmt).lower())


def _read_head(path: str) -> bytes:
    try:
        if not os.path.isfile(path):
            return b""
        with open(path, "rb") as fh:
            return fh.read(_HEAD_BYTES)
    except Exception:
        return b""


def _starts(data: bytes, sig: bytes) -> bool:
    return len(data) >= len(sig) and data[:len(sig)] == sig


def _detect_by_signature(data: bytes, ext: str) -> Tuple[str, Optional[str]]:
    """按文件头签名识别，返回 (kind, format)。"""
    if not data:
        return MEDIA_KIND_UNKNOWN, None

    # ── 图片 ──────────────────────────────────────────────
    if _starts(data, b"\xff\xd8\xff"):
        return MEDIA_KIND_IMAGE, "jpg"
    if _starts(data, b"\x89PNG\r\n\x1a\n"):
        return MEDIA_KIND_IMAGE, "png"
    if _starts(data, b"GIF87a") or _starts(data, b"GIF89a"):
        return MEDIA_KIND_IMAGE, "gif"
    if _starts(data, b"BM"):
        return MEDIA_KIND_IMAGE, "bmp"
    if _starts(data, b"II*\x00") or _starts(data, b"MM\x00*"):
        return MEDIA_KIND_IMAGE, "tiff"
    if _starts(data, b"\x00\x00\x01\x00"):
        return MEDIA_KIND_IMAGE, "ico"

    # RIFF 容器：WEBP / WAV / AVI
    if len(data) >= 12 and _starts(data, b"RIFF"):
        riff_type = data[8:12]
        if riff_type == b"WEBP":
            return MEDIA_KIND_IMAGE, "webp"
        if riff_type == b"WAVE":
            return MEDIA_KIND_AUDIO, "wav"
        if riff_type == b"AVI ":
            return MEDIA_KIND_VIDEO, "avi"

    # ── ISO BMFF（mp4/mov/m4a/heic 等）────────────────────
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        # QuickTime / HEIC / AVIF 都有明确 brand，优先判断
        if brand == b"qt  ":
            return MEDIA_KIND_VIDEO, "mov"
        if brand in {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1"}:
            return MEDIA_KIND_IMAGE, "heic"
        if brand in {b"avif", b"avis"}:
            return MEDIA_KIND_IMAGE, "avif"
        if brand in {b"M4A ", b"M4B ", b"M4P ", b"F4A ", b"F4B "}:
            return MEDIA_KIND_AUDIO, "m4a" if brand != b"M4B " else "m4b"
        if brand in {b"M4V ", b"M4VH", b"MVP "}:
            return MEDIA_KIND_VIDEO, "m4v"
        if brand in {b"3gp4", b"3gp5", b"3gp6", b"3gg6"}:
            return MEDIA_KIND_VIDEO, "3gp"
        if brand == b"MSNV":
            return MEDIA_KIND_VIDEO, "mp4"
        # isom/mp41/mp42 既可能是视频也可能是纯音频，交给扩展名兜底
        if ext in AUDIO_EXTENSIONS:
            return MEDIA_KIND_AUDIO, ext.lstrip(".")
        if ext in VIDEO_EXTENSIONS or ext in {".mp4", ".mov"}:
            return MEDIA_KIND_VIDEO, ext.lstrip(".")

    # ── 音频 ──────────────────────────────────────────────
    if _starts(data, b"ID3"):
        return MEDIA_KIND_AUDIO, "mp3"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return MEDIA_KIND_AUDIO, "mp3"
    if _starts(data, b"fLaC"):
        return MEDIA_KIND_AUDIO, "flac"
    if _starts(data, b"OggS"):
        fmt = "ogg"
        if ext in AUDIO_EXTENSIONS:
            fmt = ext.lstrip(".")
        return MEDIA_KIND_AUDIO, fmt
    # ADTS AAC：帧头同步字（0xFFF）
    if len(data) >= 3 and data[0] == 0xFF and (data[1] & 0xF6) == 0xF0:
        return MEDIA_KIND_AUDIO, "aac"

    # ── 视频 ──────────────────────────────────────────────
    if _starts(data, b"\x1a\x45\xdf\xa3"):
        # EBML：webm 与 mkv 同签名，按扩展名区分
        fmt = ext.lstrip(".") if ext in VIDEO_EXTENSIONS else "mkv"
        return MEDIA_KIND_VIDEO, fmt
    if _starts(data, _ASF_SIGNATURE):
        # ASF 也用于 wma，扩展名优先
        if ext in AUDIO_EXTENSIONS:
            return MEDIA_KIND_AUDIO, ext.lstrip(".")
        return MEDIA_KIND_VIDEO, "wmv"
    if _starts(data, b"FLV"):
        return MEDIA_KIND_VIDEO, "flv"
    if _starts(data, b"\x00\x00\x01\xba"):
        return MEDIA_KIND_VIDEO, "mpeg"
    if len(data) >= 189 and data[0] == 0x47 and data[188] == 0x47:
        return MEDIA_KIND_VIDEO, "ts"

    return MEDIA_KIND_UNKNOWN, None


def detect_media_file(path: str) -> Dict[str, Optional[str]]:
    """识别单个文件，返回:

    {
        "kind": image|video|audio|unknown,
        "format": jpg|mp4|...,
        "mime": image/jpeg|...,
        "detected_by": content|extension|none,
    }
    """
    path = str(path or "")
    ext = normalize_extension(path)
    ext_fmt = ext.lstrip(".") if ext else None
    data = _read_head(path)
    kind, sig_fmt = _detect_by_signature(data, ext)

    if kind != MEDIA_KIND_UNKNOWN:
        fmt = sig_fmt or ext_fmt
        return {
            "kind": kind,
            "format": fmt,
            "mime": mime_for_format(fmt),
            "detected_by": "content",
        }

    ext_kind = kind_from_extension(path)
    if ext_kind != MEDIA_KIND_UNKNOWN:
        return {
            "kind": ext_kind,
            "format": ext_fmt,
            "mime": mime_for_format(ext_fmt),
            "detected_by": "extension",
        }

    return {
        "kind": MEDIA_KIND_UNKNOWN,
        "format": ext_fmt,
        "mime": None,
        "detected_by": "none",
    }


def media_kind_from_extension(ext: str) -> str:
    """按扩展名（可带点）返回 media_kind。"""
    ext = str(ext or "").strip().lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return kind_from_extension(ext)
