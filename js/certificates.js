// Static demonstration data for the public evidence wall.
// In production, this document is produced by the certificate read API and
// never contains original image URLs or unrestricted personal identifiers.
const certificates = [
  {
    id: 'cert-cloud-arch-0001',
    title: '云原生架构设计专业证书',
    issuerName: '云图认证院（原：云图考试中心）',
    goal: '成长目标：把容器、韧性设计与成本治理沉淀为可复用的技能证据。',
    awardedAt: '2025-03-16T09:30:00+08:00',
    expiresAt: '2027-03-15T23:59:59+08:00',
    expiryLabel: '2027-03-15 23:59:59（Asia/Shanghai）',
    revocation: null,
    source: {
      state: 'verified',
      url: 'https://example.org/verify/cloud/DEMO-REDACTED',
      checkedAt: '2026-09-28T10:15:00+08:00',
      detail: '已核对签发方记录：脱敏编号、主体标识与当前有效期匹配。'
    },
    asset: { state: 'derived', label: 'public_derived/cloud-arch-redacted.svg', publicUrl: 'images/certificates/cloud-redacted.svg', alt: '云原生证书脱敏派生图' },
    achievementCount: 1,
    events: [
      { at: '2025-03-16T09:30:00+08:00', type: 'awarded', text: '新获奖：建立这一项成就。' },
      { at: '2026-01-10T14:00:00+08:00', type: 'asset_replaced', text: '补发公开派生图；原件版本变化，不新增成就。' },
      { at: '2026-03-01T11:20:00+08:00', type: 'renewed', text: '续期至当前有效期；续期是同一证书的生命周期事件。' },
      { at: '2026-05-18T09:00:00+08:00', type: 'issuer_renamed', text: '签发机构由“云图考试中心”更名为“云图认证院”；证书身份不变。' }
    ]
  },
  {
    id: 'cert-security-0002',
    title: '安全开发生命周期实践者',
    issuerName: '星河安全基金会',
    goal: '成长目标：将威胁建模、依赖治理与最小权限原则用于真实项目。',
    awardedAt: '2024-10-01T10:00:00+08:00',
    expiresAt: '2026-10-07T00:00:00+08:00',
    expiryLabel: '2026-10-07 00:00（Asia/Shanghai，午夜边界）',
    revocation: null,
    source: {
      state: 'verified',
      url: 'https://example.org/verify/security/DEMO-REDACTED',
      checkedAt: '2026-09-30T16:45:00+08:00',
      detail: '已核对签发方记录：脱敏编号与有效期匹配。'
    },
    asset: { state: 'derived', label: 'public_derived/security-redacted.svg', publicUrl: 'images/certificates/security-redacted.svg', alt: '安全开发证书脱敏派生图' },
    achievementCount: 1,
    events: [
      { at: '2024-10-01T10:00:00+08:00', type: 'awarded', text: '新获奖。' },
      { at: '2025-09-20T15:30:00+08:00', type: 'renewed', text: '续期；新有效期在签发方时区午夜结束。' }
    ]
  },
  {
    id: 'cert-accessibility-0003',
    title: '无障碍设计评估培训完成奖',
    issuerName: '普惠体验联盟',
    goal: '成长目标：把键盘可达、语义化和对比度检查纳入交付清单。',
    awardedAt: '2026-08-12T13:00:00+08:00',
    expiresAt: null,
    expiryLabel: '长期有效（签发方未设置有效期）',
    revocation: null,
    source: {
      state: 'self_reported',
      url: null,
      checkedAt: null,
      detail: '站主已上传自报材料；尚未完成签发方记录核对。'
    },
    asset: { state: 'failed', label: '派生图生成失败：保留文字记录，不阻塞证书身份录入。' },
    achievementCount: 1,
    events: [
      { at: '2026-08-12T13:00:00+08:00', type: 'awarded', text: '新获奖。' },
      { at: '2026-08-12T13:05:00+08:00', type: 'asset_failed', text: '脱敏派生图处理失败；私密原件不转公开，等待重试。' }
    ]
  },
  {
    id: 'cert-data-viz-0004',
    title: '数据可视化专题竞赛二等奖',
    issuerName: '南方数字媒体学会',
    goal: '成长目标：继续提升从数据口径到视觉解释的一体化表达。',
    awardedAt: '2023-05-20T18:00:00+08:00',
    expiresAt: null,
    expiryLabel: '奖项长期有效，但当前来源链接待修复',
    revocation: null,
    source: {
      state: 'stale',
      url: 'https://example.org/verify/award/old-demo',
      checkedAt: '2026-02-14T09:00:00+08:00',
      lastFailureAt: '2026-10-02T03:20:00+08:00',
      detail: '曾核对获奖名单；最近一次链接返回 404。链接失效不等于奖项被撤销，但不能继续宣称来源仍在线。'
    },
    asset: { state: 'derived', label: 'public_derived/data-viz-redacted.svg', publicUrl: 'images/certificates/award-redacted.svg', alt: '数据可视化奖项脱敏派生图' },
    achievementCount: 1,
    events: [
      { at: '2023-05-20T18:00:00+08:00', type: 'awarded', text: '新获奖。' },
      { at: '2026-02-14T09:00:00+08:00', type: 'verification_checked', text: '与签发方获奖名单核对一致。' },
      { at: '2026-10-02T03:20:00+08:00', type: 'verification_link_broken', text: '验证链接失效；证据状态降级为“链接失效”。' }
    ]
  },
  {
    id: 'cert-devops-0005',
    title: 'DevOps 流程自动化证书',
    issuerName: '海川技术学院',
    goal: '成长目标：历史技能证据；展示持续交付实践，不作为当前有效证书使用。',
    awardedAt: '2024-01-10T09:00:00+08:00',
    expiresAt: '2025-12-31T23:59:59+08:00',
    expiryLabel: '2025-12-31 23:59:59（Asia/Shanghai）',
    revocation: null,
    source: {
      state: 'verified_historical',
      url: 'https://example.org/verify/devops/DEMO-REDACTED',
      checkedAt: '2025-12-20T10:00:00+08:00',
      detail: '到期前曾核对一致；现在只作为历史记录展示。'
    },
    asset: { state: 'derived', label: 'public_derived/devops-redacted.svg', publicUrl: 'images/certificates/devops-redacted.svg', alt: 'DevOps 历史证书脱敏派生图' },
    achievementCount: 1,
    events: [
      { at: '2024-01-10T09:00:00+08:00', type: 'awarded', text: '新获奖。' },
      { at: '2025-12-20T10:00:00+08:00', type: 'verification_checked', text: '到期前核对一致；到期状态由当前时间比较得出，不伪造业务事件。' }
    ]
  },
  {
    id: 'cert-project-0006',
    title: '项目管理专业实践者证书',
    issuerName: '远洲管理认证中心',
    goal: '成长目标：保留为一次被追溯撤销的历史记录，避免继续用于技能证据与简历候选。',
    awardedAt: '2026-02-01T09:00:00+08:00',
    expiresAt: '2028-01-31T23:59:59+08:00',
    expiryLabel: '2028-01-31 23:59:59（Asia/Shanghai）',
    revocation: {
      effectiveAt: '2026-08-01T00:00:00+08:00',
      recordedAt: '2026-09-12T15:30:00+08:00',
      reason: '签发方复审发现报名资格材料不符，追溯撤销。'
    },
    source: {
      state: 'revoked_by_issuer',
      url: 'https://example.org/verify/project/DEMO-REDACTED',
      checkedAt: '2026-09-12T15:30:00+08:00',
      detail: '签发方明确撤销，撤销效力追溯至 2026-08-01。'
    },
    asset: { state: 'revoked', label: 'public_derived/project-redacted-marked.svg', publicUrl: 'images/certificates/project-revoked-redacted.svg', alt: '项目管理证书撤销标记脱敏派生图' },
    achievementCount: 1,
    events: [
      { at: '2026-02-01T09:00:00+08:00', type: 'awarded', text: '新获奖。' },
      { at: '2026-07-28T11:00:00+08:00', type: 'renewed', text: '曾提交续期；后续撤销事件按生效时间覆盖该区间的有效性。' },
      { at: '2026-08-01T00:00:00+08:00', type: 'revoked', recordedAt: '2026-09-12T15:30:00+08:00', text: '追溯撤销：业务生效时间为 2026-08-01，入库时间为 2026-09-12。' }
    ]
  }
];

