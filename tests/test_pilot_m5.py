"""Pilot M5 测试：Plan Profile 化、TemplatePlanGateway、OpenAIModelGateway。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent_hub.pilot.domain.enums import PlanStepKind
from agent_hub.pilot.services.dto import PlanBlueprint, PlanProfile, PlanStepDraft
from agent_hub.pilot.services.model_gateway import (
    OpenAIModelGateway,
    PlanContext,
    TemplatePlanGateway,
    derive_plan_profile,
)
from agent_hub.pilot.services.planning import (
    REQUIRED_KINDS_BY_PROFILE,
    PlanningService,
    PlanTemplateError,
)


def test_runtime_gateway_uses_real_chain_skill_mode() -> None:
    from agent_hub.api.pilot_runtime import build_pilot_runtime
    from agent_hub.config.settings import Settings

    runtime = build_pilot_runtime(
        Settings(
            pilot_store_path="",
            pilot_demo_mode=True,
            pilot_use_real_gateway=False,
            pilot_use_real_chain=True,
            feishu_enabled=False,
        ),
    )
    try:
        assert isinstance(runtime.gateway, TemplatePlanGateway)
        assert runtime.gateway.skill_mode == "real_chain"
    finally:
        asyncio.run(runtime.aclose())


# ── derive_plan_profile ──────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("帮我做个 PPT 汇报", PlanProfile.DECK_FULL),
        ("写一份产品 brief", PlanProfile.DOC_ONLY),
        ("总结一下今天的会议", PlanProfile.SUMMARY_ONLY),
        ("普通文本默认 deck_full", PlanProfile.DECK_FULL),
    ],
)
def test_derive_profile_by_keyword(text: str, expected: PlanProfile) -> None:
    ctx = PlanContext(raw_text=text, requester_id="u1")
    assert derive_plan_profile(ctx) == expected


def test_derive_profile_explicit_overrides_keywords() -> None:
    ctx = PlanContext(
        raw_text="帮我做 PPT",
        requester_id="u1",
        profile=PlanProfile.DOC_ONLY,
    )
    assert derive_plan_profile(ctx) == PlanProfile.DOC_ONLY


def test_derive_profile_revision_requires_base_artifact() -> None:
    ctx = PlanContext(
        raw_text="修改一下这份 brief",
        requester_id="u1",
        metadata={"base_brief_artifact_id": "art_1"},
    )
    assert derive_plan_profile(ctx) == PlanProfile.REVISION


# ── TemplatePlanGateway ──────────────────────────────


@pytest.mark.asyncio
async def test_template_gateway_deck_full_fake() -> None:
    gw = TemplatePlanGateway(skill_mode="fake")
    bp = await gw.complex_plan(
        PlanContext(raw_text="做一份 PPT", requester_id="u1", title="季度复盘"),
    )
    assert bp.profile == PlanProfile.DECK_FULL
    assert bp.metadata["gateway"] == "template"
    assert bp.metadata["skill_mode"] == "fake"
    kinds = {s.kind for s in bp.steps}
    assert REQUIRED_KINDS_BY_PROFILE[PlanProfile.DECK_FULL].issubset(kinds)
    assert all(s.skill_name.startswith("fake_") for s in bp.steps)


@pytest.mark.asyncio
async def test_template_gateway_deck_full_real_chain_uses_real_skills() -> None:
    gw = TemplatePlanGateway(skill_mode="real_chain")
    bp = await gw.complex_plan(
        PlanContext(raw_text="做一份 PPT", requester_id="u1", title="季度复盘"),
    )
    assert bp.metadata["skill_mode"] == "real_chain"
    by_kind = {s.kind: s.skill_name for s in bp.steps}
    assert by_kind[PlanStepKind.READ_CONTEXT] == "internal.context.assemble"
    assert by_kind[PlanStepKind.GENERATE_DOC] == "internal.brief.generate"
    assert by_kind[PlanStepKind.GENERATE_SLIDE_SPEC] == "real.slide.generate_spec"
    assert by_kind[PlanStepKind.RENDER_SLIDES] == "real.slide.render_pptx"
    assert by_kind[PlanStepKind.UPLOAD] == "real.drive.upload_share"
    assert by_kind[PlanStepKind.SUMMARIZE] == "feishu.im.send_message"


@pytest.mark.asyncio
async def test_template_gateway_feishu_tasks_private_deliver_to_requester() -> None:
    gw = TemplatePlanGateway(skill_mode="real_chain")
    bp = await gw.complex_plan(
        PlanContext(
            raw_text="做一份 PPT",
            requester_id="ou_requester",
            title="季度复盘",
            source_channel="feishu",
            source_conversation_id="oc_group",
            metadata={
                "feishu_private_receive_id": "ou_requester",
                "feishu_private_receive_id_type": "open_id",
                "feishu_requester_open_id": "ou_requester",
            },
        ),
    )

    by_kind = {s.kind: s for s in bp.steps}
    assert by_kind[PlanStepKind.READ_CONTEXT].skill_name == "feishu.im.fetch_recent"
    assert by_kind[PlanStepKind.READ_CONTEXT].input_params["chat_id"] == "oc_group"
    assert by_kind[PlanStepKind.UPLOAD].input_params["member_open_id"] == "ou_requester"
    summary_params = by_kind[PlanStepKind.SUMMARIZE].input_params
    assert summary_params["chat_id"] == "ou_requester"
    assert summary_params["receive_id_type"] == "open_id"


@pytest.mark.asyncio
async def test_template_gateway_feishu_private_file_uses_private_folder() -> None:
    gw = TemplatePlanGateway(skill_mode="real_chain")
    bp = await gw.complex_plan(
        PlanContext(
            raw_text="帮我写一份私人方案文档",
            requester_id="ou_leader",
            title="私人方案",
            source_channel="feishu",
            source_conversation_id="oc_p2p",
            metadata={
                "feishu_requester_open_id": "ou_leader",
                "feishu_private_folder_token": "folder-private-leader",
            },
        ),
    )

    upload = next(s for s in bp.steps if s.kind == PlanStepKind.UPLOAD)
    assert upload.input_params["folder_token"] == "folder-private-leader"
    assert upload.input_params["member_open_id"] == "ou_leader"
    assert "share_recipient_open_ids" not in upload.input_params


@pytest.mark.asyncio
async def test_template_gateway_feishu_shared_file_uses_shared_folder_and_recipients() -> None:
    gw = TemplatePlanGateway(skill_mode="real_chain")
    bp = await gw.complex_plan(
        PlanContext(
            raw_text="把选中的群消息生成共享文件",
            requester_id="ou_5f91fff5b8c696e875817ad56d745441",
            title="共享文件",
            source_channel="feishu",
            source_conversation_id="oc_group",
            metadata={
                "feishu_requester_open_id": "ou_5f91fff5b8c696e875817ad56d745441",
                "feishu_file_visibility": "shared",
                "feishu_shared_folder_token": "folder-shared-leader",
                "feishu_share_recipient_open_ids": "ou_sub_1,ou_sub_2",
            },
        ),
    )

    upload = next(s for s in bp.steps if s.kind == PlanStepKind.UPLOAD)
    assert upload.input_params["folder_token"] == "folder-shared-leader"
    assert upload.input_params["member_open_id"] == "ou_5f91fff5b8c696e875817ad56d745441"
    assert upload.input_params["share_recipient_open_ids"] == ["ou_sub_1", "ou_sub_2"]


@pytest.mark.asyncio
async def test_template_gateway_doc_only_only_two_steps() -> None:
    gw = TemplatePlanGateway(skill_mode="real_chain")
    bp = await gw.complex_plan(
        PlanContext(
            raw_text="写一份方案 brief",
            requester_id="u1",
            profile=PlanProfile.DOC_ONLY,
        ),
    )
    assert bp.profile == PlanProfile.DOC_ONLY
    # DOC_ONLY 也走 ctx → brief → upload(brief.md) → summary 四步，
    # 才能让用户在飞书侧拿到可访问链接。
    kinds = [s.kind for s in bp.steps]
    assert kinds == [
        PlanStepKind.READ_CONTEXT,
        PlanStepKind.GENERATE_DOC,
        PlanStepKind.UPLOAD,
        PlanStepKind.SUMMARIZE,
    ]
    upload = next(s for s in bp.steps if s.kind == PlanStepKind.UPLOAD)
    assert upload.skill_name == "real.drive.upload_share"
    assert upload.input_params.get("file_name", "").endswith(".md")
    assert upload.inputs_from == ["brief"]


@pytest.mark.asyncio
async def test_template_gateway_summary_only_uses_internal_summary() -> None:
    gw = TemplatePlanGateway(skill_mode="real_chain")
    bp = await gw.complex_plan(
        PlanContext(
            raw_text="总结一下昨天的讨论",
            requester_id="u1",
            profile=PlanProfile.SUMMARY_ONLY,
        ),
    )
    assert bp.profile == PlanProfile.SUMMARY_ONLY
    by_kind = {s.kind: s.skill_name for s in bp.steps}
    assert by_kind[PlanStepKind.SUMMARIZE] == "internal.summary.generate"


@pytest.mark.asyncio
async def test_template_gateway_revision_uses_brief_revise_skill() -> None:
    gw = TemplatePlanGateway(skill_mode="real_chain")
    bp = await gw.complex_plan(
        PlanContext(
            raw_text="把第三段改成更紧凑",
            requester_id="u1",
            profile=PlanProfile.REVISION,
            metadata={"base_brief_artifact_id": "art_old"},
        ),
    )
    assert bp.profile == PlanProfile.REVISION
    revise = next(s for s in bp.steps if s.kind == PlanStepKind.GENERATE_DOC)
    assert revise.skill_name == "internal.brief.revise"
    assert revise.input_params["base_brief_artifact_id"] == "art_old"


# ── PlanningService 校验：profile 化 ──────────────


def _make_blueprint(profile: PlanProfile, *, drop: PlanStepKind | None = None) -> PlanBlueprint:
    template_steps = {
        PlanStepKind.READ_CONTEXT: PlanStepDraft(
            ref="ctx",
            title="ctx",
            kind=PlanStepKind.READ_CONTEXT,
            skill_name="x",
            output_artifact_ref="ctx",
        ),
        PlanStepKind.GENERATE_DOC: PlanStepDraft(
            ref="brief",
            title="brief",
            kind=PlanStepKind.GENERATE_DOC,
            skill_name="x",
            output_artifact_ref="brief",
            depends_on=["ctx"],
        ),
        PlanStepKind.SUMMARIZE: PlanStepDraft(
            ref="sum",
            title="sum",
            kind=PlanStepKind.SUMMARIZE,
            skill_name="x",
            output_artifact_ref="sum",
            depends_on=["ctx"],
        ),
    }
    required = REQUIRED_KINDS_BY_PROFILE[profile]
    steps = [template_steps[k] for k in required if k in template_steps and k != drop]
    return PlanBlueprint(
        goal="g",
        steps=steps,
        profile=profile,
    )


def test_enforce_template_doc_only_passes() -> None:
    PlanningService._enforce_template(_make_blueprint(PlanProfile.DOC_ONLY))


def test_enforce_template_summary_only_passes() -> None:
    PlanningService._enforce_template(_make_blueprint(PlanProfile.SUMMARY_ONLY))


def test_enforce_template_doc_only_missing_brief_fails() -> None:
    bp = _make_blueprint(PlanProfile.DOC_ONLY, drop=PlanStepKind.GENERATE_DOC)
    with pytest.raises(PlanTemplateError, match="generate_doc"):
        PlanningService._enforce_template(bp)


def test_enforce_template_summary_only_missing_summarize_fails() -> None:
    bp = _make_blueprint(PlanProfile.SUMMARY_ONLY, drop=PlanStepKind.SUMMARIZE)
    with pytest.raises(PlanTemplateError, match="summarize"):
        PlanningService._enforce_template(bp)


# ── OpenAIModelGateway._call_real ────────────────────


@pytest.mark.asyncio
async def test_openai_gateway_no_api_key_falls_back() -> None:
    fallback = TemplatePlanGateway(skill_mode="fake")
    gw = OpenAIModelGateway(api_key="", fallback=fallback)
    bp = await gw.complex_plan(
        PlanContext(raw_text="ppt", requester_id="u1"),
    )
    assert bp.metadata["gateway"] == "template"


@pytest.mark.asyncio
async def test_openai_gateway_call_real_success() -> None:
    payload = {
        "goal": "做一份 PPT",
        "assumptions": [],
        "profile": "deck_full",
        "metadata": {},
        "steps": [
            {
                "ref": "ctx", "title": "c", "kind": "read_context",
                "skill_name": "fake_im_fetch", "output_artifact_ref": "ctx",
            },
            {
                "ref": "brief", "title": "b", "kind": "generate_doc",
                "skill_name": "fake_brief_generate", "output_artifact_ref": "brief",
                "depends_on": ["ctx"],
            },
            {
                "ref": "spec", "title": "s", "kind": "generate_slide_spec",
                "skill_name": "fake_slidespec_generate", "output_artifact_ref": "spec",
                "depends_on": ["brief"],
            },
            {
                "ref": "pptx", "title": "p", "kind": "render_slides",
                "skill_name": "fake_pptx_render", "output_artifact_ref": "pptx",
                "depends_on": ["spec"], "risk_level": "write", "requires_approval": True,
            },
            {
                "ref": "share", "title": "u", "kind": "upload",
                "skill_name": "fake_drive_upload", "output_artifact_ref": "share",
                "depends_on": ["pptx"], "risk_level": "share", "requires_approval": True,
            },
            {
                "ref": "summary", "title": "sm", "kind": "summarize",
                "skill_name": "fake_im_send_summary", "output_artifact_ref": "summary",
                "depends_on": ["share"], "risk_level": "share", "requires_approval": True,
            },
        ],
    }

    mock_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
    )
    mock_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=mock_response))
        )
    )

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        gw = OpenAIModelGateway(api_key="sk-test", model="glm-4-flash")
        bp = await gw.complex_plan(
            PlanContext(raw_text="ppt", requester_id="u1", title="t"),
        )
    # 真实 metadata 必须被强制写入
    assert bp.metadata["gateway"] == "openai"
    assert bp.metadata["skill_mode"] == "fake"
    assert bp.metadata["model"] == "glm-4-flash"


@pytest.mark.asyncio
async def test_openai_gateway_invalid_json_falls_back() -> None:
    mock_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))]
    )
    mock_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=mock_response))
        )
    )

    fallback = TemplatePlanGateway(skill_mode="fake")
    with patch("openai.AsyncOpenAI", return_value=mock_client):
        gw = OpenAIModelGateway(api_key="sk-test", fallback=fallback)
        bp = await gw.complex_plan(PlanContext(raw_text="ppt", requester_id="u1"))
    assert bp.metadata["gateway"] == "template"


@pytest.mark.asyncio
async def test_openai_gateway_network_error_falls_back() -> None:
    mock_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(side_effect=RuntimeError("boom"))
            )
        )
    )
    fallback = TemplatePlanGateway(skill_mode="fake")
    with patch("openai.AsyncOpenAI", return_value=mock_client):
        gw = OpenAIModelGateway(api_key="sk-test", fallback=fallback)
        bp = await gw.complex_plan(PlanContext(raw_text="ppt", requester_id="u1"))
    assert bp.metadata["gateway"] == "template"


# ── AgentLoop task profile 派生 ──────────────────────


def test_task_profile_derives_summary_profile() -> None:
    profile = derive_plan_profile(
        PlanContext(
            raw_text="帮我整理一下纪要总结",
            requester_id="u1",
            source_channel="feishu",
            source_conversation_id="c1",
            source_message_id="m1",
        )
    )
    assert profile == PlanProfile.SUMMARY_ONLY


def test_task_profile_deck_default_for_ppt() -> None:
    profile = derive_plan_profile(
        PlanContext(
            raw_text="帮我做个 ppt 汇报",
            requester_id="u1",
            source_channel="feishu",
            source_conversation_id="c1",
            source_message_id="m1",
        )
    )
    assert profile == PlanProfile.DECK_FULL
