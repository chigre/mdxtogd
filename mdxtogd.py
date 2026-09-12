#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ANDROID_RESOURCE_PREFIX = "content://mobi.goldendict.android/resource"

DEFAULT_RESOURCE_EXTENSIONS = {
    ".css", ".js", ".mjs", ".ini", ".txt", ".html", ".htm", ".json", ".xml",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".bmp", ".webp", ".svg", ".ico", ".avif",
    ".mp3", ".spx", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".mp4", ".webm",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".ttc", ".otc", ".pfa", ".pfb", ".dfont", ".fon", ".fnt",
}
TEXT_RESOURCE_EXTENSIONS = {".css", ".js", ".mjs", ".ini", ".txt", ".html", ".htm", ".json", ".xml", ".svg"}
SKIP_SCHEMES = {"http", "https", "data", "content", "file", "mailto", "tel", "javascript", "gdlookup", "sound", "bres", "qrc", "ftp"}


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_config_value(value: str):
    """Parse a simple key=value config value."""
    value = str(value).strip()
    if not value:
        return ""

    low = value.lower()
    if low in ("true", "yes", "on", "1"):
        return True
    if low in ("false", "no", "off", "0"):
        return False

    # Optional matching quotes for paths containing leading/trailing spaces.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]

    return value


def load_text_config(path: Path, required: bool = True) -> dict:
    """
    Read human-editable config.txt syntax:

        source_file = ./dict.mdx
        output_dir =
        dictionary_name =
        resource_layout = original
        local_resource_dirs = .;./extra

    Blank lines and lines starting with # or ; are ignored.
    Inline comments are intentionally NOT stripped, so Windows paths and URLs
    remain literal and predictable.
    """
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"配置文件不存在：{path}")
        return {}

    data = {}
    with path.open('r', encoding='utf-8-sig') as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith('#') or line.startswith(';'):
                continue
            if '=' not in line:
                raise ValueError(
                    f"config.txt 第 {lineno} 行缺少 '='：{raw.rstrip()}"
                )
            key, value = line.split('=', 1)
            key = key.strip()
            if not key:
                raise ValueError(f"config.txt 第 {lineno} 行 key 为空")
            data[key] = parse_config_value(value)

    # One list-like option stays easy to edit as semicolon-separated text.
    dirs = data.get('local_resource_dirs', '')
    if isinstance(dirs, str):
        data['local_resource_dirs'] = [
            x.strip() for x in dirs.split(';') if x.strip()
        ] or ['.']

    return data


# ---------------- Language configuration / inference ----------------
# Canonical config codes use modern ISO 639 terminology (mostly ISO 639-3 /
# terminology codes): eng, zho, fra, deu, por...
#
# GoldenDict's DSL parser itself recognizes English language names such as
# "English" and "Chinese", so the DSL header is generated from dsl_name.
LANGUAGE_TABLE = {
    "eng": {"dsl_name": "English",     "aliases": ("en", "eng")},
    "zho": {"dsl_name": "Chinese",     "aliases": ("zh", "zho", "chi", "cn")},
    "fra": {"dsl_name": "French",      "aliases": ("fr", "fra", "fre")},
    "deu": {"dsl_name": "German",      "aliases": ("de", "deu", "ger")},
    "spa": {"dsl_name": "Spanish",     "aliases": ("es", "spa")},
    "ita": {"dsl_name": "Italian",     "aliases": ("it", "ita")},
    "por": {"dsl_name": "Portuguese",  "aliases": ("pt", "por")},
    "jpn": {"dsl_name": "Japanese",    "aliases": ("ja", "jpn")},
    "kor": {"dsl_name": "Korean",      "aliases": ("ko", "kor")},
    "rus": {"dsl_name": "Russian",     "aliases": ("ru", "rus")},
    "nld": {"dsl_name": "Dutch",       "aliases": ("nl", "nld", "dut")},
    "lat": {"dsl_name": "Latin",       "aliases": ("la", "lat")},
    "ara": {"dsl_name": "Arabic",      "aliases": ("ar", "ara")},
    "ell": {"dsl_name": "Greek",       "aliases": ("el", "ell", "gre")},
    "ces": {"dsl_name": "Czech",       "aliases": ("cs", "ces", "cze")},
    "slk": {"dsl_name": "Slovak",      "aliases": ("sk", "slk", "slo")},
    "ron": {"dsl_name": "Romanian",    "aliases": ("ro", "ron", "rum")},
    "hun": {"dsl_name": "Hungarian",   "aliases": ("hu", "hun")},
    "pol": {"dsl_name": "Polish",      "aliases": ("pl", "pol")},
    "tur": {"dsl_name": "Turkish",     "aliases": ("tr", "tur")},
    "vie": {"dsl_name": "Vietnamese",  "aliases": ("vi", "vie")},
    "tha": {"dsl_name": "Thai",        "aliases": ("th", "tha")},
    "ind": {"dsl_name": "Indonesian",  "aliases": ("id", "ind")},
    "msa": {"dsl_name": "Malay",       "aliases": ("ms", "msa", "may")},
    "hin": {"dsl_name": "Hindi",       "aliases": ("hi", "hin")},
    "ben": {"dsl_name": "Bengali",     "aliases": ("bn", "ben")},
    "urd": {"dsl_name": "Urdu",        "aliases": ("ur", "urd")},
    "fas": {"dsl_name": "Persian",     "aliases": ("fa", "fas", "per")},
    "heb": {"dsl_name": "Hebrew",      "aliases": ("he", "heb")},
    "swe": {"dsl_name": "Swedish",     "aliases": ("sv", "swe")},
    "dan": {"dsl_name": "Danish",      "aliases": ("da", "dan")},
    "nor": {"dsl_name": "Norwegian",   "aliases": ("no", "nor")},
    "fin": {"dsl_name": "Finnish",     "aliases": ("fi", "fin")},
    "ukr": {"dsl_name": "Ukrainian",   "aliases": ("uk", "ukr")},
    "cat": {"dsl_name": "Catalan",     "aliases": ("ca", "cat")},
    "eus": {"dsl_name": "Basque",      "aliases": ("eu", "eus", "baq")},
    "cym": {"dsl_name": "Welsh",       "aliases": ("cy", "cym", "wel")},
    "sqi": {"dsl_name": "Albanian",    "aliases": ("sq", "sqi", "alb")},
    "hye": {"dsl_name": "Armenian",    "aliases": ("hy", "hye", "arm")},
    "kat": {"dsl_name": "Georgian",    "aliases": ("ka", "kat", "geo")},
    "isl": {"dsl_name": "Icelandic",   "aliases": ("is", "isl", "ice")},
    "mkd": {"dsl_name": "Macedonian",  "aliases": ("mk", "mkd", "mac")},
    "mri": {"dsl_name": "Maori",       "aliases": ("mi", "mri", "mao")},
    "mya": {"dsl_name": "Burmese",     "aliases": ("my", "mya", "bur")},
    "bod": {"dsl_name": "Tibetan",     "aliases": ("bo", "bod", "tib")},
    "srp": {"dsl_name": "Serbian",     "aliases": ("sr", "srp")},
    "hrv": {"dsl_name": "Croatian",    "aliases": ("hr", "hrv")},
    "slv": {"dsl_name": "Slovenian",   "aliases": ("sl", "slv")},
    "bul": {"dsl_name": "Bulgarian",   "aliases": ("bg", "bul")},
}

LANGUAGE_ALIAS_TO_CODE = {"unk": "Unk", "unknown": "Unk"}
for _code, _info in LANGUAGE_TABLE.items():
    LANGUAGE_ALIAS_TO_CODE[_code] = _code
    LANGUAGE_ALIAS_TO_CODE[_info["dsl_name"].lower()] = _code
    for _alias in _info["aliases"]:
        LANGUAGE_ALIAS_TO_CODE[_alias.lower()] = _code

# Compact Chinese markers for common dictionary-name patterns.
CHINESE_LANGUAGE_MARKERS = {
    "英": "eng",
    "汉": "zho",
    "漢": "zho",
    "中": "zho",
    "法": "fra",
    "德": "deu",
    "西": "spa",
    "意": "ita",
    "葡": "por",
    "日": "jpn",
    "韩": "kor",
    "韓": "kor",
    "俄": "rus",
    "荷": "nld",
    "拉": "lat",
    "阿": "ara",
    "希": "ell",
    "越": "vie",
    "泰": "tha",
}

LANGUAGE_NAME_TOKENS = {
    "英语": "eng", "英文": "eng", "English": "eng",
    "汉语": "zho", "漢語": "zho", "汉文": "zho", "漢文": "zho",
    "中文": "zho", "华语": "zho", "華語": "zho",
    "国语": "zho", "國語": "zho", "Chinese": "zho",
    "法语": "fra", "法文": "fra", "French": "fra",
    "德语": "deu", "德文": "deu", "German": "deu",
    "西班牙语": "spa", "西班牙文": "spa", "西语": "spa", "西文": "spa", "Spanish": "spa",
    "意大利语": "ita", "意大利文": "ita", "意语": "ita", "意文": "ita", "Italian": "ita",
    "葡萄牙语": "por", "葡萄牙文": "por", "葡语": "por", "葡文": "por", "Portuguese": "por",
    "日语": "jpn", "日文": "jpn", "Japanese": "jpn",
    "韩语": "kor", "韓語": "kor", "韩文": "kor", "韓文": "kor", "Korean": "kor",
    "俄语": "rus", "俄文": "rus", "Russian": "rus",
    "荷兰语": "nld", "荷蘭語": "nld", "荷文": "nld", "Dutch": "nld",
    "拉丁语": "lat", "拉丁文": "lat", "Latin": "lat",
    "阿拉伯语": "ara", "阿拉伯文": "ara", "Arabic": "ara",
    "希腊语": "ell", "希臘語": "ell", "Greek": "ell",
    "越南语": "vie", "越南文": "vie", "Vietnamese": "vie",
    "泰语": "tha", "泰文": "tha", "Thai": "tha",
}

