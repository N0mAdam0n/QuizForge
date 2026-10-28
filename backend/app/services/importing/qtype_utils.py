"""判断题识别的共享工具:关键词、对/错选项对、判断题答案集合。

被 LLM 导入归一化(normalize / review)、结构化解析(structured_parser)
以及修复脚本共用,避免各处规则漂移导致判断题被误存为单选题。
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

# 题型字符串中出现即视为判断题的关键词(小写匹配)。
TF_TYPE_KEYWORDS: tuple[str, ...] = (
    "true", "false", "判断", "是非", "对错", "t/f", "judg", "bool",
)
# 需要整词匹配的短关键词,避免误伤。
TF_TYPE_EXACT: frozenset[str] = frozenset({"tf", "t_f", "t-f", "judge"})

TF_ANSWERS: frozenset[str] = frozenset({
    "对", "错", "正确", "错误", "√", "×", "✓", "✗", "T", "F", "t", "f",
    "true", "false", "True", "False", "TRUE", "FALSE",
    "是", "否", "yes", "no", "Y", "N",
})

_TRUE_TOKENS = {"对", "正确", "√", "✓", "t", "true", "是", "yes", "y"}
_FALSE_TOKENS = {"错", "错误", "×", "✗", "f", "false", "否", "no", "n"}

# 合法的 (真, 假) 选项对。
_TF_PAIRS: tuple[frozenset[str], ...] = tuple(
    frozenset(p) for p in (
        ("对", "错"), ("正确", "错误"), ("√", "×"), ("✓", "✗"),
        ("t", "f"), ("true", "false"), ("是", "否"), ("yes", "no"),
    )
)

_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:[\(（][A-Za-z][\)）]|[A-Za-z]\s*[\.．、:：\)）]|[A-Za-z]\s+)\s*"
)
_TRAILING_PUNCT_RE = re.compile(r"[\s。\.!！]+$")


def is_tf_type_keyword(raw: Any) -> bool:
    s = str(raw or "").strip().lower()
    if not s:
        return False
    if s in TF_TYPE_EXACT:
        return True
    return any(k in s for k in TF_TYPE_KEYWORDS)


def _rich_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return str(node.get("text", ""))
        return "".join(_rich_text(c) for c in node.get("content", []) or [])
    if isinstance(node, list):
        return "".join(_rich_text(c) for c in node)
    return ""


def option_text(opt: Any) -> str:
    """取选项正文:支持 "A. 对"、{label, content(md)}、v2 {id,label,content:RichDoc}。"""
    if isinstance(opt, dict):
        content = opt.get("content", opt.get("text", ""))
        text = _rich_text(content) if not isinstance(content, str) else content
        label = str(opt.get("label", "") or "")
        if not text and label:
            text = label
    else:
        text = "" if opt is None else str(opt)
    return text


def _norm_token(text: str, *, strip_label: bool = True) -> str:
    s = text.strip()
    if strip_label:
        stripped = _LABEL_PREFIX_RE.sub("", s, count=1)
        # 仅当剥离后仍有内容时才采用(避免把 "T"/"F" 本身当成标签剥掉)。
        if stripped.strip() and stripped != s:
            s = stripped
    s = _TRAILING_PUNCT_RE.sub("", s).strip()
    return s.lower()


def tf_pair_texts(options: Optional[Iterable[Any]]) -> Optional[list[str]]:
    """若选项恰为 2 个且构成对/错类选项对,返回归一化后的两段文本,否则 None。"""
    if not options:
        return None
    opts = list(options)
    if len(opts) != 2:
        return None
    texts = [_norm_token(option_text(o)) for o in opts]
    if frozenset(texts) in _TF_PAIRS and texts[0] != texts[1]:
        return texts
    return None


def is_tf_option_pair(options: Optional[Iterable[Any]]) -> bool:
    return tf_pair_texts(options) is not None


def is_tf_answer(answer: Any) -> bool:
    return isinstance(answer, str) and answer.strip() in TF_ANSWERS


def token_to_bool(text: str) -> Optional[bool]:
    t = _norm_token(text)
    if t in _TRUE_TOKENS:
        return True
    if t in _FALSE_TOKENS:
        return False
    return None


def resolve_tf_answer(answer: Any, options: Optional[list[Any]] = None) -> Optional[str]:
    """把选择题形式的答案(字母 A/B 或选项文本)转为判断题原始答案("对"/"错")。

    返回 None 表示无法确定。
    """
    if answer is None:
        return None
    if isinstance(answer, bool):
        return "对" if answer else "错"
    raw = str(answer).strip()
    if not raw:
        return None
    direct = token_to_bool(raw)
    if direct is not None:
        return "对" if direct else "错"
    texts = tf_pair_texts(options) if options else None
    if texts:
        letter = re.sub(r"[^A-Za-z]", "", raw).upper()
        labels = []
        for i, o in enumerate(options or []):
            lab = str(o.get("label", "") or "").strip().upper() if isinstance(o, dict) else ""
            if not lab:
                m = re.match(r"^\s*[\(（]?([A-Za-z])[\)）]?\s*[\.．、:：\)）]", option_text(o))
                lab = m.group(1).upper() if m else chr(ord("A") + i)
            labels.append(lab)
        if len(letter) == 1 and letter in labels:
            val = token_to_bool(texts[labels.index(letter)])
            if val is not None:
                return "对" if val else "错"
    return None
