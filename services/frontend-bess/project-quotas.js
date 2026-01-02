/**
 * Project Quotas Editor JavaScript (v4.0.0)
 *
 * Handles:
 * - Loading project list
 * - Loading/saving project quota overrides
 * - Displaying project usage
 */

// Configuration
const API_BASE = '/api/bess-dispatch';
let currentProjectId = null;
let originalOverrides = {};
let isAdmin = false;

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
  console.log('[ProjectQuotas] v4.0.0 - Initializing project quotas editor');

  // Check authentication
  const authData = await checkAuth();
  if (!authData) {
    window.location.href = 'login.html';
    return;
  }

  // Check if user is admin
  isAdmin = authData.role === 'admin';
  if (!isAdmin) {
    document.getElementById('adminNotice').style.display = 'block';
    document.getElementById('actionsBar').style.display = 'none';
    // Disable all inputs
    document.querySelectorAll('.override-input').forEach(input => {
      input.disabled = true;
    });
  }

  // Load project list
  await loadProjectList();

  // Check URL params for pre-selected project
  const urlParams = new URLSearchParams(window.location.search);
  const projectIdParam = urlParams.get('project');
  if (projectIdParam) {
    document.getElementById('projectSelect').value = projectIdParam;
    await loadProjectQuotas();
  }
});

/**
 * Load list of projects
 */
async function loadProjectList() {
  const select = document.getElementById('projectSelect');

  try {
    const token = getAuthToken();

    // Try to get projects from a projects endpoint, or use usage data
    const response = await fetch(`${API_BASE}/usage/daily?days=30`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();

    // Extract unique project IDs
    const projects = new Set();
    data.records.forEach(record => {
      projects.add(record.project_id);
    });

    // Add options
    projects.forEach(projectId => {
      const option = document.createElement('option');
      option.value = projectId;
      option.textContent = projectId;
      select.appendChild(option);
    });

    // If no projects, add a placeholder option
    if (projects.size === 0) {
      const option = document.createElement('option');
      option.value = 'default';
      option.textContent = 'default (domyślny)';
      select.appendChild(option);
    }

    console.log('[ProjectQuotas] Loaded', projects.size, 'projects');

  } catch (error) {
    console.error('[ProjectQuotas] Failed to load projects:', error);
    // Add default option
    const option = document.createElement('option');
    option.value = 'default';
    option.textContent = 'default';
    select.appendChild(option);
  }
}

/**
 * Load quotas for selected project
 */
async function loadProjectQuotas() {
  const select = document.getElementById('projectSelect');
  const projectId = select.value;

  if (!projectId) {
    document.getElementById('quotasContent').style.display = 'none';
    return;
  }

  currentProjectId = projectId;
  document.getElementById('quotasContent').style.display = 'block';

  try {
    const token = getAuthToken();

    // Load project quotas (overrides)
    const quotasResponse = await fetch(`${API_BASE}/projects/${projectId}/quotas`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!quotasResponse.ok) {
      throw new Error(`HTTP ${quotasResponse.status}`);
    }

    const quotasData = await quotasResponse.json();
    console.log('[ProjectQuotas] Quotas data:', quotasData);

    // Load project usage
    const usageResponse = await fetch(`${API_BASE}/projects/${projectId}/usage`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!usageResponse.ok) {
      throw new Error(`HTTP ${usageResponse.status}`);
    }

    const usageData = await usageResponse.json();
    console.log('[ProjectQuotas] Usage data:', usageData);

    // Update form
    updateQuotasForm(quotasData, usageData);
    updateUsageDisplay(usageData);

  } catch (error) {
    console.error('[ProjectQuotas] Failed to load project quotas:', error);
    showError('Nie udało się załadować kwot projektu: ' + error.message);
  }
}

/**
 * Update quotas form with data
 */
function updateQuotasForm(quotasData, usageData) {
  const overrides = quotasData.overrides || {};
  originalOverrides = { ...overrides };

  // Find plan limits from usage data
  const planLimits = {};
  usageData.quotas.forEach(q => {
    planLimits[q.quota_name] = q.limit;
  });

  // Update plan limit displays
  document.getElementById('planLimitJobs').textContent = formatLimit(planLimits.jobs_per_day);
  document.getElementById('planLimitReports').textContent = formatLimit(planLimits.reports_per_day);
  document.getElementById('planLimitShares').textContent = formatLimit(planLimits.shares_total);
  document.getElementById('planLimitStorage').textContent = formatLimit(planLimits.storage_mb);

  // Update override inputs
  setOverrideInput('overrideJobs', overrides.jobs_per_day);
  setOverrideInput('overrideReports', overrides.reports_per_day);
  setOverrideInput('overrideShares', overrides.shares_total);
  setOverrideInput('overrideStorage', overrides.storage_mb);

  // Update override badge
  const hasOverrides = Object.values(overrides).some(v => v !== null && v !== undefined);
  const badge = document.getElementById('overrideBadge');
  if (hasOverrides) {
    badge.className = 'override-badge';
    badge.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
      </svg>
      Ma nadpisania
    `;
  } else {
    badge.className = 'override-badge none';
    badge.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
        <polyline points="22 4 12 14.01 9 11.01"></polyline>
      </svg>
      Używa limitów planu
    `;
  }

  // Add change listeners
  document.querySelectorAll('.override-input').forEach(input => {
    input.addEventListener('input', markAsModified);
  });
}

/**
 * Set override input value
 */
function setOverrideInput(elementId, value) {
  const input = document.getElementById(elementId);
  if (value !== null && value !== undefined) {
    input.value = value;
  } else {
    input.value = '';
  }
  input.classList.remove('modified');
}

/**
 * Mark input as modified
 */
function markAsModified(event) {
  event.target.classList.add('modified');
}

/**
 * Format limit value for display
 */
function formatLimit(value) {
  if (value === null || value === undefined) return '—';
  if (value === 0) return '∞';
  return value.toLocaleString('pl-PL');
}

/**
 * Update usage display
 */
function updateUsageDisplay(usageData) {
  const grid = document.getElementById('usageGrid');

  const html = usageData.quotas.map(quota => {
    const progressClass = getProgressClass(quota.usage_pct);
    const limitText = quota.limit === 0 ? '∞' : quota.limit;

    return `
      <div class="usage-item">
        <span class="usage-item-name">${getQuotaLabel(quota.quota_name)}</span>
        <span class="usage-item-value">${quota.used}</span>
        <span class="usage-item-limit">z ${limitText}</span>
        ${quota.limit && quota.limit > 0 ? `
          <div class="usage-progress">
            <div class="usage-progress-bar ${progressClass}" style="width: ${Math.min(quota.usage_pct || 0, 100)}%"></div>
          </div>
        ` : ''}
      </div>
    `;
  }).join('');

  grid.innerHTML = html;
}

/**
 * Get quota label in Polish
 */
function getQuotaLabel(quotaName) {
  const labels = {
    jobs_per_day: 'Zadania',
    reports_per_day: 'Raporty',
    shares_total: 'Udostępnienia',
    storage_mb: 'Przestrzeń (MB)',
    projects_total: 'Projekty'
  };
  return labels[quotaName] || quotaName;
}

/**
 * Get progress bar class based on percentage
 */
function getProgressClass(pct) {
  if (pct === null || pct === undefined) return '';
  if (pct >= 90) return 'danger';
  if (pct >= 70) return 'warning';
  return '';
}

/**
 * Save quota overrides
 */
async function saveQuotas(event) {
  event.preventDefault();

  if (!isAdmin) {
    showError('Brak uprawnień do edycji kwot');
    return;
  }

  const saveBtn = document.getElementById('saveBtn');
  saveBtn.disabled = true;
  saveBtn.textContent = 'Zapisywanie...';

  try {
    const token = getAuthToken();

    // Collect overrides from form
    const overrides = {};
    const jobsValue = document.getElementById('overrideJobs').value;
    const reportsValue = document.getElementById('overrideReports').value;
    const sharesValue = document.getElementById('overrideShares').value;
    const storageValue = document.getElementById('overrideStorage').value;

    if (jobsValue !== '') overrides.jobs_per_day = parseInt(jobsValue, 10);
    if (reportsValue !== '') overrides.reports_per_day = parseInt(reportsValue, 10);
    if (sharesValue !== '') overrides.shares_total = parseInt(sharesValue, 10);
    if (storageValue !== '') overrides.storage_mb = parseInt(storageValue, 10);

    console.log('[ProjectQuotas] Saving overrides:', overrides);

    const response = await fetch(`${API_BASE}/projects/${currentProjectId}/quotas`, {
      method: 'PATCH',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ overrides })
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || `HTTP ${response.status}`);
    }

    const result = await response.json();
    console.log('[ProjectQuotas] Save result:', result);

    // Reload data
    await loadProjectQuotas();

    showSuccess('Nadpisania zostały zapisane pomyślnie!');

  } catch (error) {
    console.error('[ProjectQuotas] Failed to save:', error);
    showError('Nie udało się zapisać nadpisań: ' + error.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = 'Zapisz nadpisania';
  }
}

