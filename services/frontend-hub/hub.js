/**
 * PV Analyzer HUB - Central Dashboard
 * JavaScript Controller
 */

// ===========================================
// Configuration
// ===========================================

const API_BASE = '/api/db';

// Mode -> Module URL mapping
const MODE_URLS = {
    'pv_solo': '/config/',
    'pv_bess': '/profile/',
    'bess_solo': '/bess/',
    'peak_shaving': '/profile/?mode=peak_shaving',
    'arbitrage': '/profile/?mode=arbitrage'
};

// Mode names in Polish
const MODE_NAMES = {
    'pv_solo': 'Tylko PV',
    'pv_bess': 'PV + BESS',
    'bess_solo': 'Tylko BESS',
    'peak_shaving': 'Peak Shaving',
    'arbitrage': 'Arbitraż cenowy'
};

// Status names
const STATUS_NAMES = {
    'draft': 'Szkic',
    'active': 'Aktywny',
    'archived': 'Zarchiwizowany'
};

// ===========================================
// State
// ===========================================

let state = {
    companies: [],
    projects: [],
    selectedCompanyId: null,
    selectedProjectId: null,
    stats: null
};

// ===========================================
// API Functions
// ===========================================

async function fetchAPI(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'API Error');
        }

        return await response.json();
    } catch (error) {
        console.error(`API Error (${endpoint}):`, error);
        throw error;
    }
}

async function loadCompanies() {
    try {
        state.companies = await fetchAPI('/companies');
        renderCompanySelect();
    } catch (error) {
        console.warn('Could not load companies:', error);
        // Still render with empty list
        state.companies = [];
        renderCompanySelect();
    }
}

async function loadProjects(companyId = null) {
    try {
        let endpoint = '/projects';
        if (companyId) {
            endpoint += `?company_id=${companyId}`;
        }
        state.projects = await fetchAPI(endpoint);
        renderProjectSelect();
    } catch (error) {
        console.warn('Could not load projects:', error);
        state.projects = [];
        renderProjectSelect();
    }
}

async function loadStats() {
    try {
        state.stats = await fetchAPI('/stats');
        renderStats();
    } catch (error) {
        console.warn('Could not load stats:', error);
        // Show placeholders
        document.getElementById('statCompanies').textContent = '-';
        document.getElementById('statProjects').textContent = '-';
        document.getElementById('statProfiles').textContent = '-';
        document.getElementById('statAnalyses').textContent = '-';
    }
}

async function createProjectAPI(projectData) {
    return await fetchAPI('/projects', {
        method: 'POST',
        body: JSON.stringify(projectData)
    });
}

// ===========================================
// Render Functions
// ===========================================

function renderCompanySelect() {
    const select = document.getElementById('companySelect');
    select.innerHTML = '<option value="">Wszystkie firmy</option>';

    state.companies.forEach(company => {
        const option = document.createElement('option');
        option.value = company.id;
        option.textContent = company.name;
        if (company.id === state.selectedCompanyId) {
            option.selected = true;
        }
        select.appendChild(option);
    });
}

function renderProjectSelect() {
    const select = document.getElementById('projectSelect');
    select.innerHTML = '<option value="">Wybierz projekt...</option>';

    const projects = state.selectedCompanyId
        ? state.projects.filter(p => p.company_id === state.selectedCompanyId)
        : state.projects;

    projects.forEach(project => {
        const option = document.createElement('option');
        option.value = project.id;
        option.textContent = project.name;
        if (project.company_name) {
            option.textContent += ` (${project.company_name})`;
        }
        if (project.id === state.selectedProjectId) {
            option.selected = true;
        }
        select.appendChild(option);
    });

    updateProjectInfo();
}

function updateProjectInfo() {
    const infoDiv = document.getElementById('projectInfo');
    const project = state.projects.find(p => p.id === state.selectedProjectId);

    if (!project) {
        infoDiv.classList.add('hidden');
        return;
    }

    infoDiv.classList.remove('hidden');

    document.getElementById('badgeLocation').textContent = project.location_name || 'Brak lokalizacji';
    document.getElementById('badgeMode').textContent = MODE_NAMES[project.analysis_mode] || project.analysis_mode;
    document.getElementById('badgeStatus').textContent = STATUS_NAMES[project.status] || project.status;

    // Update status badge color
    const statusBadge = document.getElementById('badgeStatus');
    statusBadge.className = 'badge';
    if (project.status === 'active') {
        statusBadge.classList.add('badge-success');
    } else if (project.status === 'archived') {
        statusBadge.classList.add('badge-warning');
    } else {
        statusBadge.classList.add('badge-info');
    }

    // Highlight matching mode card
    highlightModeCard(project.analysis_mode);
}

