/**
 * Customer Portal Integration for Energy Studio
 *
 * HARD BUSINESS RULES:
 * 1. Publish ONLY selected_option_key from Portfolio (INTEGRATION_MISMATCH on violation)
 * 2. Redaction guard must PASS before publish
 * 3. Blockers = STOP, Warnings = proceed with caution
 * 4. Credit terms are READ-ONLY from Portfolio
 * 5. Drift warning only for selected_option snapshot
 */

const DATABASE_API = 'http://localhost:8050';

// BANNED_FIELDS for customer-safe data (must match backend BANNED_FIELDS_CUSTOMER_SAFE)
// These are EXACT field names that must NEVER appear in customer-facing data
// NOTE: cost_pln in CustomerSafeYearlyCashflow is OK - it's the customer's payment, not internal cost
const BANNED_FIELDS_CUSTOMER_SAFE = [
  // Cost/Margin fields (INTERNAL economics)
  'capex_deal_direct_cost_pln',
  'capex_deal_gross_margin_pct',
  'capex_deal_gross_margin_pln',
  'direct_cost',
  'direct_cost_pln',
  'gross_margin',
  'gross_margin_pct',
  'gross_margin_pln',
  // Investor fields (INTERNAL economics)
  'eaas_investor_target_irr',
  'eaas_investor_project_irr',
  'eaas_investor_equity_irr',
  'eaas_investor_capex_pln',
  'eaas_investor_capex0_pln',
  'eaas_investor_debt_pln',
  'eaas_investor_equity_pln',
  'eaas_investor_leverage_pct',
  'eaas_investor_npv',
  'eaas_investor_revenue_annual',
  'eaas_investor_opex_annual',
  'eaas_investor_cit_rate_pct',
  'eaas_investor_contract_revenue_pln',
  'eaas_investor_contract_opex_pln',
  'eaas_investor_cumulative_cashflow',
  'eaas_investor_yearly_cashflow',
  // Internal payloads
  'full_payload',
  'calc_metadata',
  'request_payload',
  'result_payload',
  // Integration IDs (internal references)
  'portfolio_company_id',
  'hubspot_company_id',
  'hubspot_deal_id',
  // Credit internals
  'credit_risk_class',
  'credit_decision_source',
  'credit_approved_by'
];

// ============== STATE ==============

let portalState = {
  projectId: null,
  project: null,
  // Company data (required for NIP-based versioning)
  company: null,
  // Selected from Portfolio (READ-ONLY in ES)
  selectedOptionKey: null,
  selectedSnapshotId: null,
  // Credit terms from Portfolio (READ-ONLY)
  creditTerms: null,
  // Offer package for preview
  offerPackage: null,
  // Readiness state
  isReady: false,
  blockers: [],    // STOP - cannot publish
  warnings: [],    // PROCEED with caution
  // Redaction guard state
  redactionGuardPassed: null, // true, false, or null (not checked)
  redactionViolations: [],
  // Drift state
  hasDrift: false,
  latestSnapshotId: null,
  // User role
  userRole: 'admin' // admin, internal, customer
};

// ============== INITIALIZATION ==============

function initCustomerPortal() {
  console.log('[CustomerPortal] Initializing...');

  // Listen for project events from parent (shell)
  window.addEventListener('message', handlePortalMessage);

  // Request current project info
  requestProjectInfo();

  // Detect user role
  detectUserRole();

  // Apply access control based on role
  applyAccessControl();

  // Show empty state initially
  updateBanner();

  console.log('[CustomerPortal] Initialized, role:', portalState.userRole);
}

// ============== ACCESS CONTROL ==============

function detectUserRole() {
  try {
    const token = localStorage.getItem('authToken') ||
                  sessionStorage.getItem('authToken') ||
                  'admin_energy_studio'; // Default for Energy Studio

    if (token.startsWith('admin_')) {
      portalState.userRole = 'admin';
    } else if (token.startsWith('internal_')) {
      portalState.userRole = 'internal';
    } else if (token.startsWith('customer_')) {
      portalState.userRole = 'customer';
    } else {
      portalState.userRole = 'admin'; // Default
    }
  } catch (e) {
    portalState.userRole = 'admin';
  }
}

function applyAccessControl() {
  const role = portalState.userRole;

  // Admin-only elements (publish button)
  document.querySelectorAll('[data-admin-only="true"]').forEach(el => {
    if (role !== 'admin') {
      el.style.display = 'none';
    } else {
      el.style.display = '';
    }
  });

  // Internal-only elements (history button)
  document.querySelectorAll('[data-internal-only="true"]').forEach(el => {
    if (role === 'customer') {
      el.style.display = 'none';
    } else {
      el.style.display = '';
    }
  });
}

// ============== MESSAGE HANDLING ==============

function handlePortalMessage(event) {
  const { type, data } = event.data || {};

  if (type === 'PROJECT_INFO_RESPONSE' || type === 'PROJECT_LOADED' || type === 'PROJECT_CHANGED') {
    const projectId = data?.projectId || data?.id;
    if (projectId) {
      console.log('[CustomerPortal] Project event received, id=', projectId);
      loadProjectData(projectId);
    }
  }

  if (type === 'SHARED_DATA_RESPONSE') {
    if (data?.currentProject?.id) {
      console.log('[CustomerPortal] Shared data received, project id=', data.currentProject.id);
      loadProjectData(data.currentProject.id);
    }
  }

  if (type === 'PROJECT_FINALIZED') {
    if (data?.id) {
      console.log('[CustomerPortal] Project finalized, id=', data.id);
      loadProjectData(data.id);
    }
  }
}

function requestProjectInfo() {
  window.parent.postMessage({ type: 'REQUEST_PROJECT_INFO' }, '*');
  window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
}

// ============== LOAD PROJECT DATA ==============

