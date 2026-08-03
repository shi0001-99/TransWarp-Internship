// Stock Monitor Web App
const API_BASE = '';

let pieChart = null;
let barChart = null;
let autoRefreshInterval = null;
let currentData = [];
let currentFilter = 'all';
let currentLogType = 'run';

// ============ API Helpers ============
async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`);
  return res.json();
}

async function apiPost(path) {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST' });
  return res.json();
}

// ============ Toast ============
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
  toast.innerHTML = `<span>${icons[type] || 'ℹ️'}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ============ Navigation ============
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', (e) => {
    e.preventDefault();
    const view = item.dataset.view;
    switchView(view);
  });
});

function switchView(view) {
  document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.view === view));
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  document.getElementById(`view-${view}`).classList.remove('hidden');
  const titles = { dashboard: '仪表盘', alerts: '预警中心', logs: '运行日志', settings: '监控配置' };
  document.getElementById('pageTitle').textContent = titles[view] || '仪表盘';

  if (view === 'alerts') loadAlerts();
  if (view === 'logs') loadLogs();
  if (view === 'settings') loadSettings();
  if (view === 'dashboard') initCharts();
}

// ============ Dashboard ============
async function loadDashboard() {
  try {
    const data = await apiGet('/api/watchlist');
    currentData = data.stocks || [];
    renderDashboard(currentData);
    updateCharts(currentData);
    document.getElementById('lastUpdate').textContent = `更新于 ${new Date().toLocaleTimeString('zh-CN')}`;
  } catch (e) {
    showToast('数据加载失败', 'error');
  }
}

function renderDashboard(stocks) {
  const grid = document.getElementById('stockGrid');
  if (!stocks.length) {
    grid.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><div class="empty-text">暂无数据，请点击「立即扫描」</div></div>';
    return;
  }

  // Summary
  const alertCount = stocks.filter(s => s.alerts.length > 0).length;
  const criticalCount = stocks.filter(s => s.level === 'critical').length;
  const avgCostChange = stocks.length ? (stocks.reduce((s, st) => s + st.costChange, 0) / stocks.length) : 0;

  document.getElementById('totalCount').textContent = stocks.length;
  document.getElementById('alertCount').textContent = alertCount;
  document.getElementById('criticalCount').textContent = criticalCount;

  // Update pie chart with avg profit in center
  updatePieCenterText(avgCostChange);

  grid.innerHTML = stocks.map(s => {
    const isUp = s.changePct > 0;
    const isDown = s.changePct < 0;
    const costUp = s.costChange > 0;
    const typeLabels = { individual: '个股', etf: 'ETF', gold: '黄金' };
    const cardLevel = s.level === 'critical' ? 'alert-critical' : s.level === 'warning' ? 'alert-warning' : s.alerts.length > 0 ? 'alert-info' : '';

    const alertsHtml = s.alerts.map(a =>
      `<div class="alert-tag ${s.level}">● ${a.text}</div>`
    ).join('') || '<div class="alert-tag">✅ 无预警</div>';

    return `
      <div class="stock-card ${cardLevel}" data-code="${s.code}">
        <div class="stock-header">
          <div>
            <div class="stock-name">${s.name}</div>
            <div class="stock-code">${s.code}</div>
          </div>
          <div class="stock-type">${typeLabels[s.type] || s.type}</div>
        </div>
        <div class="stock-price-row">
          <div class="stock-price ${isUp ? 'up' : isDown ? 'down' : ''}">${s.price.toFixed(2)}</div>
          <div class="stock-change ${isUp ? 'up' : isDown ? 'down' : ''}">${isUp ? '+' : ''}${s.changePct.toFixed(2)}%</div>
        </div>
        <div class="stock-cost-row">
          <span>成本 ¥${s.cost.toFixed(2)}</span>
          <span class="stock-cost-change ${costUp ? 'up' : 'down'}">${costUp ? '+' : ''}${s.costChange.toFixed(2)}%</span>
        </div>
        ${s.maxHigh && s.maxHigh > s.cost ? `<div class="stock-high-row"><span>历史最高 ¥${s.maxHigh.toFixed(2)}</span></div>` : ''}
        <div class="stock-alerts">${alertsHtml}</div>
      </div>
    `;
  }).join('');

  // Click handler for stock cards
  grid.querySelectorAll('.stock-card').forEach(card => {
    card.addEventListener('click', () => {
      const code = card.dataset.code;
      const stock = stocks.find(s => s.code === code);
      if (stock) showStockModal(stock);
    });
  });

  // Update alert badge
  const totalAlerts = stocks.reduce((sum, s) => sum + s.alerts.length, 0);
  const badge = document.getElementById('alertBadge');
  if (totalAlerts > 0) {
    badge.textContent = totalAlerts;
    badge.classList.add('show');
  } else {
    badge.classList.remove('show');
  }
}

