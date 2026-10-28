"""修复被误存为单选/多选题的判断题。

默认 dry-run:只列出候选题(id、题干片段、选项、答案、来源),不写库。
加 --apply 才会改写:q_type → true_false,options → NULL,answer → true_false AnswerSpec,
needs_review → True(无法确定对错时答案降级为 legacy_unresolved),content_revision +1。

    cd backend && python scripts/fix_true_false_types.py            # dry-run
    cd backend && python scripts/fix_true_false_types.py --apply    # 写库(先备份!)

使用应用自身的数据库配置(.env / 环境变量,与后端一致)。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import null, select  # noqa: E402

from app.db.session import SessionLocal, engine  # noqa: E402
from app.models.question import Question, QuestionType  # noqa: E402
from app.services.importing.qtype_utils import (  # noqa: E402
    is_tf_answer,
    is_tf_option_pair,
    option_text,
    token_to_bool,
)
from app.services.question_content_converter import (  # noqa: E402
    markdown_to_rich_doc,
    rich_doc_to_plain_text,
)

CHOICE = (QuestionType.SINGLE_CHOICE, QuestionType.MULTIPLE_CHOICE)


def _load(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _plain(doc: Any) -> str:
    doc = _load(doc)
    if isinstance(doc, dict):
        return rich_doc_to_plain_text(doc)
    return "" if doc is None else str(doc)


def plan_fix(q_type: QuestionType, options: Any, answer: Any) -> Optional[dict]:
    """返回修复计划 {answer, needs_review, reason};不是候选返回 None。"""
    if q_type not in CHOICE:
        return None
    opts = _load(options) or []
    ans = _load(answer)
    if not isinstance(opts, list):
        opts = []

    value: Optional[bool] = None
    raw_text = ""
    if opts:
        if not is_tf_option_pair(opts):
            return None
        reason = "T/F option pair"
        if isinstance(ans, dict):
            correct = ans.get("correct")
            if isinstance(correct, list) and len(correct) == 1:
                correct = correct[0]
            for o in opts:
                if isinstance(o, dict) and o.get("id") == correct:
                    raw_text = option_text(o)
                    value = token_to_bool(raw_text)
            if ans.get("kind") == "legacy_unresolved":
                raw_text = _plain(ans.get("raw"))
                value = token_to_bool(raw_text)
    else:
        raw_text = _plain(ans.get("raw")) if isinstance(ans, dict) and ans.get("kind") == "legacy_unresolved" else ""
        if not is_tf_answer(raw_text):
            return None
        reason = "no options + T/F answer"
        value = token_to_bool(raw_text)

    if value is None:
        new_answer: Optional[dict] = (
            {"kind": "legacy_unresolved", "expected_kind": "true_false", "raw": markdown_to_rich_doc(raw_text)}
            if raw_text else None
        )
    else:
        new_answer = {"kind": "true_false", "correct": value}
    return {"answer": new_answer, "needs_review": True, "reason": reason}


async def main(apply: bool) -> int:
    has_needs_review = hasattr(Question, "needs_review")
    changed = 0
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(Question).where(Question.q_type.in_(CHOICE), Question.deleted_at.is_(None))
        )).scalars().all()
        for q in rows:
            plan = plan_fix(q.q_type, q.options, q.answer)
            if plan is None:
                continue
            changed += 1
            opts = [option_text(o) for o in (_load(q.options) or [])]
            print(f"#{q.id} [{q.q_type.value}] {_plain(q.content)[:40]!r} options={opts} "
                  f"answer={str(q.answer)[:80]} source={getattr(q, 'source', None)!r} "
                  f"-> {json.dumps(plan['answer'], ensure_ascii=False)[:60]} ({plan['reason']})")
            if apply:
                q.q_type = QuestionType.TRUE_FALSE
                q.options = null()
                q.answer = json.dumps(plan["answer"], ensure_ascii=False) if plan["answer"] else None
                if has_needs_review:
                    q.needs_review = True
                if hasattr(Question, "content_revision"):
                    q.content_revision = (q.content_revision or 1) + 1
        if apply:
            await db.commit()
    await engine.dispose()
    mode = "APPLIED" if apply else "DRY-RUN (use --apply to write)"
    print(f"\n{mode}: {changed} candidate question(s).")
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="actually write changes (default: dry-run)")
    args = parser.parse_args()
    if args.apply:
        print("!! 备份提醒:写库前请先备份数据库(MySQL: mysqldump;SQLite: 复制 .db 文件)。")
        if input("已备份,确认写入? 输入 yes 继续: ").strip().lower() != "yes":
            print("已取消。")
            sys.exit(1)
    asyncio.run(main(args.apply))