async function loadProjectData(projectId) {
  if (!projectId) return;

  portalState.projectId = projectId;

  try {
    // 1. Fetch project with integration data
    const projectRes = await fetch(`${DATABASE_API}/projects/${projectId}`);
    if (!projectRes.ok) {
      console.error('[CustomerPortal] Failed to fetch project');
      return;
    }

    const projectData = await projectRes.json();
    const project = projectData.project || projectData;

    portalState.project = project;
    portalState.selectedOptionKey = project.selected_option_key;
    portalState.selectedSnapshotId = project.selected_snapshot_id;

    console.log('[CustomerPortal] Project loaded:', {
      id: project.id,
      name: project.name,
      selectedOption: project.selected_option_key,
      selectedSnapshot: project.selected_snapshot_id,
      offerId: project.offer_id,
      offerVersion: project.offer_version
    });

    // 2. Load company data (required for NIP-based versioning)
    if (project.company_id) {
      await loadCompanyData(project.company_id);
      await loadCreditTerms(project.company_id);
    } else {
      portalState.company = null;
    }

    // 3. Check for snapshot drift
    await checkSnapshotDrift();

    // 4. Validate publish readiness
    validateReadiness();

    // 5. Update UI
    updateBanner();

    // 6. Highlight selected option in comparison tables
    if (portalState.selectedOptionKey) {
      highlightSelectedOption(portalState.selectedOptionKey);
    }

  } catch (error) {
    console.error('[CustomerPortal] Error loading project data:', error);
  }
}

async function loadCompanyData(companyId) {
  try {
    const response = await fetch(`${DATABASE_API}/companies/${companyId}`);
    if (response.ok) {
      portalState.company = await response.json();
      console.log('[CustomerPortal] Company loaded:', {
        id: portalState.company.id,
        name: portalState.company.name,
        nip: portalState.company.nip ? '***' + portalState.company.nip.slice(-4) : null
      });
    } else {
      portalState.company = null;
      console.warn('[CustomerPortal] Company not found:', companyId);
    }
  } catch (error) {
    console.error('[CustomerPortal] Error loading company:', error);
    portalState.company = null;
  }
}

async function loadCreditTerms(companyId) {
  try {
    const response = await fetch(`${DATABASE_API}/companies/${companyId}/credit-decision`, {
      headers: { 'Authorization': 'Bearer internal_energy_studio' }
    });

    if (response.ok) {
      portalState.creditTerms = await response.json();
      console.log('[CustomerPortal] Credit terms loaded:', portalState.creditTerms);
    } else if (response.status === 404) {
      portalState.creditTerms = null;
      console.log('[CustomerPortal] No credit terms for company');
    }
  } catch (error) {
    console.error('[CustomerPortal] Error loading credit terms:', error);
    portalState.creditTerms = null;
  }
}

async function checkSnapshotDrift() {
  portalState.hasDrift = false;
  portalState.latestSnapshotId = null;

  if (!portalState.projectId || !portalState.selectedSnapshotId) return;

  try {
    const response = await fetch(`${DATABASE_API}/projects/${portalState.projectId}/economics-snapshot`);
    if (!response.ok) return;

    const snapshots = await response.json();
    if (snapshots.length === 0) return;

    // Latest snapshot is first (ordered by created_at DESC)
    portalState.latestSnapshotId = snapshots[0].id;

    // Drift = selected is not latest
    if (portalState.selectedSnapshotId !== portalState.latestSnapshotId) {
      portalState.hasDrift = true;
      console.log('[CustomerPortal] Snapshot drift detected:',
        `selected=${portalState.selectedSnapshotId}, latest=${portalState.latestSnapshotId}`);
    }
  } catch (error) {
    console.error('[CustomerPortal] Error checking drift:', error);
  }
}

// ============== READINESS VALIDATION ==============

function validateReadiness() {
  portalState.blockers = [];
  portalState.warnings = [];

  const project = portalState.project;
  const credit = portalState.creditTerms;

  // === BLOCKERS (STOP) ===

  // 0. Company data required for Customer Portal
  const company = portalState.company;

  if (!company) {
    portalState.blockers.push({
      code: 'NO_COMPANY',
      message: 'Brak przypisanej firmy do projektu',
      fix: 'Otwórz Projekty i przypisz firmę do projektu'
    });
  } else {
    // 0a. Company name required
    if (!company.name || !company.name.trim()) {
      portalState.blockers.push({
        code: 'NO_COMPANY_NAME',
        message: 'Brak nazwy firmy',
        fix: 'Otwórz Projekty → Dane Klienta i uzupełnij nazwę firmy'
      });
    }

    // 0b. NIP required for Customer Portal (versioning based on NIP)
    if (!company.nip || !company.nip.trim()) {
      portalState.blockers.push({
        code: 'NO_NIP',
        message: 'Brak NIP firmy (wymagany do wersjonowania ofert)',
        fix: 'Otwórz Projekty → Dane Klienta i uzupełnij NIP'
      });
    }
  }

  // 1. No selected option from Portfolio
  if (!project?.selected_option_key) {
    portalState.blockers.push({
      code: 'NO_SELECTED_OPTION',
      message: 'Brak wybranej opcji w Portfolio',
      fix: 'Otwórz Portfolio Management i wybierz wariant (A/B/C/D)'
    });
  }

  // 2. No snapshot for selected option
  if (!project?.selected_snapshot_id) {
    portalState.blockers.push({
      code: 'NO_SNAPSHOT',
      message: 'Brak snapshotu ekonomicznego',
      fix: 'Wygeneruj snapshot w Economics i przypisz w Portfolio'
    });
  }

  // 3. Redaction guard failed (if already checked)
  if (portalState.redactionGuardPassed === false) {
    portalState.blockers.push({
      code: 'REDACTION_GUARD_FAIL',
      message: 'Wykryto zabronione pola w danych klienta',
      fix: 'Skontaktuj się z administratorem - błąd bezpieczeństwa danych'
    });
  }

  // 4. Approval required but not approved (if credit terms say so)
  if (credit?.approval_required && !credit?.approved_at) {
    portalState.blockers.push({
      code: 'APPROVAL_REQUIRED',
      message: 'Wymagana akceptacja managera',
      fix: 'Poczekaj na akceptację w Portfolio Management'
    });
  }

  // === WARNINGS (PROCEED WITH CAUTION) ===

  // 1. Snapshot drift
  if (portalState.hasDrift) {
    portalState.warnings.push({
      code: 'SNAPSHOT_DRIFT',
      message: `Snapshot #${portalState.selectedSnapshotId} nie jest najnowszy (latest: #${portalState.latestSnapshotId})`,
      fix: 'Rozważ aktualizację snapshotu w Portfolio'
    });
  }

  // 2. No credit terms
  if (!credit) {
    portalState.warnings.push({
      code: 'NO_CREDIT_TERMS',
      message: 'Brak warunków kredytowych',
      fix: 'Ustaw warunki kredytowe w Portfolio Management'
    });
  }

  // 3. No HubSpot integration
  if (!project?.hubspot_deal_id) {
    portalState.warnings.push({
      code: 'NO_HUBSPOT',
      message: 'Brak integracji z HubSpot',
      fix: 'Przypisz HubSpot Deal ID w Portfolio'
    });
  }

  // Final readiness
  portalState.isReady = portalState.blockers.length === 0;

  console.log('[CustomerPortal] Readiness check:', {
    isReady: portalState.isReady,
    blockers: portalState.blockers.length,
    warnings: portalState.warnings.length
  });

  return portalState.isReady;
}