# User-facing aliases accepted directly in config.txt.
# Examples:
#   英 / 英语 / 英文 / English / eng -> eng
#   中 / 汉 / 漢 / 汉语 / 中文 / Chinese / zho / chi -> zho
for _token, _code in LANGUAGE_NAME_TOKENS.items():
    LANGUAGE_ALIAS_TO_CODE[_token.lower()] = _code

for _token, _code in CHINESE_LANGUAGE_MARKERS.items():
    LANGUAGE_ALIAS_TO_CODE[_token.lower()] = _code

EXTRA_LANGUAGE_INPUT_ALIASES = {
    # English
    "英": "eng", "英语": "eng", "英文": "eng",

    # Chinese
    "中": "zho", "汉": "zho", "漢": "zho",
    "汉语": "zho", "漢語": "zho", "汉文": "zho", "漢文": "zho",
    "中文": "zho", "华语": "zho", "華語": "zho",
    "国语": "zho", "國語": "zho",

    # Common Chinese short forms for other languages
    "法": "fra", "法语": "fra", "法文": "fra",
    "德": "deu", "德语": "deu", "德文": "deu",
    "西": "spa", "西语": "spa", "西文": "spa", "西班牙语": "spa",
    "意": "ita", "意语": "ita", "意文": "ita", "意大利语": "ita",
    "葡": "por", "葡语": "por", "葡文": "por", "葡萄牙语": "por",
    "日": "jpn", "日语": "jpn", "日文": "jpn",
    "韩": "kor", "韓": "kor", "韩语": "kor", "韓語": "kor", "韩文": "kor", "韓文": "kor",
    "俄": "rus", "俄语": "rus", "俄文": "rus",
    "荷": "nld", "荷兰语": "nld", "荷蘭語": "nld",
    "拉": "lat", "拉丁语": "lat", "拉丁文": "lat",
    "阿": "ara", "阿拉伯语": "ara", "阿拉伯文": "ara",
    "希": "ell", "希腊语": "ell", "希臘語": "ell",
    "越": "vie", "越南语": "vie", "越南文": "vie",
    "泰": "tha", "泰语": "tha", "泰文": "tha",
}

for _token, _code in EXTRA_LANGUAGE_INPUT_ALIASES.items():
    LANGUAGE_ALIAS_TO_CODE[_token.lower()] = _code


def normalize_language_code(value: str) -> str:
    """Normalize codes / Chinese names / English names to canonical code."""
    s = str(value or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low in LANGUAGE_ALIAS_TO_CODE:
        return LANGUAGE_ALIAS_TO_CODE[low]
    # Allow an explicit 3-letter custom code, but it will map to DSL "Any"
    # unless it exists in LANGUAGE_TABLE.
    if re.fullmatch(r"[A-Za-z]{3}", s):
        return s.lower()
    raise ValueError(
        f"不认识的语言：{value!r}。可填写 eng / English / 英语 / 英 等；"
        "无法确定时可写 Unk。"
    )


def dsl_language_name(code: str) -> str:
    if not code or str(code).lower() == "unk":
        return "Any"
    return LANGUAGE_TABLE.get(str(code).lower(), {}).get("dsl_name", "Any")


def iso6391_for_language(code: str) -> Optional[str]:
    """
    Return ISO 639-1 two-letter code for GoldenDict StarDict filename
    language-pair detection.
    """
    if not code or str(code).lower() == "unk":
        return None

    canonical = normalize_language_code(code)
    if not canonical or str(canonical).lower() == "unk":
        return None

    info = LANGUAGE_TABLE.get(str(canonical).lower())
    if not info:
        return None

    for alias in info.get("aliases", ()):
        alias = str(alias).lower()
        if re.fullmatch(r"[a-z]{2}", alias):
            return alias

    return None


def stardict_language_tag(
    index_code: str,
    contents_code: str,
) -> Optional[str]:
    """
    GoldenDict can infer StarDict language pair from filename tokens such as
    en-zh. Emit a tag only when BOTH languages have reliable ISO 639-1 codes.
    """
    src = iso6391_for_language(index_code)
    dst = iso6391_for_language(contents_code)
    if not src or not dst:
        return None
    return f"{src}-{dst}"


def stardict_basename(
    dictionary_name: str,
    index_code: str,
    contents_code: str,
) -> Tuple[str, Optional[str]]:
    tag = stardict_language_tag(index_code, contents_code)
    if tag:
        return f"{dictionary_name}.{tag}", tag
    return dictionary_name, None


def enforce_stardict_bookname(
    ifo_path: Path,
    bookname: str,
) -> None:
    """
    Force .ifo bookname to remain the clean user-facing dictionary name even
    when StarDict filenames include a language pair, e.g. name.en-zh.ifo.
    """
    if not ifo_path.is_file():
        raise FileNotFoundError(
            f"StarDict IFO 不存在：{ifo_path}"
        )

    text = ifo_path.read_text(
        encoding="utf-8-sig"
    )
    lines = (
        text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    )

    replaced = False
    for i, line in enumerate(lines):
        if line.startswith("bookname="):
            lines[i] = "bookname=" + str(bookname)
            replaced = True
            break

    if not replaced:
        insert_index = 2 if len(lines) >= 2 else len(lines)
        lines.insert(
            insert_index,
            "bookname=" + str(bookname),
        )

    while lines and lines[-1] == "":
        lines.pop()

    ifo_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def infer_language_pair(*names: str) -> Tuple[str, str, str]:
    """
    Infer index/content language from filenames / dictionary names.

    Priority:
      1) Chinese compact pair: 英汉 / 汉英 / 英英 / 法汉 ...
      2) Delimited code pair: EN-ZH, POR-ZH, PT_ZH, IT-EN ...
      3) Two explicit language-name tokens in text.

    Returns: (index_code, contents_code, reason)
    Unknown => ("Unk", "Unk", "unresolved")
    """
    text = " ".join(str(x or "") for x in names if x).strip()
    if not text:
        return "Unk", "Unk", "unresolved"

    # 1) Common compact Chinese pair.
    chars = list(text)
    for i in range(len(chars) - 1):
        a = CHINESE_LANGUAGE_MARKERS.get(chars[i])
        b = CHINESE_LANGUAGE_MARKERS.get(chars[i + 1])
        if a and b:
            return a, b, f"filename:{chars[i]}{chars[i + 1]}"

    # 2) Delimited language codes / abbreviations.
    pair_re = re.compile(
        r"(?i)(?<![A-Za-z])([A-Za-z]{2,3})\s*[-_/+]\s*"
        r"([A-Za-z]{2,3})(?![A-Za-z])"
    )
    for m in pair_re.finditer(text):
        a = LANGUAGE_ALIAS_TO_CODE.get(m.group(1).lower())
        b = LANGUAGE_ALIAS_TO_CODE.get(m.group(2).lower())
        if a and b and a != "Unk" and b != "Unk":
            return a, b, f"filename:{m.group(0)}"

    # 3) Full language names, preserving textual order.
    hits = []
    lower_text = text.lower()
    for token, code in LANGUAGE_NAME_TOKENS.items():
        start = 0
        needle = token.lower()
        while True:
            pos = lower_text.find(needle, start)
            if pos < 0:
                break
            hits.append((pos, -len(token), code, token))
            start = pos + max(1, len(needle))

    hits.sort()
    ordered = []
    for hit in hits:
        # Avoid counting overlapping synonyms for the same language twice.
        if not ordered or hit[2] != ordered[-1][2] or hit[0] != ordered[-1][0]:
            ordered.append(hit)

    if len(ordered) >= 2:
        return (
            ordered[0][2],
            ordered[1][2],
            f"filename:{ordered[0][3]}→{ordered[1][3]}",
        )

    return "Unk", "Unk", "unresolved"


def resolve_languages(cfg: dict, mdx: Path, dictionary_name: str) -> dict:
    """
    Explicit config is strongly preferred.
    Missing fields are inferred independently as a pair only when needed.
    """
    raw_index = cfg.get("INDEX_LANGUAGE", cfg.get("index_language", ""))
    raw_contents = cfg.get("CONTENTS_LANGUAGE", cfg.get("contents_language", ""))

    index_code = normalize_language_code(raw_index)
    contents_code = normalize_language_code(raw_contents)

    inferred_index, inferred_contents, reason = infer_language_pair(
        mdx.stem,
        dictionary_name,
    )

    index_source = "config"
    contents_source = "config"

    if not index_code:
        index_code = inferred_index
        index_source = "inferred" if inferred_index != "Unk" else "fallback"

    if not contents_code:
        contents_code = inferred_contents
        contents_source = "inferred" if inferred_contents != "Unk" else "fallback"

    if not index_code:
        index_code = "Unk"
        index_source = "fallback"
    if not contents_code:
        contents_code = "Unk"
        contents_source = "fallback"

    return {
        "index_code": index_code,
        "contents_code": contents_code,
        "index_dsl_name": dsl_language_name(index_code),
        "contents_dsl_name": dsl_language_name(contents_code),
        "index_source": index_source,
        "contents_source": contents_source,
        "inference_reason": reason,
    }


def expand_install_template(
    value: str,
    name: str,
    index_code: str,
    contents_code: str,
) -> str:
    language_pair = (
        f"{str(index_code).upper()}-"
        f"{str(contents_code).upper()}"
    )
    return (
        str(value or "")
        .replace("{dictionary_name}", name)
        .replace("{INDEX_LANGUAGE}", str(index_code).upper())
        .replace("{CONTENTS_LANGUAGE}", str(contents_code).upper())
        .replace("{LANGUAGE_PAIR}", language_pair)
    )


def normalize_css_storage(value: str) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "": "zip",
        "zip": "zip",
        "resource_zip": "zip",   # backward compatibility
        "folder": "folder",
    }
    if raw not in aliases:
        raise ValueError("css_storage 只能是 zip 或 folder")
    return aliases[raw]


