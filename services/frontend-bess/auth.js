/**
 * Auth module for BESS frontend (v3.0.0)
 *
 * Handles:
 * - JWT token storage and refresh
 * - Login/logout functionality
 * - WhoAmI badge updates
 * - Auth-aware fetch wrapper
 * - Redirect to login on 401
 */

console.log('[AUTH] auth.js LOADED v=3.0.0 - timestamp:', new Date().toISOString());

// ============================================
// AUTH CONFIGURATION
// ============================================

const AUTH_CONFIG = {
  baseUrl: '/api/bess-dispatch',
  tokenKey: 'bess_access_token',
  userKey: 'bess_user_info',
  loginPath: '/login.html',
};

// ============================================
// TOKEN STORAGE
// ============================================

/**
 * Store access token in localStorage
 * @param {string} token - JWT access token
 */
function setAuthToken(token) {
  if (token) {
    localStorage.setItem(AUTH_CONFIG.tokenKey, token);
  } else {
    localStorage.removeItem(AUTH_CONFIG.tokenKey);
  }
}

/**
 * Get stored access token
 * @returns {string|null} JWT access token or null
 */
function getAuthToken() {
  return localStorage.getItem(AUTH_CONFIG.tokenKey);
}

/**
 * Store user info in localStorage
 * @param {object} userInfo - User information from /auth/me
 */
function setUserInfo(userInfo) {
  if (userInfo) {
    localStorage.setItem(AUTH_CONFIG.userKey, JSON.stringify(userInfo));
  } else {
    localStorage.removeItem(AUTH_CONFIG.userKey);
  }
}

/**
 * Get stored user info
 * @returns {object|null} User info or null
 */
function getUserInfo() {
  const stored = localStorage.getItem(AUTH_CONFIG.userKey);
  if (stored) {
    try {
      return JSON.parse(stored);
    } catch {
      return null;
    }
  }
  return null;
}

/**
 * Check if user is authenticated (has token)
 * @returns {boolean}
 */
function isAuthenticated() {
  return !!getAuthToken();
}

/**
 * Clear all auth data (logout)
 */
function clearAuth() {
  localStorage.removeItem(AUTH_CONFIG.tokenKey);
  localStorage.removeItem(AUTH_CONFIG.userKey);
}

// ============================================
// AUTH STATE
// ============================================

/**
 * Auth state object
 */
const authState = {
  isEnabled: null,  // null = unknown, true = auth enabled, false = auth disabled
  user: null,       // Current user info
  loading: false,   // Loading state
};

/**
 * Check if auth is enabled by calling /auth/me
 * @returns {Promise<boolean>} true if auth enabled, false if disabled
 */
async function checkAuthMode() {
  try {
    const response = await fetch(`${AUTH_CONFIG.baseUrl}/auth/me`);

    if (response.status === 401) {
      // Auth is enabled and we're not authenticated
      authState.isEnabled = true;
      authState.user = null;
      return true;
    }

    if (response.ok) {
      const data = await response.json();

      if (data.auth_method === 'disabled') {
        // Auth is disabled - anonymous access allowed
        authState.isEnabled = false;
        authState.user = data;
        return false;
      } else {
        // Auth is enabled and we have a valid session
        authState.isEnabled = true;
        authState.user = data;
        setUserInfo(data);
        return true;
      }
    }

    // Unexpected response - assume auth enabled
    authState.isEnabled = true;
    return true;

  } catch (error) {
    console.error('[AUTH] Error checking auth mode:', error);
    authState.isEnabled = true;  // Assume enabled on error
    return true;
  }
}

// ============================================
// LOGIN / LOGOUT
// ============================================

/**
 * Login with email and password
 * @param {string} email - User email
 * @param {string} password - User password
 * @returns {Promise<{success: boolean, error?: string}>}
 */
async function login(email, password) {
  try {
    const response = await fetch(`${AUTH_CONFIG.baseUrl}/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password }),
    });

    if (response.ok) {
      const data = await response.json();
      setAuthToken(data.access_token);

      // Fetch user info
      await fetchCurrentUser();

      return { success: true };
    }

    const errorData = await response.json().catch(() => ({}));
    const errorMessage = errorData.detail?.message || errorData.detail || 'Logowanie nie powiodlo sie';

    return { success: false, error: errorMessage };

  } catch (error) {
    console.error('[AUTH] Login error:', error);
    return { success: false, error: 'Blad polaczenia z serwerem' };
  }
}

/**
 * Logout - clear token and redirect to login
 */
function logout() {
  clearAuth();
  authState.user = null;

  // Redirect to login if auth is enabled
  if (authState.isEnabled) {
    window.location.href = AUTH_CONFIG.loginPath;
  } else {
    // Just reload for disabled mode
    window.location.reload();
  }
}

/**
 * Fetch current user info from /auth/me
 * @returns {Promise<object|null>} User info or null
 */
async function fetchCurrentUser() {
  const token = getAuthToken();

  try {
    const headers = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${AUTH_CONFIG.baseUrl}/auth/me`, { headers });

    if (response.ok) {
      const data = await response.json();
      authState.user = data;
      setUserInfo(data);
      return data;
    }

    if (response.status === 401) {
      // Token expired or invalid
      clearAuth();
      authState.user = null;
      return null;
    }

    return null;

  } catch (error) {
    console.error('[AUTH] Error fetching user:', error);
    return null;
  }
}