// ============== BANNER UPDATE ==============

function updateBanner() {
  const banner = document.getElementById('integrationStatusBanner');
  if (!banner) {
    console.warn('[CustomerPortal] Banner element not found');
    return;
  }

  const project = portalState.project;

  // Always show banner
  banner.style.display = 'flex';

  // No project = empty state
  if (!project) {
    banner.innerHTML = `
      <div class="banner-section" style="flex:1;text-align:center;padding:20px;">
        <div class="banner-title" style="color:#90caf9;font-size:14px;margin-bottom:8px;">
          📋 CUSTOMER PORTAL
        </div>
        <div style="color:rgba(255,255,255,0.7);font-size:13px;">
          Zapisz projekt do bazy danych, aby zobaczyć status publikacji.
        </div>
        <div style="color:rgba(255,255,255,0.5);font-size:11px;margin-top:8px;">
          Użyj przycisku "💾 Zapisz projekt" na górnym pasku aplikacji.
        </div>
      </div>
    `;
    return;
  }

  // Full banner with real data
  const credit = portalState.creditTerms;

  const company = portalState.company;
  const hasNip = company?.nip && company.nip.trim();
  const hasCompanyName = company?.name && company.name.trim();

  banner.innerHTML = `
    <!-- COMPANY / CLIENT SECTION -->
    <div class="banner-section" style="flex:1;min-width:140px;padding:0 16px;border-right:1px solid rgba(255,255,255,0.15);">
      <div class="banner-title" style="color:#a5d6a7;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">
        🏢 KLIENT
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="color:rgba(255,255,255,0.6);font-size:11px;">Firma:</span>
          <span style="color:${hasCompanyName ? 'white' : '#ff5252'};font-size:11px;max-width:90px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${company?.name || ''}">
            ${hasCompanyName ? company.name : 'BRAK'}
          </span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="color:rgba(255,255,255,0.6);font-size:11px;">NIP:</span>
          <span style="color:${hasNip ? '#4caf50' : '#ff5252'};font-family:monospace;font-size:11px;">
            ${hasNip ? company.nip : 'BRAK'}
          </span>
        </div>
      </div>
    </div>

    <!-- INTEGRATION SECTION -->
    <div class="banner-section" style="flex:1;min-width:160px;padding:0 16px;border-right:1px solid rgba(255,255,255,0.15);">
      <div class="banner-title" style="color:#90caf9;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">
        🔗 INTEGRACJA
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="color:rgba(255,255,255,0.6);font-size:11px;">Offer ID:</span>
          <span style="color:${project.offer_id ? '#ffc107' : 'rgba(255,255,255,0.4)'};font-family:monospace;font-size:12px;">
            ${project.offer_id ? `${project.offer_id}` : 'Brak'}
          </span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="color:rgba(255,255,255,0.6);font-size:11px;">Wersja:</span>
          <span style="color:white;font-size:12px;font-weight:600;">
            ${project.offer_version || '-'}
          </span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="color:rgba(255,255,255,0.6);font-size:11px;">HubSpot:</span>
          <span style="color:${project.hubspot_deal_id ? '#4caf50' : 'rgba(255,255,255,0.4)'};font-size:11px;">
            ${project.hubspot_deal_id ? '✓ Połączono' : 'Nie połączono'}
          </span>
        </div>
      </div>
    </div>

    <!-- SELECTED OPTION (from Portfolio - READ ONLY) -->
    <div class="banner-section" style="flex:1;min-width:180px;padding:12px 16px;background:rgba(76,175,80,0.15);border-radius:8px;margin:0 8px;">
      <div class="banner-title" style="color:#a5d6a7;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">
        ✅ WYBRANA OPCJA (Portfolio)
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="color:rgba(255,255,255,0.6);font-size:11px;">Wariant:</span>
          <span style="color:${project.selected_option_key ? '#69f0ae' : '#ff5252'};font-size:14px;font-weight:700;">
            ${project.selected_option_key ? `Wariant ${project.selected_option_key}` : 'NIE WYBRANO'}
          </span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="color:rgba(255,255,255,0.6);font-size:11px;">Snapshot:</span>
          <span style="color:${project.selected_snapshot_id ? 'white' : '#ff5252'};font-size:12px;font-weight:600;">
            ${project.selected_snapshot_id ? `#${project.selected_snapshot_id}` : 'BRAK'}
          </span>
        </div>
        ${portalState.hasDrift ? `
          <div style="background:#ff9800;color:white;padding:4px 8px;border-radius:4px;font-size:10px;font-weight:600;margin-top:4px;text-align:center;">
            ⚠️ Snapshot nieaktualny (latest: #${portalState.latestSnapshotId})
          </div>
        ` : ''}
      </div>
    </div>

    <!-- CREDIT TERMS (from Portfolio - READ ONLY) -->
    <div class="banner-section" style="flex:1;min-width:160px;padding:12px 16px;background:rgba(33,150,243,0.1);border-radius:8px;margin-right:8px;">
      <div class="banner-title" style="color:#81d4fa;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">
        📊 WARUNKI KREDYTOWE
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="color:rgba(255,255,255,0.6);font-size:11px;">Max EaaS:</span>
          <span style="color:white;font-size:12px;font-weight:600;">
            ${credit?.max_eaas_duration_years ? `${credit.max_eaas_duration_years} lat` : 'Brak limitu'}
          </span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="color:rgba(255,255,255,0.6);font-size:11px;">Depozyt:</span>
          <span style="color:white;font-size:12px;font-weight:600;">
            ${credit?.required_deposit_pct ? `${credit.required_deposit_pct}%` : '-'}
          </span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="color:rgba(255,255,255,0.6);font-size:11px;">Klasa ryzyka:</span>
          <span style="color:${credit?.credit_risk_class ? '#4caf50' : 'rgba(255,255,255,0.4)'};font-size:12px;font-weight:600;">
            ${credit?.credit_risk_class || 'Nie określono'}
          </span>
        </div>
        ${credit?.approval_required ? `
          <div style="background:#ff9800;color:white;padding:4px 8px;border-radius:4px;font-size:10px;font-weight:600;margin-top:4px;text-align:center;">
            ⚠️ Wymaga akceptacji
          </div>
        ` : ''}
      </div>
    </div>

    <!-- STATUS & ACTIONS -->
    <div class="banner-section" style="min-width:200px;padding:0 16px;display:flex;flex-direction:column;align-items:flex-end;justify-content:center;gap:10px;">
      <!-- Status badges -->
      <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;">
        <span id="bannerReadyBadge" style="
          padding:6px 12px;
          border-radius:16px;
          font-size:11px;
          font-weight:700;
          text-transform:uppercase;
          background:${portalState.isReady ? 'linear-gradient(135deg,#00c853,#00e676)' : '#f44336'};
          color:${portalState.isReady ? '#1b5e20' : 'white'};
        ">${portalState.isReady ? 'READY' : 'NOT READY'}</span>

        ${project.offer_published_at ? `
          <span style="
            padding:6px 12px;
            border-radius:16px;
            font-size:11px;
            font-weight:700;
            text-transform:uppercase;
            background:linear-gradient(135deg,#2196f3,#03a9f4);
            color:white;
          ">PUBLISHED ${project.offer_version || 'v1'}</span>
        ` : ''}
      </div>

      <!-- Blockers indicator -->
      ${portalState.blockers.length > 0 ? `
        <div style="font-size:10px;color:#ff5252;text-align:right;max-width:180px;">
          🚫 ${portalState.blockers.length} blokad${portalState.blockers.length === 1 ? 'a' : 'y'} - kliknij Publikuj aby zobaczyć
        </div>
      ` : ''}

      <!-- Action buttons -->
      <div style="display:flex;gap:8px;">
        <button onclick="openCustomerPreview()" id="btnCustomerPreview" style="
          padding:8px 14px;
          border:none;
          border-radius:6px;
          font-size:12px;
          font-weight:600;
          cursor:pointer;
          background:#2196f3;
          color:white;
          transition:all 0.2s;
        ">👁️ Podgląd</button>

        <button onclick="openPublishModal()" id="btnPublishOffer" data-admin-only="true" style="
          padding:8px 14px;
          border:none;
          border-radius:6px;
          font-size:12px;
          font-weight:600;
          cursor:pointer;
          background:${portalState.isReady ? 'linear-gradient(135deg,#00c853,#00e676)' : 'rgba(255,255,255,0.1)'};
          color:${portalState.isReady ? '#1b5e20' : 'rgba(255,255,255,0.4)'};
          transition:all 0.2s;
        ">📤 Publikuj</button>

        <button onclick="openPublicationHistory()" id="btnPublicationHistory" data-internal-only="true" style="
          padding:8px 14px;
          border:none;
          border-radius:6px;
          font-size:12px;
          font-weight:600;
          cursor:pointer;
          background:rgba(255,255,255,0.15);
          color:white;
          transition:all 0.2s;
        ">📋</button>
      </div>
    </div>
  `;

  // Re-apply access control
  applyAccessControl();
}

// ============== CUSTOMER PREVIEW ==============

async function openCustomerPreview() {
  const modal = document.getElementById('customerPreviewModal');
  if (!modal) {
    console.warn('[CustomerPortal] Preview modal not found');
    return;
  }

  modal.style.display = 'flex';

  const guardStatus = document.getElementById('previewGuardStatus');
  const content = document.getElementById('customerPreviewContent');

  // Show loading
  if (guardStatus) {
    guardStatus.innerHTML = '🔄 Sprawdzanie bezpieczeństwa danych...';
    guardStatus.className = 'guard-status checking';
  }
  if (content) {
    content.innerHTML = '<div class="loading">Ładowanie podglądu CUSTOMER_SAFE...</div>';
  }

  try {
    // Fetch offer-package (always CUSTOMER_SAFE from backend)
    const response = await fetch(
      `${DATABASE_API}/projects/${portalState.projectId}/offer-package?allow_draft=true`,
      { headers: { 'Authorization': 'Bearer internal_energy_studio' } }
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    const offerPackage = await response.json();
    portalState.offerPackage = offerPackage;

    // Run redaction guard check
    const guardResult = runRedactionGuard(offerPackage);
    portalState.redactionGuardPassed = guardResult.passed;
    portalState.redactionViolations = guardResult.violations;

    // Update guard status
    if (guardStatus) {
      if (guardResult.passed) {
        guardStatus.innerHTML = '✅ PASS: Dane bezpieczne dla klienta (CUSTOMER_SAFE)';
        guardStatus.className = 'guard-status pass';
      } else {
        guardStatus.innerHTML = `🚫 FAIL: Wykryto ${guardResult.violations.length} zabronion${guardResult.violations.length === 1 ? 'e pole' : 'ych pól'}!`;
        guardStatus.className = 'guard-status fail';
        console.error('[CustomerPortal] REDACTION GUARD FAIL:', guardResult.violations);

        // Log security event
        logSecurityEvent('DATA_LEAK_PREVENTED', {
          projectId: portalState.projectId,
          violations: guardResult.violations
        });
      }
    }

    // Render preview
    if (content) {
      content.innerHTML = renderOfferPreview(offerPackage);
    }

    // Update offer info
    const offerInfo = document.getElementById('previewOfferInfo');
    if (offerInfo) {
      offerInfo.textContent = offerPackage.offer_id
        ? `${offerPackage.offer_id} ${offerPackage.offer_version || ''}`
        : 'Wersja robocza (draft)';
    }

    // Re-validate readiness (guard result affects blockers)
    validateReadiness();
    updateBanner();

  } catch (error) {
    console.error('[CustomerPortal] Preview error:', error);
    if (guardStatus) {
      guardStatus.innerHTML = '⚠️ Błąd pobierania danych';
      guardStatus.className = 'guard-status error';
    }
    if (content) {
      content.innerHTML = `<div class="error-message">${error.message}</div>`;
    }
  }
}

function closeCustomerPreview() {
  const modal = document.getElementById('customerPreviewModal');
  if (modal) modal.style.display = 'none';
}

function runRedactionGuard(data) {
  const violations = [];

  // Pre-compute banned set for O(1) lookup
  const bannedLower = new Set(BANNED_FIELDS_CUSTOMER_SAFE.map(f => f.toLowerCase()));

  function checkObject(obj, path = '') {
    if (typeof obj !== 'object' || obj === null) return;

    for (const [key, value] of Object.entries(obj)) {
      const currentPath = path ? `${path}.${key}` : key;
      const keyLower = key.toLowerCase();

      // EXACT match only - no substring matching
      // This prevents false positives like 'cost_pln' (customer payment) being
      // flagged when only 'direct_cost_pln' (internal cost) should be banned
      if (bannedLower.has(keyLower)) {
        violations.push({
          path: currentPath,
          field: key,
          bannedField: key
        });
      }

      // Recurse into nested objects and arrays
      if (Array.isArray(value)) {
        value.forEach((item, idx) => {
          if (typeof item === 'object' && item !== null) {
            checkObject(item, `${currentPath}[${idx}]`);
          }
        });
      } else if (typeof value === 'object' && value !== null) {
        checkObject(value, currentPath);
      }
    }
  }

  checkObject(data);

  return {
    passed: violations.length === 0,
    violations
  };
}

function logSecurityEvent(eventType, details) {
  console.warn(`[SECURITY] ${eventType}:`, details);

  // Could send to backend for audit logging
  // fetch(`${DATABASE_API}/security-events`, { ... })
}

function renderOfferPreview(offer) {
  if (!offer) return '<div class="empty">Brak danych</div>';

  const inst = offer.installation || {};
  const capex = offer.capex_economics || {};
  const eaas = offer.eaas_economics || {};

  return `
    <div class="offer-preview">
      <!-- Installation -->
      <div class="preview-section">
        <h4>📦 Instalacja</h4>
        <div class="preview-grid">
          <div class="preview-item">
            <span class="label">Moc PV</span>
            <span class="value">${inst.pv_capacity_kwp || '-'} kWp</span>
          </div>
          <div class="preview-item">
            <span class="label">Typ</span>
            <span class="value">${inst.pv_type || '-'}</span>
          </div>
          <div class="preview-item">
            <span class="label">BESS</span>
            <span class="value">${inst.has_bess ? `Tak (${inst.bess_capacity_kwh || '-'} kWh)` : 'Nie'}</span>
          </div>
          <div class="preview-item">
            <span class="label">Lokalizacja</span>
            <span class="value">${inst.location_name || '-'}</span>
          </div>
        </div>
      </div>

      <!-- CAPEX Economics (customer view) -->
      <div class="preview-section">
        <h4>💰 Model CAPEX (zakup)</h4>
        <div class="preview-grid">
          <div class="preview-item highlight">
            <span class="label">Inwestycja</span>
            <span class="value">${formatCurrency(capex.investment_pln)} PLN</span>
          </div>
          <div class="preview-item">
            <span class="label">NPV (25 lat)</span>
            <span class="value">${formatCurrency(capex.npv_pln)} PLN</span>
          </div>
          <div class="preview-item">
            <span class="label">IRR</span>
            <span class="value">${capex.irr_pct ? capex.irr_pct.toFixed(1) + '%' : '-'}</span>
          </div>
          <div class="preview-item">
            <span class="label">Payback</span>
            <span class="value">${capex.simple_payback_years ? capex.simple_payback_years.toFixed(1) + ' lat' : '-'}</span>
          </div>
        </div>
      </div>

      <!-- EaaS Economics (customer view) -->
      <div class="preview-section">
        <h4>📊 Model EaaS (subskrypcja)</h4>
        <div class="preview-grid">
          <div class="preview-item">
            <span class="label">Okres umowy</span>
            <span class="value">${eaas.duration_years || '-'} lat</span>
          </div>
          <div class="preview-item highlight">
            <span class="label">Rata roczna</span>
            <span class="value">${formatCurrency(eaas.subscription_annual_pln)} PLN</span>
          </div>
          <div class="preview-item">
            <span class="label">Rata miesięczna</span>
            <span class="value">${formatCurrency(eaas.subscription_monthly_pln)} PLN</span>
          </div>
          <div class="preview-item">
            <span class="label">NPV klienta</span>
            <span class="value">${formatCurrency(eaas.npv_pln)} PLN</span>
          </div>
        </div>
      </div>

      <!-- Options -->
      ${offer.options && offer.options.length > 0 ? `
        <div class="preview-section">
          <h4>📋 Dostępne warianty</h4>
          <div class="options-list">
            ${offer.options.map(opt => `
              <div class="option-item ${opt.is_selected ? 'selected' : ''}">
                <span class="option-key">${opt.option_key}</span>
                <span class="option-capacity">${opt.pv_capacity_kwp} kWp</span>
                ${opt.is_selected ? '<span class="selected-badge">WYBRANY</span>' : ''}
              </div>
            `).join('')}
          </div>
        </div>
      ` : ''}

      <!-- Metadata -->
      <div class="preview-meta" style="margin-top:20px;padding-top:16px;border-top:1px solid #e0e0e0;font-size:11px;color:#888;">
        <div>Snapshot ID: #${offer.snapshot_id || '-'}</div>
        <div>Wygenerowano: ${offer.created_at ? new Date(offer.created_at).toLocaleString('pl-PL') : '-'}</div>
        <div>Profile: CUSTOMER_SAFE</div>
      </div>
    </div>
  `;
}

function formatCurrency(value) {
  if (value == null || isNaN(value)) return '-';
  return new Intl.NumberFormat('pl-PL').format(Math.round(value));
}

// ============== PUBLISH MODAL ==============

async function openPublishModal() {
  const modal = document.getElementById('publishModal');
  if (!modal) {
    console.warn('[CustomerPortal] Publish modal not found');
    return;
  }

  // Refresh readiness
  validateReadiness();

  const project = portalState.project;
  const credit = portalState.creditTerms;

  // Calculate new version
  const currentVersion = project?.offer_version;
  let newVersion = 'v1';
  if (currentVersion) {
    const num = parseInt(currentVersion.replace('v', '')) || 0;
    newVersion = `v${num + 1}`;
  }

  // Render modal content
  modal.innerHTML = `
    <div class="modal-content" style="background:white;border-radius:16px;max-width:600px;max-height:90vh;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
      <div class="modal-header" style="background:linear-gradient(135deg,#1a237e,#283593);color:white;padding:20px 24px;display:flex;justify-content:space-between;align-items:center;">
        <h3 style="margin:0;font-size:18px;">📤 Publikuj ofertę do Customer Portal</h3>
        <button onclick="closePublishModal()" style="background:rgba(255,255,255,0.2);border:none;color:white;font-size:20px;width:36px;height:36px;border-radius:50%;cursor:pointer;">×</button>
      </div>

      <div class="modal-body" style="padding:24px;overflow-y:auto;max-height:60vh;">
        <!-- Summary -->
        <div style="background:#f8f9fa;border-radius:10px;padding:16px;margin-bottom:16px;">
          <h4 style="margin:0 0 12px 0;font-size:14px;color:#1a237e;">Podsumowanie publikacji</h4>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
            <div style="display:flex;justify-content:space-between;padding:8px 12px;background:white;border-radius:6px;">
              <span style="font-size:12px;color:#666;">Wariant:</span>
              <span style="font-size:13px;font-weight:600;color:${project?.selected_option_key ? '#2e7d32' : '#c62828'};">
                ${project?.selected_option_key ? `Wariant ${project.selected_option_key}` : 'NIE WYBRANO'}
              </span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:8px 12px;background:white;border-radius:6px;">
              <span style="font-size:12px;color:#666;">Snapshot:</span>
              <span style="font-size:13px;font-weight:600;color:${project?.selected_snapshot_id ? '#2c3e50' : '#c62828'};">
                ${project?.selected_snapshot_id ? `#${project.selected_snapshot_id}` : 'BRAK'}
              </span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:8px 12px;background:white;border-radius:6px;">
              <span style="font-size:12px;color:#666;">Offer ID:</span>
              <span style="font-size:13px;font-weight:600;color:#2c3e50;">
                ${project?.offer_id || 'Nowy (auto)'}
              </span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:8px 12px;background:white;border-radius:6px;">
              <span style="font-size:12px;color:#666;">Nowa wersja:</span>
              <span style="font-size:13px;font-weight:600;color:#1565c0;">${newVersion}</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:8px 12px;background:white;border-radius:6px;grid-column:span 2;">
              <span style="font-size:12px;color:#666;">Warunki kredytowe:</span>
              <span style="font-size:13px;font-weight:600;color:#2c3e50;">
                ${credit?.credit_risk_class ? `Klasa ${credit.credit_risk_class}, max ${credit.max_eaas_duration_years || '?'} lat` : 'Brak'}
              </span>
            </div>
          </div>
        </div>

        <!-- Blockers -->
        ${portalState.blockers.length > 0 ? `
          <div style="background:#ffebee;border-radius:10px;padding:16px;margin-bottom:16px;border-left:4px solid #c62828;">
            <h4 style="margin:0 0 10px 0;font-size:14px;color:#c62828;">🚫 Blokady publikacji (${portalState.blockers.length})</h4>
            <ul style="margin:0;padding-left:20px;font-size:13px;color:#b71c1c;">
              ${portalState.blockers.map(b => `
                <li style="margin-bottom:8px;">
                  <strong>${b.message}</strong>
                  <div style="font-size:11px;color:#666;margin-top:2px;">💡 ${b.fix}</div>
                </li>
              `).join('')}
            </ul>
          </div>
        ` : ''}

        <!-- Warnings -->
        ${portalState.warnings.length > 0 ? `
          <div style="background:#fff3e0;border-radius:10px;padding:16px;border-left:4px solid #ff9800;">
            <h4 style="margin:0 0 10px 0;font-size:14px;color:#e65100;">⚠️ Ostrzeżenia (${portalState.warnings.length})</h4>
            <ul style="margin:0;padding-left:20px;font-size:13px;color:#bf360c;">
              ${portalState.warnings.map(w => `
                <li style="margin-bottom:6px;">
                  ${w.message}
                  <span style="font-size:10px;color:#888;margin-left:4px;">(${w.fix})</span>
                </li>
              `).join('')}
            </ul>
          </div>
        ` : ''}

        <!-- Ready state -->
        ${portalState.isReady ? `
          <div style="background:#e8f5e9;border-radius:10px;padding:16px;border-left:4px solid #4caf50;">
            <div style="display:flex;align-items:center;gap:10px;">
              <span style="font-size:24px;">✅</span>
              <div>
                <div style="font-size:14px;font-weight:600;color:#2e7d32;">Gotowe do publikacji</div>
                <div style="font-size:12px;color:#388e3c;">Wszystkie wymagania spełnione</div>
              </div>
            </div>
          </div>
        ` : ''}
      </div>

      <div class="modal-footer" style="padding:16px 24px;background:#f8f9fa;border-top:1px solid #e0e0e0;display:flex;justify-content:space-between;align-items:center;">
        <div style="font-size:11px;color:#666;">
          Publikacja utworzy nową wersję oferty dostępną dla klienta
        </div>
        <div style="display:flex;gap:12px;">
          <button onclick="closePublishModal()" style="padding:10px 20px;border:1px solid #ddd;background:white;border-radius:6px;font-size:13px;cursor:pointer;">
            Anuluj
          </button>
          <button onclick="confirmPublish()" id="btnConfirmPublish" ${portalState.isReady ? '' : 'disabled'} style="
            padding:10px 24px;
            border:none;
            border-radius:6px;
            font-size:13px;
            font-weight:600;
            cursor:${portalState.isReady ? 'pointer' : 'not-allowed'};
            background:${portalState.isReady ? 'linear-gradient(135deg,#00c853,#00e676)' : '#e0e0e0'};
            color:${portalState.isReady ? '#1b5e20' : '#999'};
          ">
            📤 Potwierdź publikację
          </button>
        </div>
      </div>
    </div>
  `;

  modal.style.display = 'flex';
}

function closePublishModal() {
  const modal = document.getElementById('publishModal');
  if (modal) modal.style.display = 'none';
}

async function confirmPublish() {
  if (!portalState.isReady) {
    showToast('Nie można opublikować - sprawdź blokady', 'error');
    return;
  }

  const project = portalState.project;

  // HARD RULE: Must have selected option and snapshot
  if (!project.selected_option_key || !project.selected_snapshot_id) {
    showToast('BŁĄD: Brak wybranej opcji lub snapshotu z Portfolio', 'error');
    return;
  }

  const btn = document.getElementById('btnConfirmPublish');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Publikowanie...';
  }

  try {
    // HARD RULE: Publish ONLY the selected option from Portfolio
    const response = await fetch(
      `${DATABASE_API}/projects/${portalState.projectId}/publish-to-customer-portal`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer admin_energy_studio'
        },
        body: JSON.stringify({
          // These MUST match what's in Portfolio - backend will verify
          snapshot_id: project.selected_snapshot_id,
          option_key: project.selected_option_key
        })
      }
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));

      // Handle INTEGRATION_MISMATCH specifically
      if (error.code === 'INTEGRATION_MISMATCH') {
        throw new Error('Niezgodność z Portfolio! Wybrana opcja/snapshot różni się od ustawień w Portfolio.');
      }

      throw new Error(error.detail || `Błąd publikacji (HTTP ${response.status})`);
    }

    const result = await response.json();

    console.log('[CustomerPortal] Published successfully:', result);

    closePublishModal();
    showToast(`✅ Opublikowano: ${result.offer_id} ${result.offer_version}`, 'success');

    // Refresh data
    await loadProjectData(portalState.projectId);

    // Open history
    setTimeout(() => openPublicationHistory(), 500);

  } catch (error) {
    console.error('[CustomerPortal] Publish error:', error);
    showToast(`❌ ${error.message}`, 'error');

    if (btn) {
      btn.disabled = false;
      btn.textContent = '📤 Potwierdź publikację';
    }
  }
}

// ============== PUBLICATION HISTORY ==============

async function openPublicationHistory() {
  const modal = document.getElementById('publicationHistoryModal');
  if (!modal) {
    console.warn('[CustomerPortal] History modal not found');
    return;
  }

  modal.innerHTML = `
    <div class="modal-content" style="background:white;border-radius:16px;max-width:700px;max-height:90vh;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
      <div class="modal-header" style="background:linear-gradient(135deg,#1a237e,#283593);color:white;padding:20px 24px;display:flex;justify-content:space-between;align-items:center;">
        <h3 style="margin:0;font-size:18px;">📋 Historia publikacji (internal-only)</h3>
        <button onclick="closePublicationHistory()" style="background:rgba(255,255,255,0.2);border:none;color:white;font-size:20px;width:36px;height:36px;border-radius:50%;cursor:pointer;">×</button>
      </div>

      <div class="modal-body" style="padding:24px;overflow-y:auto;max-height:70vh;">
        <div id="historyList" class="history-list">
          <div class="loading">Ładowanie historii...</div>
        </div>
      </div>
    </div>
  `;

  modal.style.display = 'flex';

  try {
    const response = await fetch(
      `${DATABASE_API}/projects/${portalState.projectId}/publication-history`,
      { headers: { 'Authorization': 'Bearer internal_energy_studio' } }
    );

    if (!response.ok) {
      if (response.status === 403) {
        throw new Error('Brak dostępu (wymagany token internal lub admin)');
      }
      throw new Error('Błąd pobierania historii');
    }

    const history = await response.json();
    const list = document.getElementById('historyList');

    if (history.length === 0) {
      list.innerHTML = '<div style="text-align:center;padding:40px;color:#888;">Brak historii publikacji</div>';
      return;
    }

    list.innerHTML = history.map((item, index) => `
      <div style="
        background:#f8f9fa;
        border-radius:10px;
        padding:14px 16px;
        margin-bottom:12px;
        border-left:4px solid ${index === 0 ? '#4caf50' : '#3f51b5'};
      ">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <div style="display:flex;align-items:center;gap:12px;">
            <span style="font-size:15px;font-weight:700;color:#1a237e;font-family:monospace;">
              ${item.offer_id} ${item.offer_version}
            </span>
            <span style="background:#e8f5e9;color:#2e7d32;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;">
              Wariant ${item.option_key || '-'}
            </span>
            ${index === 0 ? '<span style="background:#4caf50;color:white;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;">CURRENT</span>' : ''}
          </div>
          <span style="background:#e3f2fd;color:#1565c0;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:500;">
            ${item.action || 'publish'}
          </span>
        </div>
        <div style="display:flex;gap:16px;font-size:12px;color:#666;">
          <span>📅 ${new Date(item.published_at).toLocaleString('pl-PL')}</span>
          <span>📸 Snapshot #${item.snapshot_id || '-'}</span>
          ${item.credit_risk_class ? `<span>📊 Klasa ${item.credit_risk_class}</span>` : ''}
          ${item.published_by ? `<span>👤 ${item.published_by}</span>` : ''}
        </div>
      </div>
    `).join('');

  } catch (error) {
    console.error('[CustomerPortal] History error:', error);
    const list = document.getElementById('historyList');
    if (list) {
      list.innerHTML = `<div style="text-align:center;padding:20px;color:#c62828;background:#ffebee;border-radius:8px;">${error.message}</div>`;
    }
  }
}

function closePublicationHistory() {
  const modal = document.getElementById('publicationHistoryModal');
  if (modal) modal.style.display = 'none';
}

// ============== HIGHLIGHT SELECTED OPTION ==============

function highlightSelectedOption(optionKey) {
  if (!optionKey) return;

  console.log('[CustomerPortal] Highlighting selected option:', optionKey);

  // Find variant buttons/cards and highlight selected one
  const selectors = [
    '.variant-btn',
    '.option-btn',
    '[data-variant]',
    '.comparison-card',
    '.variant-card'
  ];

  selectors.forEach(selector => {
    document.querySelectorAll(selector).forEach(el => {
      const variant = el.dataset.variant || el.dataset.optionKey || el.textContent.trim();
      if (variant === optionKey || variant === `Wariant ${optionKey}` || variant.includes(`(${optionKey})`)) {
        el.classList.add('selected-from-portfolio');
        el.style.border = '3px solid #4caf50';
        el.style.boxShadow = '0 0 12px rgba(76,175,80,0.4)';
      } else {
        el.classList.remove('selected-from-portfolio');
      }
    });
  });

  // Add badge to comparison table headers
  document.querySelectorAll('.comparison-header, th, .variant-header').forEach(header => {
    const text = header.textContent.trim();
    if ((text.includes(optionKey) || text === `Wariant ${optionKey}`) && !header.querySelector('.portfolio-badge')) {
      const badge = document.createElement('span');
      badge.className = 'portfolio-badge';
      badge.style.cssText = 'background:#4caf50;color:white;font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;margin-left:6px;';
      badge.textContent = 'PORTFOLIO';
      header.appendChild(badge);
    }
  });
}

// ============== TOAST ==============

function showToast(message, type = 'info') {
  const existing = document.querySelector('.portal-toast');
  if (existing) existing.remove();

  const colors = {
    success: 'linear-gradient(135deg,#00c853,#00e676)',
    error: 'linear-gradient(135deg,#ff5252,#ff1744)',
    info: 'linear-gradient(135deg,#2196f3,#03a9f4)'
  };

  const toast = document.createElement('div');
  toast.className = 'portal-toast';
  toast.style.cssText = `
    position:fixed;
    bottom:30px;
    right:30px;
    padding:16px 24px;
    border-radius:10px;
    font-size:14px;
    font-weight:500;
    box-shadow:0 8px 24px rgba(0,0,0,0.2);
    z-index:20000;
    background:${colors[type] || colors.info};
    color:white;
    transform:translateY(100px);
    opacity:0;
    transition:all 0.3s ease-out;
  `;
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.style.transform = 'translateY(0)';
    toast.style.opacity = '1';
  }, 10);

  setTimeout(() => {
    toast.style.transform = 'translateY(100px)';
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ============== EXPORTS ==============

window.initCustomerPortal = initCustomerPortal;
window.loadProjectData = loadProjectData;
window.openCustomerPreview = openCustomerPreview;
window.closeCustomerPreview = closeCustomerPreview;
window.openPublishModal = openPublishModal;
window.closePublishModal = closePublishModal;
window.confirmPublish = confirmPublish;
window.openPublicationHistory = openPublicationHistory;
window.closePublicationHistory = closePublicationHistory;
window.highlightSelectedOption = highlightSelectedOption;
window.detectUserRole = detectUserRole;
window.applyAccessControl = applyAccessControl;
window.showToast = showToast;

// Backward compatibility
window.loadProjectIntegrationData = loadProjectData;

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', initCustomerPortal);

console.log('[CustomerPortal] Module loaded - HARD RULES ENFORCED');