function highlightModeCard(mode) {
    document.querySelectorAll('.mode-card').forEach(card => {
        card.style.borderColor = '';
    });

    const matchingCard = document.querySelector(`.mode-card[data-mode="${mode}"]`);
    if (matchingCard) {
        matchingCard.style.borderColor = 'var(--success)';
    }
}

function renderStats() {
    if (!state.stats) return;

    document.getElementById('statCompanies').textContent = state.stats.companies_count;
    document.getElementById('statProjects').textContent = state.stats.projects_count;
    document.getElementById('statProfiles').textContent = state.stats.profiles_count;
    document.getElementById('statAnalyses').textContent = state.stats.analyses_count;
}

// ===========================================
// Event Handlers
// ===========================================

function onCompanyChange(event) {
    const companyId = event.target.value ? parseInt(event.target.value) : null;
    state.selectedCompanyId = companyId;
    state.selectedProjectId = null;

    // Save to sessionStorage
    if (companyId) {
        sessionStorage.setItem('selectedCompanyId', companyId);
    } else {
        sessionStorage.removeItem('selectedCompanyId');
    }
    sessionStorage.removeItem('selectedProjectId');

    renderProjectSelect();
}

function onProjectChange(event) {
    const projectId = event.target.value ? parseInt(event.target.value) : null;
    state.selectedProjectId = projectId;

    // Save to sessionStorage
    if (projectId) {
        sessionStorage.setItem('selectedProjectId', projectId);

        // Find project and notify parent shell
        const project = state.projects.find(p => p.id === projectId);
        if (project && window.parent && window.parent !== window) {
            window.parent.postMessage({
                type: 'PROJECT_SELECTED',
                project: project
            }, '*');
            console.log('📁 Sent PROJECT_SELECTED to shell:', project.name);
        }
    } else {
        sessionStorage.removeItem('selectedProjectId');

        // Notify parent that project was cleared
        if (window.parent && window.parent !== window) {
            window.parent.postMessage({
                type: 'PROJECT_CLEARED'
            }, '*');
        }
    }

    updateProjectInfo();
}

function selectMode(mode) {
    // Save selected mode
    sessionStorage.setItem('selectedMode', mode);

    // Update project mode if project is selected (optional - project not required)
    if (state.selectedProjectId) {
        updateProjectMode(state.selectedProjectId, mode);
    }

    // Notify shell about mode change
    if (window.parent && window.parent !== window) {
        window.parent.postMessage({
            type: 'MODE_SELECTED',
            mode: mode
        }, '*');
    }

    // Determine target module based on mode
    let targetModule = 'settings';
    if (mode === 'bess_solo') {
        targetModule = 'bess';
    }

    if (window.parent && window.parent !== window) {
        window.parent.postMessage({
            type: 'NAVIGATE_TO_MODULE',
            module: targetModule,
            params: {
                mode: mode,
                project_id: state.selectedProjectId || null
            }
        }, '*');
        console.log('🧭 Mode selected:', mode, '- navigating to', targetModule.toUpperCase());
    } else {
        window.location.href = `/modules/${targetModule}/`;
    }
}

