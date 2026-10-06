# 个人创意主页 - 技术说明文档

本项目是一个现代化的个人主页系统，采用 3 级页面架构，旨在展示个人的技术见解、兴趣爱好及专业作品。

## 项目特点

1.  **现代化视觉设计**：采用流行的 "Glassmorphism" (毛玻璃) 风格，结合动态渐变背景和丝滑的微动画，提供极佳的视觉体验。
2.  **3 级导航结构**：
    *   **Level 1**: 首页 (`index.html`) - 整体概览。
    *   **Level 2**: 列表页 (`hobbies.html`, `portfolio.html`, `contact.html`) - 分类展示。
    *   **Level 3**: 详情页 (`hobby-detail.html`, `work-detail.html`) - 深度内容。
3.  **自定义交互系统**：弃用原生 `alert`，开发了基于 Vanilla JS 的 Toast 通知系统，用于表单验证反馈和交互提示。
4.  **纯净技术栈**：仅使用 HTML5, CSS3 和原生 JavaScript，无需任何外部框架。

## 文件结构

- `index.html`: 入口首页
- `hobbies.html`: 兴趣爱好列表 (L2)
- `hobby-detail.html`: 摄影兴趣详情 (L3)
- `portfolio.html`: 作品集列表 (L2)
- `work-detail.html`: Neo-Finance 应用案例 (L3)
- `contact.html`: 联系表单页 (L2)
- `css/style.css`: 全局样式表
- `js/main.js`: 交互逻辑与表单验证
- `images/`: 项目多媒体资源

## 技术要点

- **CSS 选择器**：广泛使用伪类 (`:hover`, `:focus`), 子选择器及复杂层叠关系。
- **盒模型布局**：利用 Flexbox 和 CSS Grid 实现响应式布局。
- **表单验证**：实时检测用户输入，并通过自定义 UI 组件进行错误提示。

---

## 证书奖项证据管理系统(新增)

在静态主页之上新增一套证书证据管理能力: 访客墙展示文字与脱敏图片, 站主通过管理 API
录入签发方、有效期与成长目标, 后台数据库保留证书身份与全部修订。

### 架构

```
certs/
  clock.py    服务器时钟校正(偏移量持久化, 事件留痕)
  db.py       SQLite 模式: 证书身份/修订/事件/图片/核对/投影/技能/简历
  pngtool.py  纯标准库 PNG: 元数据识别、PII 提取、像素级脱敏、派生图重建
  service.py  领域服务: 事件溯源 + 实时状态计算 + 事件驱动投影 + 传播
  api.py      HTTP 接口(管理 API 需 Bearer 令牌; 公共 API 只读脱敏数据)
  seed.py     演示数据
certificates.html + js/certificates.js   访客墙(分组折叠, 无评分)
tests/test_acceptance.py                 15 项验收测试
```

### 核心规则

1. **事件语义**: 同一证书的补发图片(`IMAGE_REISSUED`)、续期(`RENEWED`)、
   新获奖(`AWARDED`)是不同事件; 上传图片永远不会新增成就项。
2. **证据分离**: 图片中的个人编号(身份证号/证书编号)被识别记录;
   原件存私密目录(不对外服务), 访客墙只展示抹除元数据并遮盖 PII 的派生图。
3. **核对语义**: 链接可访问仅标记"已核对来源"(来源仍在),
   系统绝不声称证书真实性已获权威机构认证。
4. **状态权威**: 公开读取一律实时计算(撤销>到期>临期>有效);
   事件驱动投影仅为缓存, `sweep` 补齐时间流逝(如午夜到期), `reconcile` 报告漂移。
5. **时间处理**: 纯日期有效期按签发方时区的当地午夜到期; 撤销可追溯生效;
   服务器时钟偏移可校正并持久化, 每个事件记录当时使用的偏移。
6. **传播**: 状态变化同步到技能证据与未冻结简历候选;
   已冻结的历史简历绝不改写, 仅以"冻结后附注"提示变化。
7. **展示**: 页面明确区分 自报/已核对来源/链接失效/已过期/已撤销;
   分组折叠、按状态与获奖时间排序, 不提供任何含金量评分。

### 运行

```bash
python3 -m certs.seed            # 初始化演示数据(幂等)
ADMIN_TOKEN=你的令牌 python3 -m certs.api 8000
# 访客墙:  http://127.0.0.1:8000/certificates.html
# 公共API: GET /api/public/certificates
```

管理接口(均需 `Authorization: Bearer $ADMIN_TOKEN`):
`POST /api/admin/issuers`、`POST /api/admin/issuers/{id}/rename`、
`POST /api/admin/certificates`、`POST /api/admin/certificates/{id}/images|renew|revoke|link-check`、
`POST /api/admin/sweep`、`POST /api/admin/clock`、`GET /api/admin/reconcile`、
`POST /api/admin/resumes[/{id}/items|/freeze]`。
写操作支持 `Idempotency-Key` 头保证重试安全。

### 测试

```bash
python3 -m unittest discover -s tests -v   # 15 项验收场景
```
