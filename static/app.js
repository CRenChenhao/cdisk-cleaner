// ============ 全局状态 ============
let scanResults = [];
let selectedKeys = new Set();
let isScanning = false;
let isCleaning = false;

// ============ API 调用 ============
async function api(url, options = {}) {
    // 扫描/清理可能耗时较长，取消整体超时，由后端各子任务自行控制超时
    const resp = await fetch(url, options);
    return resp.json();
}

// ============ 磁盘信息 ============
async function loadDiskInfo() {
    try {
        const data = await api('/api/disk');
        document.getElementById('totalSize').textContent = data.total_str;
        document.getElementById('usedSize').textContent = data.used_str;
        document.getElementById('freeSize').textContent = data.free_str;
        document.getElementById('usedPct').textContent = data.used_pct + '%';

        // 更新仪表盘弧形
        const arc = document.getElementById('gaugeArc');
        const total = 251.3; // 半圆周长
        const offset = total * (1 - data.used_pct / 100);
        arc.style.strokeDashoffset = offset;

        // 根据使用率变色
        if (data.used_pct > 90) {
            arc.style.stroke = '#ff6b6b';
            document.getElementById('usedPct').style.color = '#ff6b6b';
        } else if (data.used_pct > 75) {
            arc.style.stroke = '#fdcb6e';
            document.getElementById('usedPct').style.color = '#fdcb6e';
        } else {
            arc.style.stroke = '#00b894';
            document.getElementById('usedPct').style.color = '#00b894';
        }
    } catch (e) {
        console.error('加载磁盘信息失败:', e);
    }
}

