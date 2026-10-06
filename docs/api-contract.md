# 管理 API 与公开 API 契约

所有时间使用 ISO-8601/RFC 3339 带偏移时间；仅给日期时必须同时提供签发方时区和到期口径。写接口要求 `Idempotency-Key` 与认证令牌。

## 1. 认证

- `POST /api/admin/session`：登录并签发短期访问令牌。
- `POST /api/admin/session/refresh`：轮换刷新令牌。
- `POST /api/admin/session/revoke`：注销。

认证请求使用 HTTPS、安全 Cookie 或 `Authorization: Bearer`；管理操作记录操作者、IP/UA、请求 ID 和变更原因。

## 2. 签发机构

### 创建签发机构

`POST /api/admin/issuers`

```json
{
  "name": "云图认证院",
  "authority_type": "independent_certifier",
  "timezone": "Asia/Shanghai",
  "verification_base_url": "https://example.org/verify/",
  "contact": "certification@example.org"
}
```

### 机构更名

`POST /api/admin/issuers/{issuer_id}/rename`

```json
{
  "new_name": "云图认证院",
  "effective_at": "2026-05-18T00:00:00+08:00",
  "reason": "机构公告更名",
  "source_url": "https://example.org/announcement"
}
```

更名只更新当前显示名，不改变 `issuer_id`，也不改变证书身份。

## 3. 证书身份

### 创建新获奖

`POST /api/admin/certificates`

```json
{
  "issuer_id": "iss_01",
  "credential_type": "professional_certificate",
  "title": "云原生架构设计专业证书",
  "credential_number_raw": "CLOUD-2025-0001",
  "subject_display_name": "林墨",
  "awarded_at": "2025-03-16T09:30:00+08:00",
  "expires_at": "2027-03-15T23:59:59+08:00",
  "expires_timezone": "Asia/Shanghai",
  "expiry_semantics": "end_of_second",
  "growth_goal": "沉淀容器与韧性设计能力",
  "public_note": "公开页可显示的文字说明",
  "source_event_request_id": "manual-award-0001"
}
```

返回：

```json
{
  "certificate_id": "cert_01H...",
  "version": 1,
  "achievement_count": 1,
  "lifecycle_state": "valid",
  "evidence_state": "self_reported"
}
```

### 录入续期（非新成就）

`POST /api/admin/certificates/{certificate_id}/events/renewal`

```json
{
  "effective_at": "2027-03-16T00:00:00+08:00",
  "expires_at": "2029-03-15T23:59:59+08:00",
  "expires_timezone": "Asia/Shanghai",
  "reason": "完成持续教育要求",
  "verification_source_id": "vsrc_01",
  "expected_version": 7
}
```

### 录入撤销（可追溯）

`POST /api/admin/certificates/{certificate_id}/events/revocation`

```json
{
  "effective_at": "2026-08-01T00:00:00+08:00",
  "recorded_reason": "签发方复审发现资格材料不符",
  "source_url": "https://example.org/revocation/123",
  "retroactive": true,
  "expected_version": 8
}
```

若撤销事件迟到，服务端重新归约受影响区间并传播当前状态；历史冻结简历不被覆盖。

### 补发证书或替换图片（非新成就）

`POST /api/admin/certificates/{certificate_id}/events/reissue`

```json
{
  "effective_at": "2026-01-10T14:00:00+08:00",
  "reason": "原证书卡片遗失后补发",
  "new_credential_number_raw": "CLOUD-2026-0088",
  "identity_match_basis": ["holder", "issuer", "credential_type", "issuer_record"]
}
```

补发必须链接原 `certificate_id`。只有匹配依据不足时才进入复核，不能静默新建证书。

## 4. 上传与派生图

### 创建上传任务

`POST /api/admin/assets/upload-intents`

```json
{
  "certificate_id": "cert_01H...",
  "asset_role": "private_original",
  "filename": "certificate.pdf",
  "media_type": "application/pdf",
  "byte_size": 284930,
  "sha256": "..."
}
```

返回私密对象存储的短期上传地址、`asset_id` 和处理任务 ID。浏览器不得直接获得可公开读取的原件 URL。

### 查询处理状态

`GET /api/admin/assets/{asset_id}/processing`

```json
{
  "state": "derived",
  "ocr_confidence": 0.91,
  "extracted_fields": {
    "credential_number": "NO. ****-****-1234",
    "issuer_name": "云图认证院",
    "awarded_at": "2025-03-16T09:30:00+08:00"
  },
  "public_derivative": {
    "asset_id": "aset_pub_01",
    "url": "https://public.example/derived/abc.webp"
  },
  "warnings": ["removed_exif_gps", "masked_qr_code"]
}
```