// ============================================
// AUTH-AWARE FETCH WRAPPER
// ============================================

/**
 * Fetch wrapper that adds auth header and handles 401
 * @param {string} url - URL to fetch
 * @param {RequestInit} options - Fetch options
 * @returns {Promise<Response>}
 */
async function authFetch(url, options = {}) {
  const token = getAuthToken();

  // Add auth header if we have a token
  const headers = { ...options.headers };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url, { ...options, headers });

  // Handle 401 - redirect to login
  if (response.status === 401 && authState.isEnabled) {
    console.log('[AUTH] Received 401 - redirecting to login');
    clearAuth();
    window.location.href = AUTH_CONFIG.loginPath;
    throw new Error('Unauthorized - redirecting to login');
  }

  return response;
}

// ============================================
// WHOAMI BADGE
// ============================================

/**
 * Update WhoAmI badge in header with current user info
 */
function updateWhoAmiBadge() {
  const badge = document.getElementById('whoamiBadge');
  if (!badge) return;

  const user = authState.user;

  if (!user) {
    badge.style.display = 'none';
    return;
  }

  badge.style.display = 'flex';

  // Build badge content
  const emailSpan = badge.querySelector('.whoami-email');
  const roleSpan = badge.querySelector('.whoami-role');
  const tenantSpan = badge.querySelector('.whoami-tenant');
  const logoutBtn = badge.querySelector('.whoami-logout');

  if (emailSpan) {
    emailSpan.textContent = user.email || user.user_id || 'Anonymous';
  }

  if (roleSpan) {
    roleSpan.textContent = user.role || '-';
    roleSpan.className = `whoami-role role-${user.role || 'unknown'}`;
  }

  if (tenantSpan) {
    tenantSpan.textContent = user.tenant_id || 'default';
  }

  if (logoutBtn) {
    // Only show logout button if auth is enabled
    logoutBtn.style.display = authState.isEnabled ? 'inline-block' : 'none';
  }
}

/**
 * Create WhoAmI badge HTML element
 * @returns {HTMLElement}
 */
function createWhoAmiBadge() {
  const badge = document.createElement('div');
  badge.id = 'whoamiBadge';
  badge.className = 'whoami-badge';
  badge.innerHTML = `
    <div class="whoami-info">
      <span class="whoami-email"></span>
      <span class="whoami-role"></span>
    </div>
    <div class="whoami-meta">
      <span class="whoami-tenant"></span>
    </div>
    <button class="whoami-logout" onclick="logout()" title="Wyloguj">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
        <polyline points="16 17 21 12 16 7"></polyline>
        <line x1="21" y1="12" x2="9" y2="12"></line>
      </svg>
    </button>
  `;
  badge.style.display = 'none';
  return badge;
}

// ============================================
// INITIALIZATION
// ============================================

/**
 * Initialize auth module
 * - Check auth mode
 * - Fetch current user if authenticated
 * - Setup WhoAmI badge
 * - Redirect to login if needed
 */
async function initAuth() {
  console.log('[AUTH] Initializing auth module...');
  authState.loading = true;

  try {
    // Check if auth is enabled
    const isEnabled = await checkAuthMode();
    console.log('[AUTH] Auth mode:', isEnabled ? 'enabled' : 'disabled');

    if (isEnabled) {
      // Auth is enabled - check if we have a valid session
      const token = getAuthToken();

      if (token) {
        // Try to fetch current user with token
        const user = await fetchCurrentUser();

        if (!user) {
          // Token is invalid - redirect to login
          console.log('[AUTH] Invalid token - redirecting to login');
          window.location.href = AUTH_CONFIG.loginPath;
          return;
        }
      } else {
        // No token - redirect to login (unless we're already on login page)
        if (!window.location.pathname.includes('login')) {
          console.log('[AUTH] No token - redirecting to login');
          window.location.href = AUTH_CONFIG.loginPath;
          return;
        }
      }
    }

    // Setup WhoAmI badge
    const headerInfo = document.querySelector('.header-info');
    if (headerInfo && !document.getElementById('whoamiBadge')) {
      const badge = createWhoAmiBadge();
      headerInfo.insertBefore(badge, headerInfo.firstChild);
    }

    updateWhoAmiBadge();

  } catch (error) {
    console.error('[AUTH] Init error:', error);
  } finally {
    authState.loading = false;
  }
}

// ============================================
// API KEYS MANAGEMENT (for admin page)
// ============================================

/**
 * List API keys for current tenant
 * @returns {Promise<{items: Array, total: number}>}
 */
async function listApiKeys() {
  const response = await authFetch(`${AUTH_CONFIG.baseUrl}/admin/api-keys`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail?.message || 'Failed to list API keys');
  }

  return response.json();
}