function showStockModal(stock) {
  const isUp = stock.changePct > 0;
  const isDown = stock.changePct < 0;
  const costUp = stock.costChange > 0;

  document.getElementById('modalTitle').textContent = `${stock.name} (${stock.code})`;
  document.getElementById('modalBody').innerHTML = `
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px;">
      <div style="background: var(--bg-secondary); padding: 16px; border-radius: 8px;">
        <div style="font-size: 12px; color: var(--text-secondary);">当前价格</div>
        <div style="font-size: 28px; font-weight: 700; color: ${isUp ? 'var(--red)' : isDown ? 'var(--green)' : 'var(--text-primary)'};">${stock.price.toFixed(2)}</div>
        <div style="font-size: 14px; color: ${isUp ? 'var(--red)' : isDown ? 'var(--green)' : 'var(--text-primary)'};">${isUp ? '+' : ''}${stock.changePct.toFixed(2)}%</div>
      </div>
      <div style="background: var(--bg-secondary); padding: 16px; border-radius: 8px;">
        <div style="font-size: 12px; color: var(--text-secondary);">持仓盈亏</div>
        <div style="font-size: 28px; font-weight: 700; color: ${costUp ? 'var(--red)' : 'var(--green)'};">${costUp ? '+' : ''}${stock.costChange.toFixed(2)}%</div>
        <div style="font-size: 14px; color: var(--text-secondary);">成本 ¥${stock.cost.toFixed(2)}</div>
      </div>
    </div>
    ${stock.maxHigh && stock.maxHigh > stock.cost ? `
    <div style="background: var(--bg-secondary); padding: 16px; border-radius: 8px; margin-bottom: 20px;">
      <h4 style="font-size: 14px; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">📈 动态止盈跟踪</h4>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
        <div>
          <div style="font-size: 12px; color: var(--text-secondary);">历史最高</div>
          <div style="font-size: 20px; font-weight: 600; color: var(--red);">¥${stock.maxHigh.toFixed(2)}</div>
        </div>
        <div>
          <div style="font-size: 12px; color: var(--text-secondary);">回撤幅度</div>
          <div style="font-size: 20px; font-weight: 600; color: ${(stock.maxHigh - stock.price) / stock.maxHigh * 100 >= 10 ? 'var(--danger)' : (stock.maxHigh - stock.price) / stock.maxHigh * 100 >= 5 ? '#f59e0b' : 'var(--text-primary)'};">${(((stock.maxHigh - stock.price) / stock.maxHigh) * 100).toFixed(2)}%</div>
        </div>
      </div>
    </div>` : ''}
    <div style="background: var(--bg-secondary); padding: 16px; border-radius: 8px; margin-bottom: 20px;">
      <h4 style="font-size: 14px; margin-bottom: 12px;">🎯 触发预警</h4>
      ${stock.alerts.length ? stock.alerts.map(a => `<div class="alert-tag ${stock.level}" style="margin-bottom: 6px;">● ${a.text}</div>`).join('') : '<div style="color: var(--text-secondary); font-size: 13px;">✅ 暂无预警</div>'}
    </div>
    <div style="font-size: 12px; color: var(--text-muted);">数据更新时间: ${stock.timestamp || '--'}</div>
  `;
  document.getElementById('stockModal').classList.add('show');
}