def normalize_resource_layout(value: str) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "": "root",
        "root": "root",
        "flat": "root",          # backward compatibility
        "original": "original",
        "preserve": "original",  # backward compatibility
    }
    if raw not in aliases:
        raise ValueError("resource_layout 只能是 root 或 original")
    return aliases[raw]


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def posix_join(*parts: str) -> str:
    out = []
    for i, p in enumerate(parts):
        s = str(p).replace("\\", "/")
        out.append(s.rstrip("/") if i == 0 else s.strip("/"))
    return "/".join(x for x in out if x)


def canonical_resource_path(raw: str, base_dir: str = "") -> str:
    raw = urllib.parse.unquote(str(raw or "")).strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    raw = raw.lstrip("/")
    if base_dir:
        raw = posixpath.join(base_dir, raw)
    norm = posixpath.normpath(raw).replace("\\", "/")
    while norm.startswith("../"):
        norm = norm[3:]
    return "" if norm in ("", ".") else norm.lstrip("/")


def device_abs_path(root: str, rel: str) -> str:
    return posix_join(str(root).rstrip("/"), rel)


def file_url_from_device_path(path: str) -> str:
    return "file://" + urllib.parse.quote(str(path).replace("\\", "/"), safe="/:@-._~!$&'()*+,;=")


def split_suffix(ref: str) -> Tuple[str, str]:
    positions = [x for x in (ref.find("?"), ref.find("#")) if x >= 0]
    if not positions:
        return ref, ""
    i = min(positions)
    return ref[:i], ref[i:]


def is_external_or_special(ref: str) -> bool:
    ref = str(ref or "").strip()
    if not ref or ref.startswith("#") or ref.startswith("//"):
        return True
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", ref)
    if not m:
        return False
    scheme = m.group(1).lower()
    return scheme in SKIP_SCHEMES or scheme != "entry"