function formatDate(isoString) {
  if (!isoString) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Asia/Shanghai'
  }).format(new Date(isoString));
}

function calculateValidity(certificate, now = new Date()) {
  if (certificate.revocation && new Date(certificate.revocation.effectiveAt) <= now) {
    return 'revoked';
  }
  if (new Date(certificate.awardedAt) > now) return 'not_active';
  if (certificate.expiresAt && new Date(certificate.expiresAt) <= now) return 'expired';
  return 'valid';
}

function sourceState(certificate) {
  return certificate.source.state;
}

function badge(label, modifier) {
  return `<span class="badge badge-${modifier}">${label}</span>`;
}

function buildBadges(certificate, validity) {
  const badges = [];

  if (validity === 'valid') badges.push(badge('当前有效', 'valid'));
  if (validity === 'expired') badges.push(badge('已过期', 'invalid'));
  if (validity === 'revoked') badges.push(badge('已撤销', 'invalid'));
  if (validity === 'not_active') badges.push(badge('未生效', 'stale'));

  const source = sourceState(certificate);
  if (source === 'verified') badges.push(badge('已核对来源', 'source'));
  if (source === 'self_reported') badges.push(badge('自报材料', 'self'));
  if (source === 'stale') badges.push(badge('验证链接失效', 'stale'));
  if (source === 'verified_historical') badges.push(badge('历史核对', 'stale'));
  if (source === 'revoked_by_issuer') badges.push(badge('签发方撤销', 'invalid'));

  if (certificate.asset.state === 'failed') badges.push(badge('图片处理失败', 'stale'));
  return badges.join('');
}