document.getElementById('modalClose').addEventListener('click', () => {
  document.getElementById('stockModal').classList.remove('show');
});
document.getElementById('stockModal').addEventListener('click', (e) => {
  if (e.target.id === 'stockModal') e.target.classList.remove('show');
});

// ============ Charts ============
let avgProfitValue = 0;

function updatePieCenterText(avgChange) {
  avgProfitValue = avgChange;
  if (!pieChart) return;
  const profitColor = avgChange > 0 ? '#ef4444' : avgChange < 0 ? '#10b981' : '#8b95a7';
  const sign = avgChange > 0 ? '+' : '';
  pieChart.setOption({
    graphic: [
      {
        type: 'text',
        left: 'center',
        top: '35%',
        style: {
          text: '平均盈亏',
          fill: '#8b95a7',
          fontSize: 12
        }
      },
      {
        type: 'text',
        left: 'center',
        top: '45%',
        style: {
          text: sign + avgChange.toFixed(1) + '%',
          fill: profitColor,
          fontSize: 24,
          fontWeight: 'bold'
        }
      }
    ]
  });
}

function initCharts() {
  if (pieChart && barChart) return;
  try {
    const pieEl = document.getElementById('pieChart');
    const barEl = document.getElementById('barChart');
    if (!pieEl || !barEl) return;
    pieChart = echarts.init(pieEl, 'dark');
    barChart = echarts.init(barEl, 'dark');
    window.addEventListener('resize', () => {
      pieChart && pieChart.resize();
      barChart && barChart.resize();
    });
    if (currentData && currentData.length) updateCharts(currentData);
  } catch (e) {
    console.error('Chart init error:', e);
  }
}

function updateCharts(stocks) {
  if (!stocks.length) return;
  if (!pieChart || !barChart) {
    currentData = stocks;
    return;
  }

  // Pie chart - cost change distribution
  const profit = stocks.filter(s => s.costChange > 0).length;
  const loss = stocks.filter(s => s.costChange < 0).length;
  const flat = stocks.filter(s => s.costChange === 0).length;

  const avgCostChange = stocks.length ? (stocks.reduce((s, st) => s + st.costChange, 0) / stocks.length) : 0;
  const profitColor = avgCostChange > 0 ? '#ef4444' : avgCostChange < 0 ? '#10b981' : '#8b95a7';
  const sign = avgCostChange > 0 ? '+' : '';

  pieChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item' },
    legend: { bottom: '0%', textStyle: { color: '#8b95a7' } },
    graphic: [
      {
        type: 'text',
        left: 'center',
        top: '35%',
        style: {
          text: '平均盈亏',
          fill: '#8b95a7',
          fontSize: 12
        }
      },
      {
        type: 'text',
        left: 'center',
        top: '45%',
        style: {
          text: sign + avgCostChange.toFixed(1) + '%',
          fill: profitColor,
          fontSize: 24,
          fontWeight: 'bold'
        }
      }
    ],
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      avoidLabelOverlap: false,
      label: { show: false },
      data: [
        { value: profit, name: '盈利', itemStyle: { color: '#ef4444' } },
        { value: loss, name: '亏损', itemStyle: { color: '#10b981' } },
        { value: flat, name: '持平', itemStyle: { color: '#3b82f6' } }
      ]
    }]
  });

  // Bar chart - change percentages
  barChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: stocks.map(s => s.name),
      axisLabel: { color: '#8b95a7', rotate: 30, fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#8b95a7', formatter: '{value}%' }
    },
    series: [{
      type: 'bar',
      data: stocks.map(s => ({
        value: s.changePct,
        itemStyle: { color: s.changePct >= 0 ? '#ef4444' : '#10b981' }
      })),
      barWidth: '60%',
      label: {
        show: true,
        position: 'top',
        color: '#8b95a7',
        formatter: '{c}%'
      }
    }]
  });
}

