# 2026-08-21 飞书附件发送失败事故（99992402 field validation failed）

## 问题

用户要求发送 HTML/PDF 报告，多次发送均未收到。**与文件格式无关**（PDF/HTML 都失败）。

## 症状

gateway 日志（`/root/.hermes/profiles/apmm/logs/gateway.log`）：
```
[Feishu] Delivering 1 non-image MEDIA attachment(s)
[Feishu] Failed to send media (.html): [99992402] field validation failed
[Feishu] Failed to send media (.pdf): [99992402] field validation failed
[Feishu] Could not send media-delivery-failure notice: [99992402] field validation failed
```
文本消息正常（用户能收到回复），仅附件（file 消息）失败。

## 排查链

1. 日志确认 3 次发送全部 99992402（HTML ×2、PDF ×1）
2. **REST API 手动复现**（apmm 凭证 `cli_aaad5d4b31b85bcf`，凭据在 `/root/.hermes/profiles/apmm/.env`）：
   - 上传 `im/v1/files`（pdf + stream 类型）→ **code=0 成功**
   - 发送 file 消息（普通 + 带 `root_id=omt_*`）→ **code=0 成功**
   - → 上传/API 本身没问题
3. **lark_oapi SDK 1.6.8 复现**（hermes venv）→ 上传+发送 file 消息 **code=0 成功**
   - → 问题不在 SDK 基础能力，在 Hermes 的调用参数
4. **代码审查** `plugins/platforms/feishu/adapter.py::_send_raw_message`（L4688-4696）：
   ```python
   _thread_id = (metadata or {}).get("thread_id")
   if _thread_id:
       body = self._build_create_message_body(receive_id=_thread_id, ...)
       request = self._build_create_message_request("thread_id", body)  # ← 根因
   ```

## 根因

**`receive_id_type="thread_id"` 不是飞书合法取值**。飞书 `im/v1/messages` 的
`receive_id_type` 仅支持 `open_id / user_id / union_id / email / chat_id`。
发送到话题（topic）的正确方式 = `receive_id=chat_id` + body 带 `root_id`（话题 ID，
`omt_*` 格式实测可接受）。

- 文本消息走 **reply 路径**（metadata 有 `reply_to_message_id`）→ 不受影响，用户正常收到
- 附件投递无 reply_to → 走 thread 分支 → `receive_id_type=thread_id` → 服务端
  400 `99992402 field validation failed`（**所有** topic 下的附件都会失败）

## 处置

1. **临时绕过（报告立即送达）**：REST 直发脚本 `/tmp/send_report_direct.py`
   （上传 + `chat_id` + `root_id=omt_19e1f1971ccf1bee` 发送 file 消息）→ message_id 确认成功
2. **根治补丁** `adapter.py::_send_raw_message` thread 分支（备份 `/tmp/adapter.py.bak-20260821`）：
   ```python
   if _thread_id:
       from lark_oapi.core import AccessTokenType, HttpMethod
       from lark_oapi.core.model import BaseRequest
       request = (BaseRequest.builder()
                  .http_method(HttpMethod.POST)
                  .uri("/open-apis/im/v1/messages?receive_id_type=chat_id")
                  .token_types({AccessTokenType.TENANT})
                  .body({"receive_id": chat_id, "msg_type": msg_type,
                         "content": payload, "root_id": _thread_id,
                         "uuid": str(uuid.uuid4())})
                  .build())
       return await self._run_blocking(self._client.request, request)
   ```
   注：SDK 1.6.8 的 `CreateMessageRequestBody` 无 `root_id` 字段 → 用 BaseRequest 自定义 body。

## 验证

- ✅ REST 直发：PDF + HTML 均 code=0，message_id 已确认（用户已收到）
- ✅ 补丁：`py_compile` 通过；BaseRequest 带 body（含 root_id）构造冒烟通过
- ⏳ **待 gateway 重启后生效**：重启后需复测 MEDIA 附件（`.html`/`.pdf` 各一次）确认 99992402 消失

## 教训

1. **topic（thread）消息 ≠ 普通消息**：飞书 topic 发送必须 `root_id`，`receive_id_type` 无 thread_id
2. **文本正常 ≠ 全链路正常**：文本走 reply 路径，附件走 create 路径——两类消息路径不同，排查附件问题不能以文本成功为据
3. **REST/SDK 手动复现是最快的二分定位法**：先证明 API 能力本身 OK，再查调用方参数
4. Hermes 源码修改需重启 gateway 生效（run 模式无 systemd，kill + nohup 重启）；修复验证纪律：补丁 → 重启 → 复测