function sourceMarkup(certificate) {
  const source = certificate.source;
  const link = source.url
    ? `<a href="${source.url}" rel="noopener noreferrer" target="_blank">${source.url}</a>`
    : '暂无公开验证链接';

  const checked = source.checkedAt ? `上次核对：${formatDate(source.checkedAt)}。` : '';
  const failed = source.lastFailureAt ? `最近失败：${formatDate(source.lastFailureAt)}。` : '';
  return `<strong>来源说明：</strong>${source.detail} ${checked}${failed}<br>链接：${link}`;
}

function renderCard(certificate, now) {
  const template = document.getElementById('certificate-card-template');
  const node = template.content.cloneNode(true);
  const article = node.querySelector('.certificate-card');
  const validity = calculateValidity(certificate, now);

  article.dataset.validity = validity;
  article.dataset.source = sourceState(certificate);
  article.dataset.expires = certificate.expiresAt || '';
  article.dataset.title = certificate.title;
  article.dataset.latest = Math.max(...certificate.events.map(event => new Date(event.at).getTime()));

  const visual = node.querySelector('.card-visual');
  if (certificate.asset.state === 'failed') {
    visual.classList.add('is-missing');
  } else if (certificate.asset.publicUrl) {
    const image = document.createElement('img');
    image.src = certificate.asset.publicUrl;
    image.alt = certificate.asset.alt;
    image.loading = 'lazy';
    image.addEventListener('error', () => {
      visual.classList.add('is-missing');
      image.remove();
    });
    visual.appendChild(image);
  }
  if (certificate.asset.state === 'revoked') visual.classList.add('is-revoked');

  node.querySelector('.badge-row').innerHTML = buildBadges(certificate, validity);
  node.querySelector('h2').textContent = certificate.title;
  node.querySelector('.issuer').textContent = certificate.issuerName;
  node.querySelector('.goal').textContent = certificate.goal;

  const facts = [
    ['获得时间', formatDate(certificate.awardedAt)],
    ['有效期', certificate.expiryLabel],
    ['成就计数', `${certificate.achievementCount} 项（补发图片/续期不重复计数）`],
    ['公开图片', certificate.asset.label]
  ];
  if (certificate.revocation) {
    facts.push(['追溯撤销', formatDate(certificate.revocation.effectiveAt)]);
    facts.push(['撤销原因', certificate.revocation.reason]);
  }
  node.querySelector('.fact-list').innerHTML = facts
    .map(([term, value]) => `<dt>${term}</dt><dd>${value}</dd>`)
    .join('');

  node.querySelector('.source-line').innerHTML = sourceMarkup(certificate);
  node.querySelector('.event-timeline ol').innerHTML = certificate.events
    .slice()
    .sort((a, b) => new Date(a.at) - new Date(b.at))
    .map(event => {
      const retroactive = event.recordedAt && event.recordedAt > event.at
        ? '（追溯事件，以业务生效时间归位）'
        : '';
      return `<li><time>${formatDate(event.at)}</time> · ${event.text}${retroactive}</li>`;
    })
    .join('');

  return node;
}