失败示例：

```json
{
  "state": "derivation_failed",
  "retryable": true,
  "error_code": "IMAGE_REDACTION_TIMEOUT",
  "public_rule": "original_must_remain_private"
}
```

### 重试派生

`POST /api/admin/assets/{asset_id}/derive`

重试只改变处理任务/派生图版本，不新增证书，不新增成就。

## 5. 来源核对

### 创建验证来源

`POST /api/admin/verification-sources`

```json
{
  "certificate_id": "cert_01H...",
  "source_kind": "issuer_registry",
  "url": "https://example.org/verify/CLOUD-2025-0001",
  "authority_scope": "current_registry"
}
```

### 记录一次核对

`POST /api/admin/verification-sources/{source_id}/checks`

```json
{
  "checked_at": "2026-09-30T08:45:00Z",
  "http_reachable": true,
  "result": "verified",
  "matched_fields": [
    "credential_number_hash",
    "subject_hash",
    "credential_type",
    "validity_range"
  ],
  "evidence_snapshot_asset_id": "aset_snapshot_01"
}
```

`http_reachable=true` 但字段未匹配时，`result` 只能是 `reachable_unverified` 或 `mismatch`，不能是 `verified`。

链接 404/超时：

```json
{
  "checked_at": "2026-10-02T03:20:00Z",
  "http_reachable": false,
  "result": "link_broken",
  "error_code": "HTTP_404",
  "certificate_effect": "source_stale_not_revocation"
}
```

## 6. 查询与修订

- `GET /api/admin/certificates/{certificate_id}`：管理详情，默认编号脱敏；带额外权限才返回完整编号。
- `GET /api/admin/certificates/{certificate_id}/events`：事件流、版本、业务生效时间和入库时间。
- `GET /api/admin/certificates?status=...&issuer=...`：管理列表。
- `POST /api/admin/certificates/{certificate_id}/corrections`：录入人工修订，必须包含原因、证据来源和操作者；旧值仍可从事件表重建。
- `GET /api/admin/reprocessing/jobs`：查看图片失败、来源失效、投影重建任务。

## 7. 公开访客 API

`GET /api/public/certificates?filter=all&sort=recent`

公开响应禁止包含：原件 URL、完整个人编号、完整姓名以外的敏感身份字段、私密 OCR 文本、内部备注、EXIF。

```json
{
  "state_computed_at": "2026-10-06T12:00:00Z",
  "clock_source": "server_authoritative_time",
  "items": [
    {
      "certificate_id": "cert_public_01",
      "title": "云原生架构设计专业证书",
      "issuer_display_name": "云图认证院（原：云图考试中心）",
      "growth_goal": "沉淀容器与韧性设计能力",
      "validity_state": "valid",
      "evidence_state": "verified",
      "asset_state": "derived",
      "awarded_at_local": "2025-03-16 09:30",
      "expires_at_local": "2027-03-15 23:59:59",
      "timezone": "Asia/Shanghai",
      "credential_number_masked": "NO. ****-****-1234",
      "public_derivative_url": "https://public.example/derived/abc.webp",
      "verification": {
        "label": "已核对来源",
        "detail": "2026-09-28 与签发方记录的脱敏编号和有效期匹配",
        "url": "https://example.org/verify/..."
      },
      "achievement_count": 1,
      "events_summary": [
        { "at": "2025-03-16T09:30:00+08:00", "type": "award.created" },
        { "at": "2026-03-01T11:20:00+08:00", "type": "certificate.renewed" }
      ]
    }
  ],
  "ranking_policy": "factual_fields_only_no_prestige_score"
}
```

## 8. 错误语义

| 状态码 | 场景 |
|---|---|
| 400 | 时区缺失、日期口径不明确、字段格式错误 |
| 401/403 | 未认证、无权查看完整编号或原件 |
| 404 | 证书、来源或文件不存在 |
| 409 | 事件版本冲突、续期/撤销并发需重新归约或复核 |
| 422 | 业务规则不通过，例如补发匹配依据不足 |
| 429 | 来源站点或管理 API 限流 |
| 502/504 | 验证来源暂时不可达；记录为检查失败，不改变证书本身 |

错误响应必须区分：证书状态、来源可达性、图片处理状态，避免把链接或图片失败误报成证书失效。