// ============ Alerts ============
async function loadAlerts() {
  const data = await apiGet('/api/alerts?lines=200');
  const list = document.getElementById('alertsList');

  let alerts = data.alerts || [];
  if (currentFilter !== 'all') {
    alerts = alerts.filter(a => a.level === currentFilter);
  }

  if (!alerts.length) {
    list.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><div class="empty-text">暂无预警记录</div></div>';
    return;
  }

  list.innerHTML = alerts.map(a => {
    const level = a.level || 'info';
    const icon = level === 'critical' ? '🚨' : level === 'warning' ? '⚠️' : '📢';
    const cleanContent = a.content.replace(/^ALERT \[\w+\]\s*/, '').trim();
    return `
      <div class="alert-item level-${level}">
        <div class="alert-icon">${icon}</div>
        <div class="alert-body">
          <div class="alert-timestamp">${a.timestamp}</div>
          <div class="alert-content">${cleanContent}</div>
        </div>
      </div>
    `;
  }).join('');
}

document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentFilter = btn.dataset.level;
    loadAlerts();
  });
});

// ============ Logs ============
async function loadLogs() {
  const data = await apiGet(`/api/${currentLogType === 'alert' ? 'alerts' : 'logs'}?lines=200`);
  const viewer = document.getElementById('logViewer');
  const entries = data.logs || data.alerts || [];

  if (!entries.length) {
    viewer.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">暂无日志</div></div>';
    return;
  }

  viewer.innerHTML = entries.map(e => {
    const level = e.level || (currentLogType === 'alert' ? 'ALERT' : 'INFO');
    return `
      <div class="log-entry">
        <span class="log-time">${e.timestamp}</span>
        <span class="log-level ${level}">${level}</span>
        <span class="log-content">${e.content}</span>
      </div>
    `;
  }).join('');
  viewer.scrollTop = viewer.scrollHeight;
}

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentLogType = btn.dataset.logType;
    loadLogs();
  });
});

// ============ Settings ============
let currentWatchlist = [];
let editingStockCode = null;
let searchTimer = null;

async function loadSettings() {
  const data = await apiGet('/api/watchlist_config');
  currentWatchlist = data.watchlist || [];
  renderWatchlistTable();
}

function renderWatchlistTable() {
  const container = document.getElementById('settingsContainer');

  if (!currentWatchlist.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">暂无监控标的，点击右上角"新增标的"添加</div></div>';
    return;
  }

  const typeLabels = { individual: '个股', etf: 'ETF', gold: '黄金' };

  container.innerHTML = `
    <div class="settings-section">
      <h3 style="margin-bottom:16px;">📋 监控标的列表 (${currentWatchlist.length} 只)</h3>
      <div style="overflow-x:auto;">
        <table class="settings-table">
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>类型</th>
              <th>成本价</th>
              <th>预警参数</th>
            </tr>
          </thead>
          <tbody>
            ${currentWatchlist.map(s => `
              <tr data-code="${s.code}" data-market="${s.market}">
                <td class="stock-code">${s.market}${s.code}</td>
                <td><strong>${s.name}</strong></td>
                <td><span class="type-badge">${typeLabels[s.type] || s.type}</span></td>
                <td class="stock-price">¥${s.cost.toFixed(2)}</td>
                <td class="stock-alerts">
                  ${renderAlertTags(s.alerts)}
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  // Attach click handlers
  container.querySelectorAll('tbody tr').forEach(row => {
    row.addEventListener('click', () => {
      const code = row.dataset.code;
      const market = row.dataset.market;
      openEditModal(code, market);
    });
  });
}