// ============ 扫描 ============
async function startScan() {
    if (isScanning) return;
    isScanning = true;

    const btn = document.getElementById('scanBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 扫描中...';

    document.getElementById('scanProgress').style.display = 'block';
    document.getElementById('scanStatus').textContent = '正在扫描各目录...';
    document.getElementById('scanProgressBar').style.width = '30%';

    document.getElementById('targetsList').innerHTML = `
        <div class="empty-state">
            <i class="fa-solid fa-spinner fa-spin"></i>
            <p>正在扫描 C 盘，请稍候...</p>
        </div>
    `;

    try {
        document.getElementById('scanProgressBar').style.width = '60%';
        document.getElementById('scanStatus').textContent = '正在计算各分类大小...';

        const data = await api('/api/scan');

        document.getElementById('scanProgressBar').style.width = '100%';
        document.getElementById('scanStatus').textContent = '扫描完成！';

        scanResults = data.targets;
        document.getElementById('cleanableSize').textContent = data.total_cleanable_str;

        // 重置选择状态（重新扫描不应保留旧勾选）
        selectedKeys.clear();
        updateSelection();

        renderTargets(data.targets);

        // 启用一键清理
        const hasCleanable = data.targets.some(t => t.safe && t.size > 0);
        if (hasCleanable) {
            document.getElementById('cleanAllBtn').disabled = false;
        }

        setTimeout(() => {
            document.getElementById('scanProgress').style.display = 'none';
        }, 1000);

    } catch (e) {
        document.getElementById('targetsList').innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-circle-exclamation" style="color:#ff6b6b;"></i>
                <p>扫描失败: ${e.message}</p>
            </div>
        `;
        document.getElementById('scanProgress').style.display = 'none';
    }

    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> 重新扫描';
    isScanning = false;
}

// ============ 渲染目标列表 ============
function renderTargets(targets) {
    const list = document.getElementById('targetsList');

    if (targets.length === 0) {
        list.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-check-circle" style="color:#00b894;"></i>
                <p>C 盘很干净，没有发现可清理的项目</p>
            </div>
        `;
        return;
    }

    list.innerHTML = targets.map(t => {
        const isEmpty = t.size === 0;
        const isSelected = selectedKeys.has(t.key);
        const warnBadge = !t.safe ? '<span class="badge-warn">需管理员</span>' : '';
        const cleanBtn = isEmpty ? '' : `<button class="btn-clean-one" onclick="event.stopPropagation(); cleanOne('${t.key}')"><i class="fa-solid fa-trash-can"></i> 清理</button>`;

        return `
        <div class="target-card ${isEmpty ? 'empty' : ''} ${isSelected ? 'selected' : ''}"
             data-key="${t.key}" onclick="${isEmpty ? '' : `toggleSelect('${t.key}')`}">
            <div class="target-checkbox">
                <i class="fa-solid fa-check"></i>
            </div>
            <div class="target-icon" style="background: ${t.color}22; color: ${t.color};">
                <i class="fa-solid ${t.icon}"></i>
            </div>
            <div class="target-info">
                <div class="target-name">${t.name}${warnBadge}</div>
                <div class="target-desc">${t.desc}</div>
            </div>
            <div class="target-size">
                <div class="size-value" style="color: ${isEmpty ? 'var(--text-dim)' : t.color};">${t.size_str}</div>
                <div class="size-label">${isEmpty ? '无需清理' : '可释放'}</div>
            </div>
            ${cleanBtn}
        </div>
        `;
    }).join('');
}

// ============ 选择切换 ============
function toggleSelect(key) {
    if (selectedKeys.has(key)) {
        selectedKeys.delete(key);
    } else {
        selectedKeys.add(key);
    }
    updateSelection();
}

function updateSelection() {
    // 更新卡片选中状态
    document.querySelectorAll('.target-card').forEach(card => {
        const key = card.dataset.key;
        if (selectedKeys.has(key)) {
            card.classList.add('selected');
        } else {
            card.classList.remove('selected');
        }
    });

    // 更新选择信息
    const count = selectedKeys.size;
    const info = document.getElementById('selectInfo');
    const cleanSelectedBtn = document.getElementById('cleanSelectedBtn');
    if (count === 0) {
        info.textContent = '未选择';
        cleanSelectedBtn.disabled = true;
    } else {
        let totalSize = 0;
        selectedKeys.forEach(key => {
            const target = scanResults.find(t => t.key === key);
            if (target) totalSize += target.size;
        });
        info.innerHTML = `已选 <strong style="color:var(--primary);">${count}</strong> 项，共 <strong style="color:var(--warning);">${formatSize(totalSize)}</strong>`;
        cleanSelectedBtn.disabled = false;
    }
}

// ============ 单项清理 ============
function cleanOne(key) {
    selectedKeys.clear();
    selectedKeys.add(key);
    updateSelection();
    cleanSelected();
}

// ============ 一键清理安全项 ============
function cleanAll() {
    // 自动选中所有 safe 且 size > 0 的项
    selectedKeys.clear();
    scanResults.forEach(t => {
        if (t.safe && t.size > 0) {
            selectedKeys.add(t.key);
        }
    });
    updateSelection();

    if (selectedKeys.size === 0) {
        return;
    }

    cleanSelected();
}

// ============ 执行清理（逐个执行，实时进度） ============
async function cleanSelected() {
    if (isCleaning || selectedKeys.size === 0) return;
    isCleaning = true;

    const keys = Array.from(selectedKeys);
    const modal = document.getElementById('cleanModal');
    const log = document.getElementById('cleanLog');
    const progressBar = document.getElementById('cleanProgressBar');
    const progressText = document.getElementById('cleanProgressText');
    const resultDiv = document.getElementById('cleanResult');

    modal.style.display = 'flex';
    log.innerHTML = '';
    progressBar.style.width = '0%';
    progressText.innerHTML = '准备中...';
    resultDiv.style.display = 'none';

    // 先展示所有待清理项（灰色未开始状态）
    keys.forEach((key) => {
        const target = scanResults.find(t => t.key === key);
        if (target) {
            const entry = document.createElement('div');
            entry.className = 'clean-log-entry';
            entry.id = `log-${key}`;
            entry.innerHTML = `<i class="fa-solid fa-circle" style="color:var(--text-dim);opacity:0.3;"></i> ${target.name} - 等待中...`;
            log.appendChild(entry);
        }
    });
    log.scrollTop = log.scrollHeight;

    let totalScanned = 0;
    let totalActuallyFreed = 0;
    const total = keys.length;

    // 逐个清理每一项
    for (let i = 0; i < keys.length; i++) {
        const key = keys[i];
        const target = scanResults.find(t => t.key === key);
        if (!target) continue;

        const entry = document.getElementById(`log-${key}`);
        const scannedSize = target.size;
        totalScanned += scannedSize;

        // 更新进度文字和状态
        progressText.innerHTML = `正在清理: <span class="current-name">${target.name}</span> (${i + 1}/${total})`;
        const pct = Math.round((i / total) * 100);
        progressBar.style.width = pct + '%';
        if (entry) {
            entry.innerHTML = `<i class="fa-solid fa-spinner fa-spin" style="color:var(--primary);"></i> 正在清理: ${target.name}...`;
        }
        log.scrollTop = log.scrollHeight;

        try {
            const data = await api('/api/clean', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ keys: [key] })
            });

            const r = data.results[0];
            const freed = r ? r.freed : 0;
            totalActuallyFreed += freed;

            if (entry) {
                const locked = scannedSize - freed;
                if (locked > 1024 * 1024 && freed < scannedSize * 0.9) {
                    entry.innerHTML = `<i class="fa-solid fa-circle-check" style="color:var(--success);"></i> ${r.name} - 释放 <span class="freed">${r.freed_str}</span> <span style="color:var(--warning);font-size:12px;">（${formatSize(locked)} 被占用，关闭相关程序后可清理）</span>`;
                } else {
                    entry.innerHTML = `<i class="fa-solid fa-circle-check" style="color:var(--success);"></i> ${r.name} - 释放 <span class="freed">${r.freed_str}</span>`;
                }
            }
        } catch (e) {
            if (entry) {
                const errMsg = (e.name === 'TimeoutError' || e.name === 'AbortError')
                    ? '超时' : (e.message === 'Failed to fetch' ? '连接失败' : e.message);
                entry.innerHTML = `<i class="fa-solid fa-circle-xmark" style="color:var(--danger);"></i> ${target.name} - <span style="color:var(--danger);">清理失败: ${errMsg}</span>`;
            }
        }

        log.scrollTop = log.scrollHeight;
    }

    // 完成
    const pct = Math.round(((total - 1) / total) * 100);
    // 如果全部成功，显示100%
    if (totalActuallyFreed > 0 || keys.every(k => document.getElementById(`log-${k}`)?.innerHTML.includes('circle-check'))) {
        progressBar.style.width = '100%';
    } else {
        progressBar.style.width = pct + '%';
    }
    progressText.innerHTML = '清理完成';

    // 显示结果
    const lockedTotal = totalScanned - totalActuallyFreed;
    let warningHtml = '';
    if (lockedTotal > 1024 * 1024 && totalActuallyFreed < totalScanned * 0.8) {
        warningHtml = `<div style="margin-top:12px;padding:10px 14px;background:rgba(253,203,110,0.15);border-radius:8px;color:#856404;font-size:13px;line-height:1.6;">
            <i class="fa-solid fa-triangle-exclamation"></i> <strong>部分文件被占用未能清理</strong><br>
            有 <strong>${formatSize(lockedTotal)}</strong> 因相关程序运行中无法删除。建议关闭 Chrome、Edge、VS Code、微信等程序后重新扫描清理。
        </div>`;
    }
    resultDiv.innerHTML = `
        <div class="result-title">清理完成</div>
        <div class="result-freed">${formatSize(totalActuallyFreed)}</div>
        <div class="result-label">实际释放空间</div>
        ${warningHtml}
        <button class="btn-primary btn-done" onclick="closeModal()"><i class="fa-solid fa-check"></i> 完成</button>
    `;
    resultDiv.style.display = 'block';

    // 显示捐赠入口（清理完成即显示）
    const donationSection = document.getElementById('donationSection');
    if (donationSection && totalActuallyFreed > 0) {
        donationSection.style.display = 'block';
    }

    // 刷新磁盘信息
    await loadDiskInfo();

    isCleaning = false;
}

