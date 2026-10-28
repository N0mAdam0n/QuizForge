"""判断题被误判为单选题的回归测试(LLM 导入 / 结构化导入 / 安全网)。"""
import json
import pytest

from app.models.question import QuestionType
from app.services.importing.normalize import apply_true_false_safety_net, coerce_q_type
from app.services.importing.qtype_utils import is_tf_option_pair, resolve_tf_answer
from app.services.importing.review import extracted_to_v2_review
from app.services.structured_parser import _map_q_type, parse_structured


@pytest.mark.parametrize(
    "raw",
    ["判断题", "判断", "是非题", "对错题", "TF", "t/f", "judge", "judgment", "boolean", "true_false", "True/False"],
)
def test_coerce_q_type_true_false_keywords(raw):
    assert coerce_q_type(raw) == QuestionType.TRUE_FALSE


def test_coerce_q_type_other_cn_keywords():
    assert coerce_q_type("单选题") == QuestionType.SINGLE_CHOICE
    assert coerce_q_type("多选题") == QuestionType.MULTIPLE_CHOICE
    assert coerce_q_type(None) == QuestionType.SINGLE_CHOICE


def test_coerce_q_type_fallback_logs_warning(monkeypatch):
    from app.services.importing import normalize

    calls = []
    monkeypatch.setattr(normalize.logger, "warning", lambda msg, *a: calls.append(msg % a))
    assert coerce_q_type("weird") == QuestionType.SINGLE_CHOICE
    assert any("unrecognized q_type" in c for c in calls)


def test_llm_import_with_chinese_tf_type_becomes_true_false():
    items = extracted_to_v2_review([{"content": "0 是自然数", "q_type": "判断题", "answer": "对"}])
    assert items[0]["q_type"] == "true_false"
    assert items[0]["answer"] == {"kind": "true_false", "correct": True}


def test_structured_import_tf_options_without_tag():
    q = parse_structured("【题目】地球是圆的\n【选项】A. 对 B. 错\n【答案】B").questions[0]
    assert q["q_type"] == "true_false"
    assert q["options"] == []
    assert q["answer"] == "错"


@pytest.mark.parametrize("tag", ["判断题（每题2分）", "判断题(共5题)", "判断题 2分", "是非题", "判断对错"])
def test_map_q_type_tolerates_noise(tag):
    assert _map_q_type(tag) == "true_false"


def test_map_q_type_single_with_score():
    assert _map_q_type("单选题（每题3分）") == "single_choice"


def test_structured_import_tf_tag_with_score():
    q = parse_structured("【题型】判断题（每题2分）\n【题目】0 是自然数\n【答案】√").questions[0]
    assert q["q_type"] == "true_false"


@pytest.mark.parametrize(
    "options,answer,expected",
    [
        (["A. 对", "B. 错"], "A", "对"),
        (["A、正确", "B、错误"], "B", "错"),
        ([{"label": "A", "content": "√"}, {"label": "B", "content": "×"}], "B", "错"),
        (["T", "F"], "T", "对"),
        (["A. true", "B. false"], "false", "错"),
    ],
)
def test_safety_net_reclassifies_tf_option_pairs(options, answer, expected):
    qt, opts, ans = apply_true_false_safety_net(QuestionType.SINGLE_CHOICE, options, answer)
    assert qt == QuestionType.TRUE_FALSE
    assert opts is None
    assert ans == expected


def test_safety_net_optionless_tf_answer():
    qt, opts, ans = apply_true_false_safety_net(QuestionType.SINGLE_CHOICE, None, "×")
    assert (qt, opts, ans) == (QuestionType.TRUE_FALSE, None, "错")


def test_safety_net_leaves_real_single_choice_alone():
    opts = ["A. 1", "B. 2"]
    assert apply_true_false_safety_net(QuestionType.SINGLE_CHOICE, opts, "A") == (
        QuestionType.SINGLE_CHOICE, opts, "A")
    assert not is_tf_option_pair(["A. 对", "B. 错", "C. 不确定"])


def test_review_end_to_end_single_choice_with_tf_options():
    items = extracted_to_v2_review(
        [{"content": "水在 100℃ 沸腾", "q_type": "single_choice", "options": ["A. 正确", "B. 错误"], "answer": "A"}]
    )
    assert items[0]["q_type"] == "true_false"
    assert items[0]["options"] in (None, [])
    assert items[0]["answer"] == {"kind": "true_false", "correct": True}


def test_resolve_tf_answer_unknown():
    assert resolve_tf_answer("C", ["A. 对", "B. 错"]) is None


def test_repair_plan_fix():
    from scripts.fix_true_false_types import plan_fix
    from app.services.question_content_converter import convert_options

    opts = convert_options([{"label": "A", "content": "对"}, {"label": "B", "content": "错"}])
    ans = json.dumps({"kind": "single_choice", "correct": opts[1]["id"]})
    plan = plan_fix(QuestionType.SINGLE_CHOICE, opts, ans)
    assert plan["answer"] == {"kind": "true_false", "correct": False}
    assert plan["needs_review"] is True

    real = convert_options([{"label": "A", "content": "1"}, {"label": "B", "content": "2"}])
    assert plan_fix(QuestionType.SINGLE_CHOICE, real, None) is None
    assert plan_fix(QuestionType.TRUE_FALSE, opts, ans) is None