function renderAlertTags(alerts) {
  if (!alerts) return '';
  const tags = [];
  if (alerts.cost_pct_above) tags.push(`<span class="mini-alert">盈利≥${alerts.cost_pct_above}%</span>`);
  if (alerts.cost_pct_below) tags.push(`<span class="mini-alert critical">亏损≤${alerts.cost_pct_below}%</span>`);
  if (alerts.change_pct_above) tags.push(`<span class="mini-alert warning">涨幅≥${alerts.change_pct_above}%</span>`);
  if (alerts.change_pct_below) tags.push(`<span class="mini-alert critical">跌幅≤${alerts.change_pct_below}%</span>`);
  if (alerts.volume_surge) tags.push(`<span class="mini-alert info">放量≥${alerts.volume_surge}x</span>`);
  return tags.join('');
}

// ============ Edit Modal ============
function openEditModal(code, market) {
  const stock = currentWatchlist.find(s => s.code === code && s.market === market);
  if (!stock) return;

  editingStockCode = code;
  const isNew = false;
  document.getElementById('editModalTitle').textContent = '编辑标的';
  document.getElementById('deleteStockBtn').style.display = 'inline-flex';

  showEditForm(stock, isNew);
}

function openAddModal() {
  editingStockCode = null;
  document.getElementById('editModalTitle').textContent = '新增标的';
  document.getElementById('deleteStockBtn').style.display = 'none';

  const defaults = {
    code: '', name: '', market: 'sh', type: 'individual', cost: 0,
    alerts: {
      cost_pct_above: 10.0,
      cost_pct_below: -10.0,
      change_pct_above: 3.0,
      change_pct_below: -3.0,
      volume_surge: 2.0
    }
  };
  showEditForm(defaults, true);
}

