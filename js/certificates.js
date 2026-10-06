/**
 * 证书证据墙前端逻辑。
 * 数据来自 /api/public/certificates(脱敏派生数据);
 * 分组折叠展示, 排序仅按状态与获奖时间, 不计算也不展示任何评分。
 */
(function () {
    'use strict';

    var GROUPS = [
        { key: 'valid', label: '有效', badge: 'badge-valid' },
        { key: 'expiring_soon', label: '临近到期', badge: 'badge-expiring' },
        { key: 'expired', label: '已过期', badge: 'badge-expired' },
        { key: 'revoked', label: '已撤销', badge: 'badge-revoked' }
    ];
    var VALIDITY_BADGE = {
        valid: { cls: 'badge-valid', text: '有效' },
        expiring_soon: { cls: 'badge-expiring', text: '临近到期' },
        expired: { cls: 'badge-expired', text: '已过期' },
        revoked: { cls: 'badge-revoked', text: '已撤销' }
    };
    var VERIFICATION_BADGE = {
        self_reported: { cls: 'badge-self', text: '自报' },
        source_checked: { cls: 'badge-checked', text: '已核对来源' },
        link_failed: { cls: 'badge-linkfail', text: '链接失效' }
    };

    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function badge(map, key) {
        var b = map[key] || { cls: 'badge-self', text: key };
        return el('span', 'badge ' + b.cls, b.text);
    }

    function renderCard(item) {
        var card = el('article', 'cert-card glass' + (item.image ? ' with-image' : ''));

        if (item.image) {
            var figure = el('div');
            var img = el('img', 'derived');
            img.src = item.image.url;
            img.alt = item.title + '(已脱敏证书影像)';
            img.loading = 'lazy';
            figure.appendChild(img);
            figure.appendChild(el('div', 'redacted-note', '脱敏派生图 · 原件不公开展示'));
            card.appendChild(figure);
        }

        var body = el('div');
        body.appendChild(el('div', 'cert-title', item.title));

        var issuer = el('div', 'cert-issuer', item.issuer.name);
        if (item.issuer.former_names && item.issuer.former_names.length) {
            issuer.appendChild(el('span', 'former',
                '(曾用名: ' + item.issuer.former_names.join('、') + ')'));
        }
        body.appendChild(issuer);

        var meta = el('div', 'cert-meta');
        meta.appendChild(el('span', null, '获奖: ' + item.issued_on));
        meta.appendChild(el('span', null,
            item.valid_until ? ('有效期至: ' + item.valid_until + ' (' + item.expiry_tz + ')')
                             : '长期有效'));
        if (item.level) meta.appendChild(el('span', null, '等级: ' + item.level));
        body.appendChild(meta);

        if (item.growth_goal) {
            var goal = el('p', 'cert-goal');
            goal.appendChild(el('strong', null, '成长目标: '));
            goal.appendChild(document.createTextNode(item.growth_goal));
            body.appendChild(goal);
        }

        var badges = el('div', 'badges');
        badges.appendChild(badge(VALIDITY_BADGE, item.validity));
        badges.appendChild(badge(VERIFICATION_BADGE, item.verification));
        body.appendChild(badges);

        if (item.verify_url) {
            var link = el('a', 'verify-link', '验证来源');
            link.href = item.verify_url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            var wrap = el('p');
            wrap.style.marginTop = '0.6rem';
            wrap.appendChild(link);
            wrap.appendChild(el('div', 'verify-note', item.verification_note));
            body.appendChild(wrap);
        }

        card.appendChild(body);
        return card;
    }

    function renderWall(data) {
        var wall = document.getElementById('wall');
        wall.textContent = '';
        if (!data.total) {
            wall.appendChild(el('div', 'wall-status', '暂无公开的证书记录。'));
            return;
        }
        GROUPS.forEach(function (g, idx) {
            var items = data.groups[g.key];
            if (!items || !items.length) return;
            var details = el('details', 'cert-group glass');
            if (idx === 0) details.open = true;      // 默认仅展开第一组
            var summary = el('summary');
            summary.appendChild(el('span', null, g.label));
            summary.appendChild(el('span', 'count', items.length + ' 项'));
            details.appendChild(summary);
            var bodyWrap = el('div', 'group-body');
            items.forEach(function (item) { bodyWrap.appendChild(renderCard(item)); });
            details.appendChild(bodyWrap);
            wall.appendChild(details);
        });
        document.getElementById('sort-note').textContent =
            (data.sort_note || '') + ' · 数据生成于 ' + (data.generated_at || '未知时间');
    }

    function renderFallback(err) {
        var wall = document.getElementById('wall');
        wall.textContent = '';
        wall.appendChild(el('div', 'wall-status',
            '证据墙服务暂不可用(' + err.message + '), 请稍后再访。'));
    }

    fetch('/api/public/certificates', { headers: { 'Accept': 'application/json' } })
        .then(function (resp) {
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        })
        .then(renderWall)
        .catch(renderFallback);
})();