def safe_read_text(path: Path) -> Optional[str]:
    data = path.read_bytes()
    if b"\x00" in data[:4096] and not (data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff")):
        return None
    for enc in ("utf-8-sig", "utf-8", "utf-16", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------- Android GoldenDict hash ----------------
def android_goldendict_resource_id(relative_dict_path: str, encoding: str = "utf-8") -> str:
    relative_dict_path = canonical_resource_path(relative_dict_path)
    if not relative_dict_path:
        raise ValueError("Android GoldenDict hash 输入不能为空")
    return hashlib.md5(relative_dict_path.encode(encoding)).hexdigest()


def verify_android_hash_algorithm() -> None:
    known = {
        "a.dsl": "cf720ab20d00f14ea433254b99c5c1b8",
        "zzz/a.dsl": "5a4a28e8fab346d876be7e2218556487",
    }
    for rel, expected in known.items():
        actual = android_goldendict_resource_id(rel)
        if actual != expected:
            raise RuntimeError(f"Android GoldenDict hash 自检失败: {rel} -> {actual}, expected {expected}")


# ---------------- Source input: MDX / Tabfile / MDict Textfile ----------------

SUPPORTED_INPUT_TYPES = {"auto", "mdx", "tabfile", "textfile"}


def read_source_text(path: Path) -> Tuple[str, str]:
    """
    Read text source with practical dictionary encodings.
    Returns (text, encoding_used).
    """
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "utf-16", "gb18030"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            pass
    raise UnicodeError(
        f"无法识别文本文件编码：{path}。"
        "目前尝试了 UTF-8/UTF-8 BOM/UTF-16/GB18030。"
    )


def normalize_input_type(value: str) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "": "auto",
        "auto": "auto",
        "mdx": "mdx",
        "tab": "tabfile",
        "tabfile": "tabfile",
        "tsv": "tabfile",
        "text": "textfile",
        "textfile": "textfile",
        "mdict": "textfile",
        "mdict_text": "textfile",
    }
    if raw not in aliases:
        raise ValueError(
            "input_type 只能是 auto / mdx / tabfile / textfile"
        )
    return aliases[raw]


def detect_source_type(path: Path, configured_type: str = "auto") -> str:
    """
    Auto detection:
      .mdx                  -> mdx
      .tab/.tabfile/.tsv    -> tabfile
      text containing a standalone </> line -> textfile
      otherwise text with a TAB on an entry line -> tabfile
    """
    configured = normalize_input_type(configured_type)
    if configured != "auto":
        return configured

    ext = path.suffix.lower()
    if ext == ".mdx":
        return "mdx"
    if ext in (".tab", ".tabfile", ".tsv"):
        return "tabfile"

    text, _enc = read_source_text(path)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    if any(line.strip() == "</>" for line in lines):
        return "textfile"

    if any("\t" in line for line in lines if line.strip()):
        return "tabfile"

    raise ValueError(
        f"无法自动判断输入格式：{path.name}。"
        "请在 config.txt 设置 input_type = tabfile 或 textfile。"
    )


def normalize_tabfile_to_utf8(source: Path, tabfile: Path) -> dict:
    """
    Copy an existing Tabfile into normalized UTF-8 LF form.
    The actual dictionary entries are not altered here.
    """
    text, encoding = read_source_text(source)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    tabfile.parent.mkdir(parents=True, exist_ok=True)
    tabfile.write_text(text, encoding="utf-8", newline="\n")

    nonempty = [x for x in text.split("\n") if x]
    with_tab = sum(1 for x in nonempty if "\t" in x)
    return {
        "source_type": "tabfile",
        "source_encoding": encoding,
        "source_entries_estimated": with_tab,
    }


def convert_mdict_textfile_to_tabfile(source: Path, tabfile: Path) -> dict:
    r"""
    Convert MDict-style text source:

        headword
        definition line 1
        definition line 2
        </>

    to one-entry-per-line Tabfile:

        headword<TAB>definition line 1\n definition line 2

    The separator must be a line whose stripped content is exactly </>.
    Real newlines inside a definition are written as the literal two
    characters backslash+n: "\\n".
    """
    text, encoding = read_source_text(source)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    records: List[List[str]] = []
    block: List[str] = []
    missing_final_delimiter = False

    for line in lines:
        if line.strip() == "</>":
            # Ignore blank padding before a record, but preserve definition
            # blank lines after the headword.
            while block and block[0] == "":
                block.pop(0)
            if block:
                records.append(block)
            block = []
        else:
            block.append(line)

    # Accept a useful final record even if the last </> was omitted.
    while block and block[0] == "":
        block.pop(0)
    while block and block[-1] == "":
        block.pop()
    if block:
        records.append(block)
        missing_final_delimiter = True

    tabfile.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_empty_headword = 0

    with tabfile.open("w", encoding="utf-8", newline="\n") as f:
        for record in records:
            if not record:
                continue

            headword = record[0].lstrip("\ufeff").strip()
            if not headword:
                skipped_empty_headword += 1
                continue

            body_lines = record[1:]

            # Tabfile must keep one physical line per entry.
            # Convert real definition line breaks to literal "\n".
            definition = r"\n".join(body_lines)

            f.write(headword + "\t" + definition + "\n")
            written += 1

    if written == 0:
        raise ValueError(
            f"Textfile 未解析到有效词条：{source}"
        )

    return {
        "source_type": "textfile",
        "source_encoding": encoding,
        "source_entries": written,
        "records_detected": len(records),
        "skipped_empty_headword": skipped_empty_headword,
        "missing_final_delimiter_accepted": missing_final_delimiter,
        "definition_newline_encoding": r"\n",
    }


def prepare_source_tabfile(
    source: Path,
    tabfile: Path,
    input_type: str = "auto",
) -> dict:
    source_type = detect_source_type(source, input_type)

    if source_type == "mdx":
        convert_mdx_to_tabfile(source, tabfile)
        return {
            "source_type": "mdx",
            "source_encoding": None,
            "conversion": "PyGlossary MDX -> Tabfile",
        }

    if source_type == "tabfile":
        return normalize_tabfile_to_utf8(source, tabfile)

    if source_type == "textfile":
        return convert_mdict_textfile_to_tabfile(source, tabfile)

    raise RuntimeError(f"未处理的 source_type：{source_type}")


# ---------------- PyGlossary ----------------
_GLOSSARY_INITIALIZED = False


def get_glossary_class():
    global _GLOSSARY_INITIALIZED
    try:
        from pyglossary import Glossary
    except ImportError as e:
        raise RuntimeError("未安装 PyGlossary：pip install -U pyglossary xxhash") from e
    if not _GLOSSARY_INITIALIZED:
        Glossary.init()
        _GLOSSARY_INITIALIZED = True
    return Glossary


def convert_mdx_to_tabfile(mdx: Path, tabfile: Path) -> None:
    Glossary = get_glossary_class()
    tabfile.parent.mkdir(parents=True, exist_ok=True)
    log(f"      PyGlossary: MDX -> Tabfile: {mdx.name}")
    glos = Glossary()
    result = glos.convert(inputFilename=str(mdx), outputFilename=str(tabfile), outputFormat="Tabfile")
    if result is False or not tabfile.exists():
        raise RuntimeError("PyGlossary MDX -> Tabfile 转换失败")


def pyglossary_tab_to_stardict(tabfile: Path, ifo_path: Path, dictzip: bool, html: bool = True) -> None:
    Glossary = get_glossary_class()
    ifo_path.parent.mkdir(parents=True, exist_ok=True)
    opts = {"dictzip": bool(dictzip)}
    if html:
        opts["sametypesequence"] = "h"
    glos = Glossary()
    result = glos.convert(
        inputFilename=str(tabfile), outputFilename=str(ifo_path), inputFormat="Tabfile",
        outputFormat="Stardict", writeOptions=opts,
    )
    if result is False or not ifo_path.exists():
        raise RuntimeError(f"PyGlossary Tabfile -> StarDict 转换失败 (dictzip={dictzip})")


def list_stardict_files(folder: Path, base: str) -> List[Path]:
    out = []
    for suffix in (".ifo", ".idx", ".idx.gz", ".dict", ".dict.dz", ".syn", ".res.zip"):
        p = folder / (base + suffix)
        if p.exists():
            out.append(p)
    return out


def build_stardict(
    tabfile: Path,
    output_dir: Path,
    stardict_base: str,
    bookname: str,
    keep_dictzip: bool,
    html: bool = True,
) -> List[Path]:
    """
    Build StarDict with language-tagged filenames when available.

    Example filenames:
        外研社英汉多功能词典.en-zh.ifo
        外研社英汉多功能词典.en-zh.idx
        外研社英汉多功能词典.en-zh.dict

    .ifo bookname remains:
        外研社英汉多功能词典
    """
    final_ifo = output_dir / f"{stardict_base}.ifo"

    pyglossary_tab_to_stardict(
        tabfile,
        final_ifo,
        dictzip=False,
        html=html,
    )
    enforce_stardict_bookname(
        final_ifo,
        bookname,
    )

    dict_file = output_dir / f"{stardict_base}.dict"
    if not dict_file.exists():
        raise RuntimeError(
            "未生成预期的 StarDict .dict 文件"
        )

    dz_file = output_dir / f"{stardict_base}.dict.dz"

    if keep_dictzip:
        with tempfile.TemporaryDirectory(
            prefix="mdx2gd_dictzip_"
        ) as td:
            temp_dir = Path(td)
            temp_ifo = temp_dir / f"{stardict_base}.ifo"

            pyglossary_tab_to_stardict(
                tabfile,
                temp_ifo,
                dictzip=True,
                html=html,
            )

            temp_dz = (
                temp_dir /
                f"{stardict_base}.dict.dz"
            )

            if not temp_dz.exists():
                raise RuntimeError(
                    "stardict_dictzip=true，"
                    "但 PyGlossary 未生成 .dict.dz"
                )

            shutil.copy2(
                temp_dz,
                dz_file,
            )

    elif dz_file.exists():
        dz_file.unlink()

    return list_stardict_files(
        output_dir,
        stardict_base,
    )


# ---------------- MDD auto-discovery / extraction ----------------
def discover_companion_mdds(source: Path) -> List[Path]:
    pattern = re.compile(r"^" + re.escape(source.stem) + r"(?:\.(\d+))?\.mdd$", re.IGNORECASE)
    found = []
    for p in source.parent.iterdir():
        if not p.is_file():
            continue
        m = pattern.match(p.name)
        if not m:
            continue
        part = m.group(1)
        order = -1 if part is None else int(part)
        found.append((order, p.name.lower(), p))
    found.sort(key=lambda x: (x[0], x[1]))
    return [p for _, _, p in found]


def extract_mdd(mdd: Path, extract_dir: Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    exe = shutil.which("mdict")
    if exe:
        cmd = [exe, "-x", str(mdd), "-d", str(extract_dir)]
    else:
        try:
            import mdict_utils  # noqa: F401
        except ImportError as e:
            raise RuntimeError("未安装 mdict-utils：pip install -U mdict-utils") from e
        cmd = [sys.executable, "-m", "mdict_utils", "-x", str(mdd), "-d", str(extract_dir)]

    log(f"      extracting: {mdd.name}")
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"MDD 提取失败：{mdd}\n命令：{' '.join(cmd)}\n输出：\n{p.stdout}")


@dataclass
class ResourceItem:
    source_path: Path
    original_path: str
    source_mdd: str  # MDD filename or "[local]"
    output_path: str = ""
    target_kind: str = "zip"  # zip / folder
    target_url: str = ""


def collect_resources_from_mdds(mdds: List[Path], temp_root: Path) -> List[ResourceItem]:
    by_original_lower: Dict[str, ResourceItem] = {}
    for i, mdd in enumerate(mdds):
        extract_dir = temp_root / f"mdd_{i:03d}"
        extract_mdd(mdd, extract_dir)
        for p in extract_dir.rglob("*"):
            if not p.is_file():
                continue
            original = canonical_resource_path(p.relative_to(extract_dir).as_posix())
            if not original:
                continue
            key = original.lower()
            item = ResourceItem(p, original, mdd.name)
            previous = by_original_lower.get(key)
            if previous is None:
                by_original_lower[key] = item
            elif sha256_file(previous.source_path) != sha256_file(p):
                raise RuntimeError(
                    "多个 MDD 中存在同一路径但内容不同的资源，无法安全判断引用：\n"
                    f"  path: {original}\n  A: {previous.source_mdd}\n  B: {mdd.name}"
                )
    return list(by_original_lower.values())


# ---------------- Resource output layout ----------------
_INVALID_FLAT_CHARS = re.compile(r'[:*?"<>|\x00-\x1f]')


def sanitize_flat_component(name: str) -> str:
    name = urllib.parse.unquote(str(name)).replace("\\", "_").replace("/", "_")
    name = _INVALID_FLAT_CHARS.sub("_", name)
    name = re.sub(r"_+", "_", name).strip(" _")
    return name or "resource"


def make_collision_flat_name(original_path: str) -> str:
    return "_".join(
        sanitize_flat_component(x)
        for x in canonical_resource_path(original_path).split("/")
        if x
    )


def _assign_flat_output_paths(items: List[ResourceItem]) -> List[dict]:
    """Assign collision-safe root-level filenames to a selected item set."""
    basename_groups: Dict[str, List[ResourceItem]] = {}
    for item in items:
        base = posixpath.basename(item.original_path)
        basename_groups.setdefault(base.lower(), []).append(item)

    assigned_lower = set()
    renamed = []

    for item in sorted(items, key=lambda x: x.original_path.lower()):
        base = posixpath.basename(item.original_path)
        group = basename_groups[base.lower()]
        candidate = (
            sanitize_flat_component(base)
            if len(group) == 1
            else make_collision_flat_name(item.original_path)
        )

        if candidate.lower() in assigned_lower:
            stem, ext = os.path.splitext(candidate)
            suffix = hashlib.md5(
                item.original_path.encode("utf-8")
            ).hexdigest()[:8]
            candidate = f"{stem}_{suffix}{ext}"
            n = 2
            while candidate.lower() in assigned_lower:
                candidate = f"{stem}_{suffix}_{n}{ext}"
                n += 1

        assigned_lower.add(candidate.lower())
        item.output_path = candidate

        if candidate != item.original_path:
            renamed.append({
                "source_mdd": item.source_mdd,
                "original_path": item.original_path,
                "output_path": candidate,
                "reason": "flatten",
            })

    return renamed


def assign_resource_output_paths(
    items: List[ResourceItem],
    resource_layout: str,
    css_storage: str,
) -> List[dict]:
    """
    resource_layout:
      root
        All ZIP resources are stored at ZIP root. Duplicate basenames are
        renamed using original directory names.

      original
        ZIP resources keep their normalized original MDD paths/directories.

    css_storage:
      zip
        CSS follows resource_layout inside .dsl.files.zip.
      folder
        CSS is external and always flattened to the common final dictionary
        directory root.
    """
    resource_layout = normalize_resource_layout(resource_layout)
    css_storage = normalize_css_storage(css_storage)

    zip_items: List[ResourceItem] = []
    folder_css: List[ResourceItem] = []

    for item in items:
        ext = posixpath.splitext(item.original_path)[1].lower()
        if ext == ".css" and css_storage == "folder":
            item.target_kind = "folder"
            folder_css.append(item)
        else:
            item.target_kind = "zip"
            zip_items.append(item)

    renamed: List[dict] = []

    # External CSS always goes to final dictionary directory root.
    if folder_css:
        css_renamed = _assign_flat_output_paths(folder_css)
        for r in css_renamed:
            r["reason"] = "external_css_root"
        renamed.extend(css_renamed)

    if resource_layout == "root":
        zip_renamed = _assign_flat_output_paths(zip_items)
        for r in zip_renamed:
            r["reason"] = "zip_root"
        renamed.extend(zip_renamed)
    else:
        for item in zip_items:
            item.output_path = canonical_resource_path(item.original_path)

    return renamed


# ---------------- Resource resolver ----------------
class ResourceResolver:
    def __init__(self, dsl_id: str, items: List[ResourceItem], resource_extensions: Iterable[str]):
        self.dsl_id = dsl_id
        self.exts = {x.lower() if str(x).startswith(".") else "." + str(x).lower() for x in resource_extensions}
        self.exact: Dict[str, str] = {}
        self.lower: Dict[str, str] = {}
        self.basename_unique: Dict[str, str] = {}
        self.basename_ambiguous = set()
        self.replaced_count = 0
        self.unresolved = set()

        for item in items:
            key = canonical_resource_path(item.original_path)
            self.exact[key] = item.target_url
            self.lower[key.lower()] = item.target_url

        groups: Dict[str, List[ResourceItem]] = {}
        for item in items:
            groups.setdefault(posixpath.basename(item.original_path).lower(), []).append(item)
        for base, group in groups.items():
            if len(group) == 1:
                self.basename_unique[base] = group[0].target_url
            else:
                self.basename_ambiguous.add(base)

    def lookup(self, path: str) -> Optional[str]:
        path = canonical_resource_path(path)
        if not path:
            return None
        if path in self.exact:
            return self.exact[path]
        if path.lower() in self.lower:
            return self.lower[path.lower()]
        return self.basename_unique.get(posixpath.basename(path).lower())

    def rewrite_ref(self, ref: str, current_resource: str = "") -> str:
        original = str(ref or "")
        s = original.strip()
        if not s:
            return original
        if s.lower().startswith("entry://"):
            self.replaced_count += 1
            return re.sub(r"(?i)^entry://", "", s)
        if is_external_or_special(s):
            return original

        path_part, suffix = split_suffix(s)
        base_dir = posixpath.dirname(current_resource) if current_resource else ""
        candidates = []
        if base_dir:
            candidates.append(canonical_resource_path(path_part, base_dir))
        candidates.append(canonical_resource_path(path_part))

        seen = set()
        for c in candidates:
            if not c or c in seen:
                continue
            seen.add(c)
            url = self.lookup(c)
            if url:
                self.replaced_count += 1
                return url + suffix

        diagnostic = candidates[0] if candidates else ""
        if posixpath.splitext(diagnostic)[1].lower() in self.exts:
            self.unresolved.add(s)
        return original


ATTR_RE = re.compile(r'''(?P<prefix>\b(?:src|href|poster|data)\s*=\s*)(?P<q>["'])(?P<url>.*?)(?P=q)''', re.I)
CSS_URL_RE = re.compile(r'''(?P<prefix>\burl\(\s*)(?P<q>["']?)(?P<url>[^)"']+?)(?P=q)(?P<suffix>\s*\))''', re.I)
CSS_IMPORT_RE = re.compile(r'''(?P<prefix>@import\s+)(?P<q>["'])(?P<url>.*?)(?P=q)''', re.I)
SRCSET_RE = re.compile(r'''(?P<prefix>\bsrcset\s*=\s*)(?P<q>["'])(?P<value>.*?)(?P=q)''', re.I)
QUOTED_REF_RE = re.compile(r'''(?P<q>["'])(?P<url>[^"'<> \t\r\n]+?\.[A-Za-z0-9]{1,10}(?:[?#][^"'<> \t\r\n]*)?)(?P=q)''', re.I)


def rewrite_srcset(value: str, resolver: ResourceResolver, current_resource: str) -> str:
    out = []
    for item in value.split(","):
        bits = item.strip().split()
        if bits:
            out.append(" ".join([resolver.rewrite_ref(bits[0], current_resource)] + bits[1:]))
    return ", ".join(out)


def rewrite_markup(text: str, resolver: ResourceResolver, current_resource: str = "") -> str:
    text = re.sub(r"(?i)entry://", "", text)
    text = ATTR_RE.sub(lambda m: m.group("prefix") + m.group("q") + resolver.rewrite_ref(m.group("url"), current_resource) + m.group("q"), text)
    text = SRCSET_RE.sub(lambda m: m.group("prefix") + m.group("q") + rewrite_srcset(m.group("value"), resolver, current_resource) + m.group("q"), text)
    text = CSS_URL_RE.sub(lambda m: m.group("prefix") + m.group("q") + resolver.rewrite_ref(m.group("url").strip(), current_resource) + m.group("q") + m.group("suffix"), text)
    text = CSS_IMPORT_RE.sub(lambda m: m.group("prefix") + m.group("q") + resolver.rewrite_ref(m.group("url"), current_resource) + m.group("q"), text)
    text = QUOTED_REF_RE.sub(lambda m: m.group("q") + resolver.rewrite_ref(m.group("url"), current_resource) + m.group("q"), text)
    return text

# ---------------- Referenced local resources ----------------
def extract_resource_refs(text: str) -> List[str]:
    """Collect resource-looking references without rewriting them."""
    refs: List[str] = []
    for m in ATTR_RE.finditer(text):
        refs.append(m.group("url"))
    for m in CSS_URL_RE.finditer(text):
        refs.append(m.group("url").strip())
    for m in CSS_IMPORT_RE.finditer(text):
        refs.append(m.group("url"))
    for m in SRCSET_RE.finditer(text):
        for item in m.group("value").split(","):
            bits = item.strip().split()
            if bits:
                refs.append(bits[0])
    for m in QUOTED_REF_RE.finditer(text):
        refs.append(m.group("url"))

    out: List[str] = []
    seen = set()
    for ref in refs:
        s = str(ref or "").strip()
        if not s or s.lower().startswith("entry://") or is_external_or_special(s):
            continue
        key = s.lower()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def build_local_file_index(
    mdx: Path,
    local_resource_dirs: Iterable[str],
    recursive: bool,
    resource_extensions: Iterable[str],
    exclude_dirs: Iterable[Path],
) -> dict:
    allowed = {
        x.lower() if str(x).startswith(".") else "." + str(x).lower()
        for x in resource_extensions
    }
    mdx_dir = mdx.parent.resolve()
    excluded = [Path(x).resolve() for x in exclude_dirs]
    exact: Dict[str, dict] = {}
    basename_groups: Dict[str, List[dict]] = {}
    roots_report = []

    for raw_root in local_resource_dirs:
        root = Path(str(raw_root))
        root = root.resolve() if root.is_absolute() else (mdx_dir / root).resolve()
        roots_report.append(str(root))
        if not root.is_dir():
            continue
        iterator = root.rglob("*") if recursive else root.iterdir()
        for p in iterator:
            if not p.is_file():
                continue
            rp = p.resolve()
            if any(_is_under(rp, ex) for ex in excluded):
                continue
            if p.suffix.lower() not in allowed:
                continue
            try:
                logical = canonical_resource_path(rp.relative_to(mdx_dir).as_posix())
            except ValueError:
                logical = canonical_resource_path(rp.relative_to(root).as_posix())
            if not logical:
                continue
            rec = {"path": rp, "logical": logical, "root": str(root)}
            key = logical.lower()
            old = exact.get(key)
            if old is not None and old["path"] != rp:
                if sha256_file(old["path"]) != sha256_file(rp):
                    raise RuntimeError(
                        "多个本地资源目录中存在同一路径但内容不同的文件：\n"
                        f"  path: {logical}\n  A: {old['path']}\n  B: {rp}"
                    )
                continue
            exact[key] = rec
            basename_groups.setdefault(posixpath.basename(logical).lower(), []).append(rec)

    basename_unique = {
        base: group[0]
        for base, group in basename_groups.items()
        if len({str(x["path"]) for x in group}) == 1
    }
    return {"exact": exact, "basename_unique": basename_unique, "roots": roots_report}


def _logical_candidates(ref: str, current_resource: str = "") -> List[str]:
    path_part, _suffix = split_suffix(str(ref or "").strip())
    base_dir = posixpath.dirname(current_resource) if current_resource else ""
    out = []
    if base_dir:
        out.append(canonical_resource_path(path_part, base_dir))
    out.append(canonical_resource_path(path_part))
    dedup = []
    seen = set()
    for x in out:
        if x and x.lower() not in seen:
            seen.add(x.lower())
            dedup.append(x)
    return dedup


def _resource_exists_in_items(items: List[ResourceItem], ref: str, current_resource: str = "") -> bool:
    candidates = _logical_candidates(ref, current_resource)
    exact = {canonical_resource_path(x.original_path).lower() for x in items}
    for c in candidates:
        if c.lower() in exact:
            return True
    base = posixpath.basename(candidates[-1] if candidates else "").lower()
    if not base:
        return False
    matches = [x for x in items if posixpath.basename(x.original_path).lower() == base]
    return len(matches) == 1


def _resolve_local_candidate(local_index: dict, ref: str, current_resource: str = "") -> Optional[dict]:
    candidates = _logical_candidates(ref, current_resource)
    for c in candidates:
        rec = local_index["exact"].get(c.lower())
        if rec:
            return rec
    base = posixpath.basename(candidates[-1] if candidates else "").lower()
    return local_index["basename_unique"].get(base)


def collect_referenced_local_resources(
    raw_tab: Path,
    items: List[ResourceItem],
    mdx: Path,
    local_resource_dirs: Iterable[str],
    recursive: bool,
    resource_extensions: Iterable[str],
    output_dir: Path,
) -> Tuple[List[ResourceItem], dict]:
    """Import only local files actually referenced by Tabfile/text resources."""
    local_index = build_local_file_index(
        mdx, local_resource_dirs, recursive, resource_extensions,
        exclude_dirs=[output_dir],
    )
    queue: List[Tuple[str, str]] = []

    with raw_tab.open("r", encoding="utf-8-sig", errors="strict") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if "\t" not in line:
                continue
            _headword, definition = line.split("\t", 1)
            for ref in extract_resource_refs(definition):
                queue.append((ref, ""))

    for item in list(items):
        if item.source_path.suffix.lower() not in TEXT_RESOURCE_EXTENSIONS:
            continue
        text = safe_read_text(item.source_path)
        if text is not None:
            for ref in extract_resource_refs(text):
                queue.append((ref, item.original_path))

    imported: List[dict] = []
    seen_requests = set()
    added_paths = {str(x.source_path.resolve()) for x in items}

    while queue:
        ref, current_resource = queue.pop(0)
        request_key = (str(ref).lower(), str(current_resource).lower())
        if request_key in seen_requests:
            continue
        seen_requests.add(request_key)
        if _resource_exists_in_items(items, ref, current_resource):
            continue
        rec = _resolve_local_candidate(local_index, ref, current_resource)
        if not rec:
            continue
        source_path: Path = rec["path"]
        source_key = str(source_path.resolve())
        if source_key in added_paths:
            continue

        item = ResourceItem(source_path, rec["logical"], "[local]")
        items.append(item)
        added_paths.add(source_key)
        imported.append({
            "original_reference": ref,
            "current_resource": current_resource,
            "source_path": str(source_path),
            "logical_path": rec["logical"],
        })

        if source_path.suffix.lower() in TEXT_RESOURCE_EXTENSIONS:
            text = safe_read_text(source_path)
            if text is not None:
                for child_ref in extract_resource_refs(text):
                    queue.append((child_ref, rec["logical"]))

    return items, {
        "search_roots": local_index["roots"],
        "recursive": bool(recursive),
        "imported": imported,
    }


def rewrite_tabfile(src: Path, dst: Path, resolver: ResourceResolver) -> dict:
    total = malformed = entry_removed = 0
    with src.open("r", encoding="utf-8-sig", errors="strict") as fin, dst.open("w", encoding="utf-8", newline="\n") as fout:
        for line in fin:
            total += 1
            line = line.rstrip("\r\n")
            if "\t" not in line:
                malformed += 1
                fout.write(line + "\n")
                continue
            headword, definition = line.split("\t", 1)
            before = definition.lower().count("entry://")
            definition = rewrite_markup(definition, resolver)
            entry_removed += max(0, before - definition.lower().count("entry://"))
            fout.write(headword + "\t" + definition + "\n")
    return {"tab_lines": total, "tab_lines_without_tab": malformed, "entry_scheme_removed": entry_removed}


# ---------------- Dictionary icon ----------------
ICON_SOURCE_EXTENSIONS = (".bmp", ".png", ".jpg", ".jpeg")
ICON_SIZE = (48, 64)


def discover_dictionary_icon(mdx: Path) -> Optional[Path]:
    """Find an image beside the MDX with the same stem."""
    wanted_stem = mdx.stem.lower()
    candidates: Dict[str, Path] = {}

    for p in mdx.parent.iterdir():
        if not p.is_file():
            continue
        if p.stem.lower() != wanted_stem:
            continue
        ext = p.suffix.lower()
        if ext in ICON_SOURCE_EXTENSIONS and ext not in candidates:
            candidates[ext] = p

    for ext in ICON_SOURCE_EXTENSIONS:
        if ext in candidates:
            return candidates[ext]

    return None


def convert_dictionary_icon_to_bmp(
    source: Path,
    destination: Path,
    size: Tuple[int, int] = ICON_SIZE,
) -> Path:
    """
    Convert icon to a 48x64 24-bit BMP.
    Preserve aspect ratio and center it on a white 48x64 canvas.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError as e:
        raise RuntimeError(
            "检测到词典图标，但未安装 Pillow。请运行："
            "python -m pip install Pillow"
        ) from e

    destination.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as img:
        img = img.convert("RGBA")
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        fitted = ImageOps.contain(img, size, method=resample)

        canvas = Image.new("RGB", size, (255, 255, 255))
        x = (size[0] - fitted.width) // 2
        y = (size[1] - fitted.height) // 2

        if fitted.mode == "RGBA":
            canvas.paste(fitted.convert("RGB"), (x, y), fitted.getchannel("A"))
        else:
            canvas.paste(fitted.convert("RGB"), (x, y))

        canvas.save(destination, format="BMP")

    return destination


# ---------------- DSL / resource output ----------------
def make_dsl_shell(
    path: Path,
    name: str,
    index_dsl_name: str,
    contents_dsl_name: str,
) -> None:
    body = (
        f'#NAME "{name} Resources"\n'
        f'#INDEX_LANGUAGE "{index_dsl_name}"\n'
        f'#CONTENTS_LANGUAGE "{contents_dsl_name}"\n\n'
        '__ANDROID_GD_RESOURCES__\n'
        '\t[m1]Resource container[/m]\n'
    )
    # UTF-8 WITH BOM.
    path.write_text(body, encoding="utf-8-sig", newline="\n")


def prepare_resource_targets(
    items: List[ResourceItem],
    dsl_id: str,
    gd_root: str,
    install_dir: str,
) -> None:
    """Build final Android URL from each item's already-assigned output_path."""
    for item in items:
        if not item.output_path:
            raise RuntimeError(
                f"资源尚未分配输出路径：{item.original_path}"
            )

        if item.target_kind == "folder":
            item.target_url = file_url_from_device_path(
                device_abs_path(
                    gd_root,
                    posix_join(install_dir, item.output_path),
                )
            )
        else:
            encoded = urllib.parse.quote(
                item.output_path,
                safe="/:@-._~!$&'()*+,;=",
            )
            item.target_url = (
                f"{ANDROID_RESOURCE_PREFIX}/{dsl_id}/{encoded}"
            )


def build_resource_outputs(items: List[ResourceItem], output_dir: Path, zip_path: Path, resolver: ResourceResolver, rewrite_inside: bool) -> dict:
    text_rewritten = zip_count = folder_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in sorted(items, key=lambda x: x.output_path.lower()):
            source = item.source_path
            ext = source.suffix.lower()
            data = None
            if rewrite_inside and ext in TEXT_RESOURCE_EXTENSIONS:
                text = safe_read_text(source)
                if text is not None:
                    new = rewrite_markup(text, resolver, current_resource=item.original_path)
                    text_rewritten += int(new != text)
                    data = new.encode("utf-8")

            if item.target_kind == "folder":
                folder_count += 1
                dest = output_dir / item.output_path
                dest.write_bytes(data) if data is not None else shutil.copy2(source, dest)
            else:
                zip_count += 1
                if data is not None:
                    zf.writestr(item.output_path, data)
                else:
                    zf.write(source, arcname=item.output_path)

    return {
        "resource_files_total": len(items),
        "resource_files_in_zip": zip_count,
        "resource_files_in_folder": folder_count,
        "text_resource_files_rewritten": text_rewritten,
    }

def write_manual_stardict_tools(
    output_dir: Path,
    formal_dir_name: str,
    dictionary_name: str,
    stardict_base: str,
    tabfile_name: str,
    keep_dictzip: bool,
    html: bool,
    formal_dir_is_base: bool = False,
) -> Tuple[Path, Path]:
    helper_path = output_dir / "_makestardict.py"
    bat_path = output_dir / "makestardict.bat"

    helper_template = r'''# -*- coding: utf-8 -*-
from pathlib import Path
import shutil
import tempfile
from pyglossary import Glossary

BASE = Path(__file__).resolve().parent
TARGET = BASE if __FORMAL_IS_BASE__ else (BASE / __FORMAL_DIR__)
BOOKNAME = __BOOKNAME__
STARDICT_BASE = __STARDICT_BASE__
TABFILE = BASE / __TABFILE__
KEEP_DICTZIP = __KEEP_DICTZIP__
HTML = __HTML__


def enforce_bookname(ifo_path, bookname):
    text = ifo_path.read_text(encoding="utf-8-sig")
    lines = (
        text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    )

    replaced = False
    for i, line in enumerate(lines):
        if line.startswith("bookname="):
            lines[i] = "bookname=" + bookname
            replaced = True
            break

    if not replaced:
        insert_index = 2 if len(lines) >= 2 else len(lines)
        lines.insert(insert_index, "bookname=" + bookname)

    while lines and lines[-1] == "":
        lines.pop()

    ifo_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def convert(tabfile, ifo_path, dictzip):
    glos = Glossary()

    opts = {
        "dictzip": bool(dictzip)
    }
    if HTML:
        opts["sametypesequence"] = "h"

    result = glos.convert(
        inputFilename=str(tabfile),
        outputFilename=str(ifo_path),
        inputFormat="Tabfile",
        outputFormat="Stardict",
        writeOptions=opts,
    )

    if result is False or not ifo_path.exists():
        raise RuntimeError(
            "PyGlossary Tabfile -> StarDict conversion failed"
        )


def main():
    if not TABFILE.is_file():
        raise FileNotFoundError(
            f"Tabfile not found: {TABFILE}"
        )

    Glossary.init()
    TARGET.mkdir(
        parents=True,
        exist_ok=True,
    )

    for suffix in (
        ".ifo",
        ".idx",
        ".idx.gz",
        ".dict",
        ".dict.dz",
        ".syn",
        ".res.zip",
    ):
        p = TARGET / (
            STARDICT_BASE + suffix
        )
        if p.exists():
            p.unlink()

    final_ifo = TARGET / (
        STARDICT_BASE + ".ifo"
    )

    convert(
        TABFILE,
        final_ifo,
        dictzip=False,
    )

    enforce_bookname(
        final_ifo,
        BOOKNAME,
    )

    if KEEP_DICTZIP:
        with tempfile.TemporaryDirectory(
            prefix="makestardict_"
        ) as td:
            td = Path(td)

            temp_ifo = td / (
                STARDICT_BASE + ".ifo"
            )

            convert(
                TABFILE,
                temp_ifo,
                dictzip=True,
            )

            dz = td / (
                STARDICT_BASE + ".dict.dz"
            )

            if not dz.exists():
                raise RuntimeError(
                    ".dict.dz was not generated. "
                    "Install python-idzip: "
                    "python -m pip install python-idzip"
                )

            shutil.copy2(
                dz,
                TARGET / dz.name,
            )

    print("StarDict conversion complete.")
    print("Book name:", BOOKNAME)
    print("StarDict basename:", STARDICT_BASE)
    print("Source:", TABFILE)
    print("Output:", TARGET)


if __name__ == "__main__":
    main()
'''

    helper_code = (
        helper_template
        .replace(
            "__FORMAL_DIR__",
            repr(formal_dir_name),
        )
        .replace(
            "__FORMAL_IS_BASE__",
            repr(bool(formal_dir_is_base)),
        )
        .replace(
            "__BOOKNAME__",
            repr(dictionary_name),
        )
        .replace(
            "__STARDICT_BASE__",
            repr(stardict_base),
        )
        .replace(
            "__TABFILE__",
            repr(tabfile_name),
        )
        .replace(
            "__KEEP_DICTZIP__",
            repr(bool(keep_dictzip)),
        )
        .replace(
            "__HTML__",
            repr(bool(html)),
        )
    )

    helper_path.write_text(
        helper_code,
        encoding="utf-8",
        newline="\n",
    )

    bat = r'''@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 goto USE_PY
python "%~dp0_makestardict.py"
goto DONE
:USE_PY
py -3 "%~dp0_makestardict.py"
:DONE
pause
'''

    bat_path.write_text(
        bat,
        encoding="utf-8-sig",
        newline="\r\n",
    )

    return bat_path, helper_path

def resolve_path(value: Optional[str], base: Path) -> Optional[Path]:
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else (base / p).resolve()


def write_install_location_txt(
    output_dir: Path,
    device_install_dir: str,
    required_files: List[str],
) -> Path:
    """Write a human-readable Android GoldenDict deployment note."""
    note_path = output_dir / "GoldenDict安装位置.txt"

    lines = [
        "Android GoldenDict 词典安装位置",
        "=" * 40,
        "",
        "请将以下词典文件放到：",
        "",
        device_install_dir,
        "",
        "需要复制的文件：",
    ]

    for filename in required_files:
        lines.append("  " + filename)

    lines.extend([
        "",
        "说明：",
        "1. DSL、DSL资源ZIP、StarDict文件，以及 css_storage=folder 时的外置CSS，均放在上述同一目录。",
        "2. 正式词典文件均已集中输出；请按本文件列出的文件复制到上述 Android 目录。",
        "3. 词典.android.txt、makestardict.bat、_makestardict.py、conversion_report.json 仅供电脑端编辑/转换/检查，不需要复制到 Android。",
        "",
    ])

    note_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
        newline="\n",
    )
    return note_path