function showEditForm(stock, isNew) {
  const marketOptions = ['sh', 'sz'];
  const typeOptions = [
    { value: 'individual', label: '个股' },
    { value: 'etf', label: 'ETF' },
    { value: 'gold', label: '黄金' }
  ];

  document.getElementById('editModalBody').innerHTML = `
    <div class="form-row">
      <div class="form-group">
        <label>股票代码 *</label>
        <input type="text" id="editCode" value="${stock.code}" ${!isNew ? 'readonly' : ''} placeholder="如 600519" />
      </div>
      <div class="form-group">
        <label>所属市场 *</label>
        <select id="editMarket" ${!isNew ? 'disabled' : ''}>
          ${marketOptions.map(m => `<option value="${m}" ${stock.market === m ? 'selected' : ''}>${m.toUpperCase()}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>股票名称 *</label>
        <input type="text" id="editName" value="${stock.name}" placeholder="如 贵州茅台" />
      </div>
      <div class="form-group">
        <label>类型 *</label>
        <select id="editType">
          ${typeOptions.map(t => `<option value="${t.value}" ${stock.type === t.value ? 'selected' : ''}>${t.label}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="form-group">
      <label>买入成本价 (¥)</label>
      <input type="number" id="editCost" step="0.01" value="${stock.cost || 0}" />
    </div>

    <h4 style="margin: 20px 0 12px; font-size: 14px; color: var(--text-secondary);">🔔 预警参数设置</h4>
    <div class="form-row">
      <div class="form-group">
        <label>盈利预警 (%)</label>
        <input type="number" id="alertCostAbove" step="0.1" value="${stock.alerts?.cost_pct_above ?? 10.0}" />
      </div>
      <div class="form-group">
        <label>亏损预警 (%)</label>
        <input type="number" id="alertCostBelow" step="0.1" value="${stock.alerts?.cost_pct_below ?? -10.0}" />
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>日内涨幅预警 (%)</label>
        <input type="number" id="alertChangeAbove" step="0.1" value="${stock.alerts?.change_pct_above ?? 3.0}" />
      </div>
      <div class="form-group">
        <label>日内跌幅预警 (%)</label>
        <input type="number" id="alertChangeBelow" step="0.1" value="${stock.alerts?.change_pct_below ?? -3.0}" />
      </div>
    </div>
    <div class="form-group">
      <label>放量倍数预警 (x)</label>
      <input type="number" id="alertVolumeSurge" step="0.1" value="${stock.alerts?.volume_surge ?? 2.0}" />
    </div>
  `;

  document.getElementById('editModal').classList.add('show');
}

function closeEditModal() {
  document.getElementById('editModal').classList.remove('show');
  editingStockCode = null;
}

function getEditFormData() {
  const code = document.getElementById('editCode').value.trim();
  const name = document.getElementById('editName').value.trim();
  const market = document.getElementById('editMarket').value;
  const type = document.getElementById('editType').value;
  const cost = parseFloat(document.getElementById('editCost').value) || 0;

  const costPctAbove = parseFloat(document.getElementById('alertCostAbove').value) || 10;
  const costPctBelow = parseFloat(document.getElementById('alertCostBelow').value) || -10;
  const changePctAbove = parseFloat(document.getElementById('alertChangeAbove').value) || 3;
  const changePctBelow = parseFloat(document.getElementById('alertChangeBelow').value) || -3;
  const volumeSurge = parseFloat(document.getElementById('alertVolumeSurge').value) || 2;

  return {
    code, name, market, type, cost,
    alerts: {
      cost_pct_above: costPctAbove,
      cost_pct_below: costPctBelow,
      change_pct_above: changePctAbove,
      change_pct_below: changePctBelow,
      volume_surge: volumeSurge
    }
  };
}

// Modal controls
document.getElementById('addStockBtn').addEventListener('click', openAddModal);
document.getElementById('editModalClose').addEventListener('click', closeEditModal);
document.getElementById('cancelEditBtn').addEventListener('click', closeEditModal);

document.getElementById('saveEditBtn').addEventListener('click', async () => {
  const formData = getEditFormData();

  if (!formData.code || !formData.name) {
    showToast('请填写完整信息', 'warning');
    return;
  }

  try {
    let result;
    if (editingStockCode) {
      // Update existing
      result = await fetch(`/api/watchlist/${encodeURIComponent(editingStockCode)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      }).then(r => r.json());

      if (result.error) { showToast(result.error, 'error'); return; }
      showToast('修改成功', 'success');
    } else {
      // Add new
      result = await fetch('/api/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      }).then(r => r.json());

      if (result.error) { showToast(result.error, 'error'); return; }
      showToast('新增成功', 'success');
    }

    closeEditModal();
    loadSettings();
    loadDashboard();
  } catch (err) {
    showToast('操作失败: ' + err.message, 'error');
  }
});

document.getElementById('deleteStockBtn').addEventListener('click', async () => {
  if (!editingStockCode) return;

  const stock = currentWatchlist.find(s => s.code === editingStockCode);
  if (!stock) return;

  const confirmed = await showConfirm(`确定删除 ${stock.name} (${stock.code}) 吗？`);
  if (!confirmed) return;

  try {
    const result = await fetch(`/api/watchlist/${encodeURIComponent(editingStockCode)}`, {
      method: 'DELETE'
    }).then(r => r.json());

    if (result.error) { showToast(result.error, 'error'); return; }
    showToast('删除成功', 'success');
    closeEditModal();
    loadSettings();
    loadDashboard();
  } catch (err) {
    showToast('删除失败: ' + err.message, 'error');
  }
});

// ============ Confirm Dialog ============
function showConfirm(message) {
  return new Promise(resolve => {
    document.getElementById('confirmMessage').textContent = message;
    document.getElementById('confirmModal').classList.add('show');

    const okBtn = document.getElementById('confirmOk');
    const cancelBtn = document.getElementById('confirmCancel');

    const cleanup = () => {
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      document.getElementById('confirmModal').classList.remove('show');
    };

    const onOk = () => { cleanup(); resolve(true); };
    const onCancel = () => { cleanup(); resolve(false); };

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
  });
}

// Search with debounce
const searchInput = document.getElementById('stockSearch');
searchInput.addEventListener('input', () => {
  const q = searchInput.value.trim();
  clearTimeout(searchTimer);

  if (!q) {
    document.getElementById('searchResults').classList.remove('show');
    return;
  }

  searchTimer = setTimeout(async () => {
    const data = await apiGet(`/api/stock/search?q=${encodeURIComponent(q)}`);
    const results = data.results || [];
    const container = document.getElementById('searchResults');

    if (!results.length) {
      container.innerHTML = '<div class="search-result-item" style="color:var(--text-secondary);text-align:center;">无匹配结果</div>';
    } else {
      container.innerHTML = results.map(r => `
        <div class="search-result-item" data-code="${r.code}" data-market="${r.market}">
          <div class="result-name">${r.name}</div>
          <div class="result-code">${r.market.toUpperCase()}${r.code}</div>
        </div>
      `).join('');

      container.querySelectorAll('.search-result-item').forEach(item => {
        item.addEventListener('click', () => {
          searchInput.value = '';
          container.classList.remove('show');
          const code = item.dataset.code;
          const market = item.dataset.market;
          const existing = currentWatchlist.find(s => s.code === code);
          if (existing) {
            openEditModal(code, market);
          } else {
            openAddModal();
            document.getElementById('editCode').value = code;
            document.getElementById('editMarket').value = market;
          }
        });
      });
    }
    container.classList.add('show');
  }, 300);
});

// Close search results on outside click
document.addEventListener('click', (e) => {
  if (!e.target.closest('.settings-search')) {
    document.getElementById('searchResults').classList.remove('show');
  }
});

// ============ Card Click Navigation ============
document.querySelectorAll('.summary-cards .card.clickable').forEach(card => {
  card.addEventListener('click', () => {
    const target = card.dataset.target;
    handleCardNavigation(target);
  });
});

function handleCardNavigation(target) {
  switch (target) {
    case 'holdings':
      const holdingsSection = document.querySelector('.section-title');
      if (holdingsSection) {
        holdingsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
      break;
    case 'alerts':
      switchView('alerts');
      setTimeout(() => {
        const allBtn = document.querySelector('.filter-btn[data-level="all"]');
        if (allBtn) {
          allBtn.click();
        }
      }, 100);
      break;
    case 'critical-alerts':
      switchView('alerts');
      setTimeout(() => {
        const criticalBtn = document.querySelector('.filter-btn[data-level="critical"]');
        if (criticalBtn) {
          criticalBtn.click();
        }
      }, 100);
      break;
  }
}

// ============ Controls ============
document.getElementById('startDaemonBtn').addEventListener('click', async () => {
  const result = await apiPost('/api/daemon/start');
  if (result.success) {
    showToast(`后台进程已启动 (PID: ${result.pid})`, 'success');
  } else {
    showToast(result.message || '启动失败', 'error');
  }
  updateDaemonStatus();
});

document.getElementById('stopDaemonBtn').addEventListener('click', async () => {
  const result = await apiPost('/api/daemon/stop');
  if (result.success) {
    showToast(result.message, 'success');
  } else {
    showToast(result.message || '停止失败', 'error');
  }
  updateDaemonStatus();
});

async function updateDaemonStatus() {
  try {
    const data = await apiGet('/api/status');
    const dot = document.querySelector('#daemonStatus .status-dot');
    const text = document.querySelector('#daemonStatus .status-text');
    if (data.daemon.running) {
      dot.className = 'status-dot running';
      text.textContent = `运行中 (PID: ${data.daemon.pid})`;
    } else {
      dot.className = 'status-dot stopped';
      text.textContent = '未运行';
    }
  } catch {
    // ignore
  }
}

// ============ Auto Refresh ============
function setupAutoRefresh() {
  if (autoRefreshInterval) clearInterval(autoRefreshInterval);
  const interval = 10000; // 10 seconds fixed
  autoRefreshInterval = setInterval(() => {
    const activeView = document.querySelector('.nav-item.active')?.dataset.view;
    if (activeView === 'dashboard') loadDashboard();
    updateDaemonStatus();
  }, interval);
}

// ============ Init ============
document.addEventListener('DOMContentLoaded', async () => {
  initCharts();
  setupAutoRefresh();
  updateDaemonStatus();
  await loadDashboard();
});
