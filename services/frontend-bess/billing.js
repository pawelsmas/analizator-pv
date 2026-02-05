/**
 * Billing Dashboard JavaScript (v4.0.0)
 *
 * Handles:
 * - Loading tenant usage data
 * - Displaying quota cards with progress bars
 * - Daily usage history table
 * - CSV export functionality
 */

// Configuration
const API_BASE = '/api/bess-dispatch';
let currentDays = 7;

// Quota display names (Polish)
const QUOTA_LABELS = {
  jobs_per_day: 'Zadania (dzienna)',
  reports_per_day: 'Raporty (dziennie)',
  shares_total: 'Udostępnienia',
  storage_mb: 'Przestrzeń (MB)',
  projects_total: 'Projekty'
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
  console.log('[Billing] v4.0.0 - Initializing billing dashboard');

  // Check authentication
  const authOk = await checkAuth();
  if (!authOk) {
    window.location.href = 'login.html';
    return;
  }

  // Load usage data
  await loadUsage();
  await loadHistory(currentDays);
});

/**
 * Load tenant usage summary
 */
async function loadUsage() {
  const usageGrid = document.getElementById('usageGrid');
  const planBadge = document.getElementById('planBadge');
  const planName = document.getElementById('planName');
  const resetInfo = document.getElementById('resetInfo');
  const resetText = document.getElementById('resetText');
  const errorMessage = document.getElementById('errorMessage');

  try {
    const token = getAuthToken();
    const response = await fetch(`${API_BASE}/usage`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    console.log('[Billing] Usage data:', data);

    // Update plan badge
    planName.textContent = data.plan_id.toUpperCase();
    planBadge.className = `plan-badge ${data.plan_id}`;

    // Update reset info
    if (data.reset_at) {
      const resetDate = new Date(data.reset_at);
      resetText.textContent = `Limity dzienne resetują się o: ${resetDate.toLocaleTimeString('pl-PL')} (${resetDate.toLocaleDateString('pl-PL')})`;
      resetInfo.style.display = 'flex';
    }

    // Build usage cards
    usageGrid.innerHTML = data.quotas.map(quota => buildUsageCard(quota)).join('');

    errorMessage.style.display = 'none';

  } catch (error) {
    console.error('[Billing] Failed to load usage:', error);
    errorMessage.textContent = `Błąd ładowania danych: ${error.message}`;
    errorMessage.style.display = 'block';
    usageGrid.innerHTML = '<div class="loading-spinner">Nie udało się załadować danych</div>';
  }
}

/**
 * Build HTML for a usage card
 */
function buildUsageCard(quota) {
  const label = QUOTA_LABELS[quota.quota_name] || quota.quota_name;
  const isUnlimited = quota.limit === 0 || quota.limit === null;

  let progressClass = '';
  if (quota.usage_pct !== null) {
    if (quota.usage_pct >= 90) progressClass = 'danger';
    else if (quota.usage_pct >= 70) progressClass = 'warning';
  }

  const limitText = isUnlimited
    ? '<span class="unlimited-badge">UNLIMITED</span>'
    : `z ${quota.limit}`;

  const progressBar = isUnlimited
    ? ''
    : `
      <div class="usage-progress">
        <div class="usage-progress-bar ${progressClass}" style="width: ${Math.min(quota.usage_pct || 0, 100)}%"></div>
      </div>
      <div class="usage-pct">${quota.usage_pct !== null ? quota.usage_pct.toFixed(1) : 0}% wykorzystania</div>
    `;

  return `
    <div class="usage-card">
      <div class="usage-card-header">
        <span class="usage-card-title">${label}</span>
      </div>
      <div class="usage-card-value">${quota.used}</div>
      <div class="usage-card-limit">${limitText}</div>
      ${progressBar}
    </div>
  `;
}

/**
 * Load usage history
 */
async function loadHistory(days) {
  currentDays = days;
  const historyTable = document.getElementById('historyTable');

  // Update button states
  document.querySelectorAll('.days-btn').forEach(btn => {
    btn.classList.remove('active');
    if (btn.textContent.includes(days.toString())) {
      btn.classList.add('active');
    }
  });

  try {
    const token = getAuthToken();
    const response = await fetch(`${API_BASE}/usage/daily?days=${days}`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    console.log('[Billing] History data:', data);

    if (data.records.length === 0) {
      historyTable.innerHTML = '<div class="loading-spinner">Brak danych w wybranym okresie</div>';
      return;
    }

    // Group by date
    const byDate = {};
    data.records.forEach(record => {
      if (!byDate[record.date]) {
        byDate[record.date] = { date: record.date, jobs: 0, reports: 0, projects: [] };
      }
      byDate[record.date].jobs += record.counters.jobs_per_day || 0;
      byDate[record.date].reports += record.counters.reports_per_day || 0;
      if (!byDate[record.date].projects.includes(record.project_id)) {
        byDate[record.date].projects.push(record.project_id);
      }
    });

    // Sort by date descending
    const sortedDates = Object.values(byDate).sort((a, b) => b.date.localeCompare(a.date));

    historyTable.innerHTML = `
      <table class="usage-table">
        <thead>
          <tr>
            <th>Data</th>
            <th>Zadania</th>
            <th>Raporty</th>
            <th>Projekty</th>
          </tr>
        </thead>
        <tbody>
          ${sortedDates.map(row => `
            <tr>
              <td>${formatDate(row.date)}</td>
              <td>${row.jobs}</td>
              <td>${row.reports}</td>
              <td>${row.projects.length}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;

  } catch (error) {
    console.error('[Billing] Failed to load history:', error);
    historyTable.innerHTML = '<div class="loading-spinner">Nie udało się załadować historii</div>';
  }
}

/**
 * Export usage data as CSV
 */
async function exportCsv() {
  try {
    const token = getAuthToken();
    const response = await fetch(`${API_BASE}/usage/export/csv?days=${currentDays}`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    // Get filename from Content-Disposition header
    const disposition = response.headers.get('Content-Disposition');
    let filename = 'usage_export.csv';
    if (disposition) {
      const match = disposition.match(/filename="(.+)"/);
      if (match) filename = match[1];
    }

    // Download file
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);

    console.log('[Billing] CSV exported:', filename);

  } catch (error) {
    console.error('[Billing] Failed to export CSV:', error);
    alert('Nie udało się wyeksportować danych: ' + error.message);
  }
}

/**
 * Format date for display
 */
function formatDate(dateStr) {
  const date = new Date(dateStr);
  return date.toLocaleDateString('pl-PL', {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });
}

/**
 * Get auth token from storage
 */
function getAuthToken() {
  return localStorage.getItem('authToken') || sessionStorage.getItem('authToken');
}

/**
 * Check authentication status
 */
async function checkAuth() {
  const token = getAuthToken();
  if (!token) {
    return false;
  }

  try {
    const response = await fetch(`${API_BASE}/auth/whoami`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (response.ok) {
      const data = await response.json();
      updateWhoAmiBadge(data);
      return true;
    }
  } catch (error) {
    console.error('[Billing] Auth check failed:', error);
  }

  return false;
}

/**
 * Update WhoAmI badge
 */
function updateWhoAmiBadge(data) {
  const badge = document.getElementById('whoamiBadge');
  if (badge && data) {
    badge.querySelector('.whoami-email').textContent = data.email || 'Unknown';
    badge.querySelector('.whoami-role').textContent = data.role || '';
    badge.querySelector('.whoami-tenant').textContent = data.tenant_id || '';
    badge.style.display = 'flex';
  }
}

/**
 * Logout function
 */
function logout() {
  localStorage.removeItem('authToken');
  sessionStorage.removeItem('authToken');
  window.location.href = 'login.html';
}

// Export for testing
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    loadUsage,
    loadHistory,
    exportCsv,
    buildUsageCard,
    formatDate,
    QUOTA_LABELS
  };
}