function matches(card, filter) {
  if (filter === 'all') return true;
  const validity = card.dataset.validity;
  const source = card.dataset.source;
  if (filter === 'valid') return validity === 'valid';
  if (filter === 'invalid') return validity === 'expired' || validity === 'revoked';
  if (filter === 'self_reported') return source === 'self_reported';
  if (filter === 'source_verified') return source === 'verified';
  if (filter === 'stale') return source === 'stale' || source === 'verified_historical' || source === 'revoked_by_issuer';
  return true;
}

function sortCards(cards, mode) {
  return cards.sort((a, b) => {
    if (mode === 'title') return a.dataset.title.localeCompare(b.dataset.title, 'zh-CN');
    if (mode === 'expiry') {
      const aTime = a.dataset.expires ? new Date(a.dataset.expires).getTime() : Number.MAX_SAFE_INTEGER;
      const bTime = b.dataset.expires ? new Date(b.dataset.expires).getTime() : Number.MAX_SAFE_INTEGER;
      return aTime - bTime;
    }
    return Number(b.dataset.latest) - Number(a.dataset.latest);
  });
}

function getDemoNow() {
  const override = new URLSearchParams(window.location.search).get('demo_at');
  if (override) {
    const parsed = new Date(override);
    if (!Number.isNaN(parsed.getTime())) return parsed;
  }
  return new Date();
}

function render() {
  const grid = document.getElementById('certificate-grid');
  const activeFilter = document.querySelector('.filter-chip.active').dataset.filter;
  const sortMode = document.getElementById('certificate-sort').value;
  const now = getDemoNow();
  const fragment = document.createDocumentFragment();

  certificates.forEach(certificate => fragment.appendChild(renderCard(certificate, now)));
  const allCards = Array.from(fragment.children);
  const visible = sortCards(allCards.filter(card => matches(card, activeFilter)), sortMode);

  grid.innerHTML = '';
  visible.forEach(card => grid.appendChild(card));

  const timeMode = new URLSearchParams(window.location.search).get('demo_at')
    ? '（URL 参数 demo_at 指定的演示时间；生产环境以服务器权威时间为准）'
    : '（浏览器演示时间；生产环境以服务器权威时间为准）';
  document.getElementById('result-meta').textContent =
    `展示 ${visible.length} / ${allCards.length} 项；读取时间：${formatDate(now.toISOString())}${timeMode}。只按事实字段排序，无含金量评分。`;
  document.getElementById('empty-state').hidden = visible.length !== 0;
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.filter-chip').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.filter-chip').forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      render();
    });
  });
  document.getElementById('certificate-sort').addEventListener('change', render);
  render();
});