// ============ 关闭弹窗 ============
function closeModal() {
    document.getElementById('cleanModal').style.display = 'none';
    // 隐藏捐赠入口
    const donationSection = document.getElementById('donationSection');
    if (donationSection) donationSection.style.display = 'none';
    // 重新扫描
    startScan();
}

// ============ 放大赞赏码 ============
function openRewardLightbox() {
    document.getElementById('rewardLightbox').style.display = 'flex';
}
function closeRewardLightbox() {
    document.getElementById('rewardLightbox').style.display = 'none';
}

// ============ 退出应用 ============
function exitApp() {
    if (!confirm('确定要退出 C 盘清理工具吗？\n退出后程序将完全关闭。')) {
        return;
    }
    fetch('/api/shutdown', { method: 'POST' })
        .finally(() => {
            // 尝试关闭浏览器标签页
            window.close();
            // 如果 window.close() 被浏览器阻止，显示提示
            document.body.innerHTML = `
                <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;color:var(--text);font-size:16px;text-align:center;padding:40px;">
                    <i class="fa-solid fa-circle-check" style="font-size:48px;color:var(--success);margin-bottom:20px;"></i>
                    <p>已安全退出</p>
                    <p style="color:var(--text-dim);font-size:13px;margin-top:8px;">可以关闭此窗口了</p>
                </div>
            `;
        });
}

// ============ 工具函数 ============
function formatSize(bytes) {
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) {
        bytes /= 1024;
        i++;
    }
    return bytes.toFixed(1) + ' ' + units[i];
}

// ============ 初始化 ============
window.addEventListener('load', () => {
    loadDiskInfo();
    // 自动开始首次扫描
    setTimeout(() => startScan(), 500);
});