/**
 * Reset form to original values
 */
function resetForm() {
  setOverrideInput('overrideJobs', originalOverrides.jobs_per_day);
  setOverrideInput('overrideReports', originalOverrides.reports_per_day);
  setOverrideInput('overrideShares', originalOverrides.shares_total);
  setOverrideInput('overrideStorage', originalOverrides.storage_mb);

  document.querySelectorAll('.override-input').forEach(input => {
    input.classList.remove('modified');
  });

  hideMessages();
}

/**
 * Show success message
 */
function showSuccess(message) {
  const el = document.getElementById('successMessage');
  el.textContent = message;
  el.style.display = 'block';
  document.getElementById('errorMessage').style.display = 'none';

  setTimeout(() => {
    el.style.display = 'none';
  }, 5000);
}

/**
 * Show error message
 */
function showError(message) {
  const el = document.getElementById('errorMessage');
  el.textContent = message;
  el.style.display = 'block';
  document.getElementById('successMessage').style.display = 'none';
}

/**
 * Hide all messages
 */
function hideMessages() {
  document.getElementById('successMessage').style.display = 'none';
  document.getElementById('errorMessage').style.display = 'none';
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
    return null;
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
      return data;
    }
  } catch (error) {
    console.error('[ProjectQuotas] Auth check failed:', error);
  }

  return null;
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
    loadProjectQuotas,
    saveQuotas,
    resetForm,
    formatLimit,
    getQuotaLabel,
    getProgressClass
  };
}