/**
 * Create a new API key
 * @param {object} params - Key parameters
 * @param {string} params.label - Key label
 * @param {string} params.role - Key role (viewer, editor, service)
 * @param {number} [params.expires_days] - Optional expiration in days
 * @returns {Promise<{key_id: string, key: string, label: string, role: string}>}
 */
async function createApiKey({ label, role, expires_days }) {
  const response = await authFetch(`${AUTH_CONFIG.baseUrl}/admin/api-keys`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label, role, expires_days }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail?.message || 'Failed to create API key');
  }

  return response.json();
}

/**
 * Revoke an API key
 * @param {string} keyId - Key ID to revoke
 * @returns {Promise<void>}
 */
async function revokeApiKey(keyId) {
  const response = await authFetch(`${AUTH_CONFIG.baseUrl}/admin/api-keys/${keyId}`, {
    method: 'DELETE',
  });

  if (!response.ok && response.status !== 204) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail?.message || 'Failed to revoke API key');
  }
}

// ============================================
// AUDIT LOG (for admin page)
// ============================================

/**
 * Query audit log
 * @param {object} params - Query parameters
 * @returns {Promise<{items: Array, total: number}>}
 */
async function queryAuditLog(params = {}) {
  const searchParams = new URLSearchParams();
  if (params.action) searchParams.set('action', params.action);
  if (params.actor_id) searchParams.set('actor_id', params.actor_id);
  if (params.resource_type) searchParams.set('resource_type', params.resource_type);
  if (params.from_date) searchParams.set('from_date', params.from_date);
  if (params.to_date) searchParams.set('to_date', params.to_date);
  if (params.limit) searchParams.set('limit', params.limit);
  if (params.offset) searchParams.set('offset', params.offset);

  const response = await authFetch(`${AUTH_CONFIG.baseUrl}/audit?${searchParams}`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail?.message || 'Failed to query audit log');
  }

  return response.json();
}

/**
 * Export audit log as ZIP
 * @param {object} params - Export parameters (from_date, to_date)
 * @returns {Promise<Blob>}
 */
async function exportAuditZip(params = {}) {
  const searchParams = new URLSearchParams();
  if (params.from_date) searchParams.set('from_date', params.from_date);
  if (params.to_date) searchParams.set('to_date', params.to_date);

  const url = searchParams.toString()
    ? `${AUTH_CONFIG.baseUrl}/audit/export/zip?${searchParams}`
    : `${AUTH_CONFIG.baseUrl}/audit/export/zip`;

  const response = await authFetch(url);

  if (!response.ok) {
    throw new Error('Failed to export audit log');
  }

  return response.blob();
}

/**
 * Export audit log as CSV
 * @param {object} params - Export parameters (from_date, to_date)
 * @returns {Promise<Blob>}
 */
async function exportAuditCsv(params = {}) {
  const searchParams = new URLSearchParams();
  if (params.from_date) searchParams.set('from_date', params.from_date);
  if (params.to_date) searchParams.set('to_date', params.to_date);

  const url = searchParams.toString()
    ? `${AUTH_CONFIG.baseUrl}/audit/export/csv?${searchParams}`
    : `${AUTH_CONFIG.baseUrl}/audit/export/csv`;

  const response = await authFetch(url);

  if (!response.ok) {
    throw new Error('Failed to export audit log as CSV');
  }

  return response.blob();
}

/**
 * Export audit log as JSON
 * @param {object} params - Export parameters (from_date, to_date)
 * @returns {Promise<Blob>}
 */
async function exportAuditJson(params = {}) {
  const searchParams = new URLSearchParams();
  if (params.from_date) searchParams.set('from_date', params.from_date);
  if (params.to_date) searchParams.set('to_date', params.to_date);

  const url = searchParams.toString()
    ? `${AUTH_CONFIG.baseUrl}/audit/export/json?${searchParams}`
    : `${AUTH_CONFIG.baseUrl}/audit/export/json`;

  const response = await authFetch(url);

  if (!response.ok) {
    throw new Error('Failed to export audit log as JSON');
  }

  return response.blob();
}

// ============================================
// EXPORTS
// ============================================

// Export to window for use in other scripts
window.AUTH_CONFIG = AUTH_CONFIG;
window.authState = authState;

// Token management
window.setAuthToken = setAuthToken;
window.getAuthToken = getAuthToken;
window.isAuthenticated = isAuthenticated;
window.clearAuth = clearAuth;

// Auth actions
window.login = login;
window.logout = logout;
window.checkAuthMode = checkAuthMode;
window.fetchCurrentUser = fetchCurrentUser;
window.initAuth = initAuth;

// Auth-aware fetch
window.authFetch = authFetch;

// UI updates
window.updateWhoAmiBadge = updateWhoAmiBadge;

// Admin functions
window.listApiKeys = listApiKeys;
window.createApiKey = createApiKey;
window.revokeApiKey = revokeApiKey;
window.queryAuditLog = queryAuditLog;
window.exportAuditZip = exportAuditZip;
window.exportAuditCsv = exportAuditCsv;
window.exportAuditJson = exportAuditJson;

console.log('[AUTH] auth.js v3.1.0 - Auth Module Ready');