// Update project analysis_mode in database
async function updateProjectMode(projectId, mode) {
    try {
        await fetch(`${API_BASE}/projects/${projectId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ analysis_mode: mode })
        });
        console.log('Updated project mode to:', mode);
    } catch (error) {
        console.error('Error updating project mode:', error);
    }
}

// ===========================================
// Navigation Helper
// ===========================================

function navigateToModule(moduleName) {
    // Navigate via parent shell (postMessage)
    if (window.parent && window.parent !== window) {
        window.parent.postMessage({
            type: 'NAVIGATE_TO_MODULE',
            module: moduleName,
            params: {}
        }, '*');
    } else {
        // Fallback: direct navigation
        const moduleUrls = {
            'consumption': '/modules/consumption/',
            'production': '/modules/production/',
            'config': '/modules/config/',
            'profile': '/modules/profile/',
            'economics': '/modules/economics/',
            'reports': '/modules/reports/',
            'bess': '/modules/bess/',
            'settings': '/modules/settings/'
        };
        window.location.href = moduleUrls[moduleName] || '/';
    }
}

// ===========================================
// Modal Functions
// ===========================================

// State for new project modal
let selectedCompanyForProject = null;
let searchTimeout = null;

function showNewProjectModal() {
    // Reset state
    selectedCompanyForProject = null;
    document.getElementById('newProjectModal').classList.remove('hidden');
    document.getElementById('companySearch').value = '';
    document.getElementById('companySearch').focus();
    document.getElementById('selectedCompanyInfo').classList.add('hidden');
    document.getElementById('newCompanyForm').classList.add('hidden');
    document.getElementById('companySearchResults').classList.add('hidden');
    document.getElementById('selectedCompanyId').value = '';
}

function hideNewProjectModal() {
    document.getElementById('newProjectModal').classList.add('hidden');
    document.getElementById('newProjectForm').reset();
    selectedCompanyForProject = null;
}

// Company search with debounce
async function searchCompanies(query) {
    const resultsDiv = document.getElementById('companySearchResults');

    // Clear timeout for debounce
    if (searchTimeout) clearTimeout(searchTimeout);

    if (!query || query.length < 2) {
        resultsDiv.classList.add('hidden');
        document.getElementById('newCompanyForm').classList.add('hidden');
        return;
    }

    // Debounce search
    searchTimeout = setTimeout(async () => {
        try {
            const response = await fetch(`${API_BASE}/companies?search=${encodeURIComponent(query)}&limit=5`);
            const companies = await response.json();

            resultsDiv.innerHTML = '';

            if (companies.length > 0) {
                companies.forEach(company => {
                    const item = document.createElement('div');
                    item.className = 'search-result-item';
                    item.innerHTML = `
                        <div class="company-name">${company.name}</div>
                        <div class="company-nip">NIP: ${company.nip || 'brak'}</div>
                    `;
                    item.onclick = () => selectCompany(company);
                    resultsDiv.appendChild(item);
                });
            }

            // Add "Create new" option
            const createOption = document.createElement('div');
            createOption.className = 'search-result-create';
            createOption.textContent = '+ Utwórz nową firmę';
            createOption.onclick = () => showNewCompanyForm(query);
            resultsDiv.appendChild(createOption);

            resultsDiv.classList.remove('hidden');
        } catch (error) {
            console.error('Error searching companies:', error);
        }
    }, 300);
}

function selectCompany(company) {
    selectedCompanyForProject = company;
    document.getElementById('selectedCompanyId').value = company.id;
    document.getElementById('selectedCompanyName').textContent = company.name;
    document.getElementById('selectedCompanyNip').textContent = `NIP: ${company.nip || 'brak'}`;

    document.getElementById('companySearch').value = '';
    document.getElementById('companySearchResults').classList.add('hidden');
    document.getElementById('selectedCompanyInfo').classList.remove('hidden');
    document.getElementById('newCompanyForm').classList.add('hidden');

    // Focus on project name
    document.getElementById('projectName').focus();
}

function clearSelectedCompany() {
    selectedCompanyForProject = null;
    document.getElementById('selectedCompanyId').value = '';
    document.getElementById('selectedCompanyInfo').classList.add('hidden');
    document.getElementById('companySearch').focus();
}

function showNewCompanyForm(prefillName) {
    document.getElementById('companySearchResults').classList.add('hidden');
    document.getElementById('newCompanyForm').classList.remove('hidden');
    document.getElementById('selectedCompanyInfo').classList.add('hidden');

    // Check if prefillName looks like NIP (all digits)
    if (/^\d+$/.test(prefillName)) {
        document.getElementById('newCompanyNip').value = prefillName;
        document.getElementById('newCompanyName').focus();
    } else {
        document.getElementById('newCompanyName').value = prefillName;
        document.getElementById('newCompanyNip').focus();
    }

    selectedCompanyForProject = null;
    document.getElementById('selectedCompanyId').value = '';
}

async function createCompanyIfNeeded() {
    // If company already selected, return its ID
    if (selectedCompanyForProject) {
        return selectedCompanyForProject.id;
    }

    // Check if new company form is visible
    const newCompanyForm = document.getElementById('newCompanyForm');
    if (newCompanyForm.classList.contains('hidden')) {
        return null; // No company selected or created
    }

    // Create new company
    const companyName = document.getElementById('newCompanyName').value.trim();
    const companyNip = document.getElementById('newCompanyNip').value.trim();

    if (!companyName) {
        alert('Podaj nazwę firmy');
        return null;
    }

    try {
        const response = await fetch(`${API_BASE}/companies`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: companyName,
                nip: companyNip || null
            })
        });

        if (!response.ok) {
            throw new Error('Błąd tworzenia firmy');
        }

        const newCompany = await response.json();
        console.log('Created new company:', newCompany);

        // Reload companies list
        await loadCompanies();

        return newCompany.id;
    } catch (error) {
        console.error('Error creating company:', error);
        alert('Błąd tworzenia firmy: ' + error.message);
        return null;
    }
}

async function createProject(event) {
    event.preventDefault();

    // Get or create company
    const companyId = await createCompanyIfNeeded();
    if (!companyId) {
        alert('Wybierz lub utwórz firmę');
        return;
    }

    // Get selected mode from radio buttons
    const modeRadio = document.querySelector('input[name="projectMode"]:checked');
    const analysisMode = modeRadio ? modeRadio.value : 'pv_bess';
    console.log('Creating project with analysis_mode:', analysisMode);

    const projectData = {
        name: document.getElementById('projectName').value,
        description: null,
        location_name: document.getElementById('projectLocation').value || null,
        latitude: null,
        longitude: null,
        analysis_mode: analysisMode,
        company_id: companyId,
        status: 'draft'
    };

    console.log('Project data to send:', projectData);

    try {
        const newProject = await createProjectAPI(projectData);
        console.log('Project created:', newProject);

        // Reload projects
        await loadProjects(state.selectedCompanyId);

        // Select new project
        state.selectedProjectId = newProject.id;
        sessionStorage.setItem('selectedProjectId', newProject.id);

        // Notify parent shell about the new project
        if (window.parent && window.parent !== window) {
            window.parent.postMessage({
                type: 'PROJECT_SELECTED',
                project: newProject
            }, '*');
            console.log('📁 Sent PROJECT_SELECTED to shell:', newProject.name, 'mode:', newProject.analysis_mode);
        }

        renderProjectSelect();
        hideNewProjectModal();

        // Always navigate to SETTINGS first - this is the logical first step
        // Workflow: USTAWIENIA -> ZUŻYCIE -> KONFIGURACJA PV -> PRODUKCJA PV -> ANALIZA -> BESS
        if (window.parent && window.parent !== window) {
            window.parent.postMessage({
                type: 'NAVIGATE_TO_MODULE',
                module: 'settings',
                params: {
                    mode: newProject.analysis_mode,
                    project_id: newProject.id
                }
            }, '*');
            console.log('🧭 Navigating to SETTINGS (first step for new project)');
        }

    } catch (error) {
        alert(`Błąd tworzenia projektu: ${error.message}`);
    }
}

// ===========================================
// Initialization
// ===========================================

async function init() {
    // Restore state from sessionStorage
    const savedCompanyId = sessionStorage.getItem('selectedCompanyId');
    const savedProjectId = sessionStorage.getItem('selectedProjectId');

    if (savedCompanyId) {
        state.selectedCompanyId = parseInt(savedCompanyId);
    }
    if (savedProjectId) {
        state.selectedProjectId = parseInt(savedProjectId);
    }

    // Setup event listeners
    document.getElementById('companySelect').addEventListener('change', onCompanyChange);
    document.getElementById('projectSelect').addEventListener('change', onProjectChange);

    // Close modal on outside click
    document.getElementById('newProjectModal').addEventListener('click', (e) => {
        if (e.target.id === 'newProjectModal') {
            hideNewProjectModal();
        }
    });

    // Close modal on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            hideNewProjectModal();
        }
    });

    // Load data
    await Promise.all([
        loadCompanies(),
        loadProjects(),
        loadStats()
    ]);

    console.log('HUB initialized', state);
}

// Start when DOM is ready
document.addEventListener('DOMContentLoaded', init);