# ---------------- Main build ----------------
def build(
    cfg: dict,
    config_base: Path,
    source_override: Optional[Path] = None,
    target_ifo_override: Optional[Path] = None,
) -> Path:
    """
    Build in either mode:

    Config mode:
      - source_file is required in config.txt
        (legacy source_mdx is still accepted)
      - MDX / Tabfile / MDict Textfile are supported
      - dictionary_name blank -> source file stem
      - output_dir blank -> <source_dir>/<source_stem>
      - formal dictionary dir -> <output_dir>/<dictionary_name>

    Direct mode:
      mdxtogd.py SOURCE_FILE TARGET.ifo
      - TARGET.ifo is the exact final IFO path
      - dictionary name = TARGET stem
      - formal dictionary dir = TARGET parent
      - support/process files live in TARGET parent as well
        (no extra nesting, because the target path is explicit)
      - all other generic options can still come from config.txt if present
    """
    verify_android_hash_algorithm()
    config_base = Path(config_base).resolve()

    if source_override is not None:
        source = Path(source_override)
        if not source.is_absolute():
            source = (Path.cwd() / source).resolve()
    else:
        source_value = str(
            cfg.get('source_file', '') or
            cfg.get('source_mdx', '') or
            ''
        ).strip()
        if not source_value:
            raise ValueError(
                'config.txt 中 source_file 为必填项'
            )
        source = resolve_path(source_value, config_base)

    if not source or not source.is_file():
        raise FileNotFoundError(f"输入文件不存在：{source}")

    input_type_setting = normalize_input_type(
        cfg.get('input_type', 'auto')
    )
    source_type = detect_source_type(
        source,
        input_type_setting,
    )

    direct_mode = target_ifo_override is not None

    if direct_mode:
        target_ifo = Path(target_ifo_override)
        if not target_ifo.is_absolute():
            target_ifo = (Path.cwd() / target_ifo).resolve()
        if target_ifo.suffix.lower() != '.ifo':
            raise ValueError('快捷模式第二个参数必须以 .ifo 结尾')

        name = target_ifo.stem
        formal_output = target_ifo.parent
        output = formal_output
        formal_output.mkdir(parents=True, exist_ok=True)
    else:
        configured_name = str(cfg.get('dictionary_name', '') or '').strip()
        name = configured_name or source.stem

        configured_output = str(cfg.get('output_dir', '') or '').strip()
        if configured_output:
            output = resolve_path(configured_output, config_base)
        else:
            # "output_dir same as source_mdx": sibling folder named after MDX stem.
            output = source.parent / source.stem

        assert output is not None
        output.mkdir(parents=True, exist_ok=True)

        # Process/support files stay in output root.
        # Formal dictionary artifacts live in a same-name subdirectory.
        formal_output = output / name
        formal_output.mkdir(parents=True, exist_ok=True)

    gd_root = str(
        cfg.get('device_goldendict_root', '') or
        '/storage/emulated/0/GoldenDict'
    ).replace('\\', '/').rstrip('/')

    # INDEX_LANGUAGE / CONTENTS_LANGUAGE are strongly recommended.
    # If blank, infer from source/dictionary name; unresolved -> Unk / Unk.
    languages = resolve_languages(cfg, source, name)
    index_language = languages["index_code"]
    contents_language = languages["contents_code"]

    stardict_base, stardict_lang_tag = stardict_basename(
        name,
        index_language,
        contents_language,
    )

    install_value = str(cfg.get('install_dir', '') or '').strip()
    if install_value:
        install_value = expand_install_template(
            install_value,
            name,
            index_language,
            contents_language,
        )
        install_dir = canonical_resource_path(install_value)
    else:
        # Default Android folder hierarchy:
        #   <INDEX>/<INDEX>-<CONTENTS>/<dictionary_name>
        #
        # Example:
        #   eng + zho -> ENG/ENG-ZHO/词典名
        #   eng + eng -> ENG/ENG-ENG/词典名
        #   Unk + Unk -> UNK/UNK-UNK/词典名
        index_folder = str(index_language).upper()
        pair_folder = (
            f'{str(index_language).upper()}-'
            f'{str(contents_language).upper()}'
        )
        install_dir = canonical_resource_path(
            f'{index_folder}/{pair_folder}/{name}'
        )

    css_storage = normalize_css_storage(cfg.get('css_storage', 'zip'))
    resource_layout = normalize_resource_layout(
        cfg.get('resource_layout', 'root')
    )
    local_resource_dirs = cfg.get('local_resource_dirs', ['.']) or ['.']
    local_resource_recursive = bool(cfg.get('local_resource_recursive', True))

    # Resource shell filenames are always derived from dictionary_name.
    dsl_name = f"{name}.dsl"
    zip_name = f"{name}.dsl.files.zip"

    # Formal dictionary files live in output_dir/<dictionary_name>/.
    dsl_path = formal_output / dsl_name
    zip_path = formal_output / zip_name

    dsl_hash_input = canonical_resource_path(posix_join(install_dir, dsl_name))
    dsl_id = android_goldendict_resource_id(dsl_hash_input)
    device_install_dir = device_abs_path(gd_root, install_dir)
    device_dsl_path = device_abs_path(gd_root, dsl_hash_input)

    log("=" * 72)
    log(f"Dictionary       : {name}")
    log(f"Source file      : {source}")
    log(f"Input type       : {source_type}")
    log(f"Output directory : {output}")
    log(f"Formal dictionary: {formal_output}")
    log(f"Languages        : {index_language} -> {contents_language} "
        f"(DSL: {languages['index_dsl_name']} -> {languages['contents_dsl_name']})")
    log(f"Language source  : INDEX={languages['index_source']}, "
        f"CONTENTS={languages['contents_source']}, "
        f"reason={languages['inference_reason']}")
    log(
        f"StarDict basename: {stardict_base}"
        + (
            f"  [{stardict_lang_tag}]"
            if stardict_lang_tag
            else "  [no language tag]"
        )
    )
    log(f"Android install  : {device_install_dir}")
    log(f"CSS storage      : {css_storage}")
    log(f"Resource layout  : {resource_layout}")
    log(f"Local resources  : {local_resource_dirs} (recursive={local_resource_recursive})")
    log(f"DSL hash input   : {dsl_hash_input}")
    log(f"DSL resource ID  : {dsl_id}")
    log("=" * 72)

    make_dsl_shell(
        dsl_path,
        name,
        languages["index_dsl_name"],
        languages["contents_dsl_name"],
    )

    source_icon = discover_dictionary_icon(source)
    final_icon = None
    if source_icon:
        # Keep icon basename aligned with StarDict basename:
        #   dictionary.en-zh.ifo
        #   dictionary.en-zh.bmp
        final_icon = formal_output / f"{stardict_base}.bmp"
        convert_dictionary_icon_to_bmp(source_icon, final_icon)

        # Remove the old clean-name icon from previous versions so one
        # dictionary directory does not contain two competing icons.
        legacy_icon = formal_output / f"{name}.bmp"
        if legacy_icon != final_icon and legacy_icon.exists():
            legacy_icon.unlink()

        log(
            f"Dictionary icon  : {source_icon.name} "
            f"-> {final_icon.name} (48x64 BMP)"
        )
    else:
        # Remove both possible stale names.
        stale_icons = {
            formal_output / f"{name}.bmp",
            formal_output / f"{stardict_base}.bmp",
        }
        for stale_icon in stale_icons:
            if stale_icon.exists():
                stale_icon.unlink()
        log("Dictionary icon  : none")

    mdds = discover_companion_mdds(source)
    log("Companion MDDs   : " + (", ".join(p.name for p in mdds) if mdds else "none"))

    with tempfile.TemporaryDirectory(prefix="mdx2gd_work_") as td:
        work = Path(td)
        raw_tab = work / f"{name}.raw.txt"
        android_tab = work / f"{name}.android.txt"

        log(f"[1/8] Prepare source -> Tabfile ({source_type})")
        source_conversion_report = prepare_source_tabfile(
            source,
            raw_tab,
            source_type,
        )

        if (
            source_type == "textfile" and
            source_conversion_report.get("missing_final_delimiter_accepted")
        ):
            log("      ⚠️ 最后一条记录没有 </>，已按有效末条接受")

        log("[2/8] MDD discovery / extraction")
        items = collect_resources_from_mdds(mdds, work / "mdd_extract") if mdds else []
        log(f"      logical resources: {len(items)}")

        log("[3/8] Resolve referenced local resources")
        items, local_resource_report = collect_referenced_local_resources(
            raw_tab,
            items,
            source,
            local_resource_dirs,
            local_resource_recursive,
            sorted(DEFAULT_RESOURCE_EXTENSIONS),
            output,
        )
        log(f"      imported local resources: {len(local_resource_report['imported'])}")

        log("[4/8] Assign resource layout + detect filename collisions")
        renamed_resources = assign_resource_output_paths(
            items, resource_layout, css_storage
        )
        prepare_resource_targets(items, dsl_id, gd_root, install_dir)
        resolver = ResourceResolver(dsl_id, items, sorted(DEFAULT_RESOURCE_EXTENSIONS))

        log("[5/8] Rewrite Tabfile + entry:// + resource URLs")
        tab_report = rewrite_tabfile(raw_tab, android_tab, resolver)

        log("[6/8] Build DSL resource ZIP / optional CSS files")
        resource_report = build_resource_outputs(
            items, formal_output, zip_path, resolver,
            rewrite_inside=bool(cfg.get("rewrite_inside_resources", True))
        )

        log("[7/8] Preserve editable Tabfile + build StarDict")
        final_tab = output / f"{name}.android.txt"
        shutil.copy2(android_tab, final_tab)

        keep_dictzip = bool(cfg.get("stardict_dictzip", True))
        stardict_html = bool(cfg.get("stardict_html", True))
        stardict_files = build_stardict(
            final_tab,
            formal_output,
            stardict_base,
            name,
            keep_dictzip=keep_dictzip,
            html=stardict_html,
        )

        bat_path, helper_path = write_manual_stardict_tools(
            output,
            formal_output.name,
            name,
            stardict_base,
            final_tab.name,
            keep_dictzip,
            stardict_html,
            formal_dir_is_base=direct_mode,
        )

        if cfg.get("keep_raw_tabfile", False):
            shutil.copy2(raw_tab, output / f"{name}.raw.txt")

    report = {
        "dictionary_name": name,
        "invocation_mode": "direct" if direct_mode else "config",
        "source_file": str(source),
        "source_type": source_type,
        "source_conversion": source_conversion_report,
        "source_mdx": str(source) if source_type == "mdx" else None,
        "source_mdds": [str(x) for x in mdds],
        "output_dir": str(output),
        "formal_dictionary_dir": str(formal_output),
        "android": {
            "goldendict_root": gd_root,
            "install_dir": install_dir,
            "device_install_dir": device_install_dir,
        },
        "resource_shell": {
            "dsl_file": dsl_name,
            "zip_file": zip_name,
            "device_dsl_path": device_dsl_path,
            "android_hash_input": dsl_hash_input,
            "resource_id": dsl_id,
            "resource_url_prefix": f"{ANDROID_RESOURCE_PREFIX}/{dsl_id}/",
            "dsl_encoding": "utf-8 with BOM",
            "index_language_code": index_language,
            "contents_language_code": contents_language,
            "index_language_dsl": languages["index_dsl_name"],
            "contents_language_dsl": languages["contents_dsl_name"],
            "index_language_source": languages["index_source"],
            "contents_language_source": languages["contents_source"],
            "language_inference_reason": languages["inference_reason"],
        },
        "dictionary_icon": {
            "source": str(source_icon) if source_icon else None,
            "output": final_icon.name if final_icon else None,
            "basename_follows_stardict": True,
            "language_tag": stardict_lang_tag,
            "size": [48, 64] if final_icon else None,
            "format": "BMP" if final_icon else None,
        },
        "css_storage": {
            "mode": css_storage,
            "folder_files": [x.output_path for x in items if x.target_kind == "folder"],
        },
        "stardict": {
            "dictzip_requested": bool(cfg.get("stardict_dictzip", True)),
            "bookname": name,
            "basename": stardict_base,
            "goldendict_language_tag": stardict_lang_tag,
            "files": [p.name for p in stardict_files],
            "editable_tabfile": final_tab.name,
            "manual_batch": bat_path.name,
            "manual_helper": helper_path.name,
        },
        "local_resources": local_resource_report,
        "resources": {
            "layout": resource_layout,
            **resource_report,
            "renamed_due_to_layout_or_collision": renamed_resources,
            "ambiguous_basenames": sorted(resolver.basename_ambiguous),
        },
        "rewrite": {
            **tab_report,
            "resource_reference_replacements": resolver.replaced_count,
            "unresolved_local_resource_refs": sorted(resolver.unresolved),
        },
    }
    report_path = output / "conversion_report.json"
    save_json(report_path, report)

    # Human-readable Android deployment note.
    required_android_files = [
        dsl_name,
        zip_name,
    ]

    for p in stardict_files:
        if p.name not in required_android_files:
            required_android_files.append(p.name)

    if final_icon and final_icon.name not in required_android_files:
        required_android_files.append(final_icon.name)

    for item in items:
        if (
            item.target_kind == "folder" and
            item.output_path not in required_android_files
        ):
            required_android_files.append(item.output_path)

    install_note_path = write_install_location_txt(
        output,
        device_install_dir,
        required_android_files,
    )

    report["android"]["install_note"] = install_note_path.name
    save_json(report_path, report)

    log("[8/8] Complete")
    log(f"      report: {report_path}")
    log(f"      install note: {install_note_path}")
    if resolver.unresolved:
        log("⚠️ 未解析本地资源：")
        for x in sorted(resolver.unresolved):
            log("   - " + x)
    return output


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "MDX/Tabfile/Textfile -> Android GoldenDict converter. "
            "No args: read config.txt. "
            "Shortcut: mdxtogd.py SOURCE_FILE TARGET.ifo"
        )
    )
    ap.add_argument('source_file', nargs='?', help='快捷模式：源 MDX / Tabfile / Textfile')
    ap.add_argument('target_ifo', nargs='?', help='快捷模式：输出目录/词典名锚点；语言可识别时实际IFO会自动变为 name.en-zh.ifo')
    ap.add_argument(
        '--config',
        default='config.txt',
        help='配置文件（默认：config.txt）',
    )
    ap.add_argument(
        '--hash',
        metavar='RELATIVE_DSL_PATH',
        help='只计算 Android GoldenDict DSL resource ID',
    )
    args = ap.parse_args()

    if args.hash:
        verify_android_hash_algorithm()
        print(android_goldendict_resource_id(args.hash))
        return 0

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()

    direct_mode = bool(args.source_file or args.target_ifo)

    try:
        if direct_mode:
            if not (args.source_file and args.target_ifo):
                raise ValueError(
                    '快捷模式必须同时提供 SOURCE_FILE 和 TARGET.ifo'
                )
            # Generic options may still be taken from config.txt if it exists.
            cfg = load_text_config(config_path, required=False)
            return_path = build(
                cfg,
                config_path.parent,
                source_override=Path(args.source_file),
                target_ifo_override=Path(args.target_ifo),
            )
        else:
            cfg = load_text_config(config_path, required=True)
            return_path = build(
                cfg,
                config_path.parent,
            )
        return 0
    except Exception as e:
        print(f"\\n❌ 转换失败：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
