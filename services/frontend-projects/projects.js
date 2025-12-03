/**
 * PV Optimizer - Projects Module
 * Version: 1.8
 *
 * Handles project management: create, list, load, save, export
 */

const PROJECTS_API = 'http://localhost:8012';
let currentProjectId = null;
let sharedData = null;
let searchTimeout = null;

// ============== Initialization ==============

document.addEventListener('DOMContentLoaded', () => {
    console.log('Projects module loaded');
    initMessageListener();
    requestSharedData();
    loadProjects();
    loadCurrentProjectFromStorage();
});

function initMessageListener() {
    window.addEventListener('message', (event) => {
        const { type, data } = event.data;

        switch (type) {
            case 'SHARED_DATA_RESPONSE':
                console.log('Received shared data:', data);
                sharedData = data;
                break;

            case 'ANALYSIS_COMPLETE':
                console.log('Analysis complete - can save to project');
                showToast('Analiza zakończona - możesz zapisać wyniki', 'info');
                break;

            case 'ECONOMICS_CALCULATED':
                console.log('Economics calculated - can save to project');
                break;

            case 'PROJECT_LOADED':
                console.log('Project loaded:', data);
                if (data && data.projectId) {
                    setCurrentProject(data.projectId, data.projectName, data.clientName);
                }
                break;
        }
    });
}

function requestSharedData() {
    window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
}

// ============== Project List ==============

async function loadProjects() {
    const listEl = document.getElementById('projectsList');
    const emptyEl = document.getElementById('emptyState');

    listEl.innerHTML = '<div class="loading">Ładowanie projektów...</div>';
    emptyEl.style.display = 'none';

    const search = document.getElementById('searchInput').value;
    const status = document.getElementById('statusFilter').value;

    try {
        const params = new URLSearchParams();
        if (search) params.append('search', search);
        if (status) params.append('status', status);

        const response = await fetch(`${PROJECTS_API}/projects?${params.toString()}`);
        const result = await response.json();

        if (result.success && result.projects.length > 0) {
            listEl.innerHTML = result.projects.map(p => renderProjectCard(p)).join('');
            emptyEl.style.display = 'none';
        } else {
            listEl.innerHTML = '';
            emptyEl.style.display = 'block';
        }
    } catch (error) {
        console.error('Error loading projects:', error);
        listEl.innerHTML = `
            <div class="loading" style="color: #e74c3c;">
                Błąd ładowania projektów. Sprawdź czy serwis projects-db działa na porcie 8012.
            </div>
        `;
    }
}

function renderProjectCard(project) {
    const isCurrent = currentProjectId === project.id;
    const statusClass = project.status === 'archived' ? 'status-archived' : 'status-active';
    const createdDate = new Date(project.created_at).toLocaleDateString('pl-PL');
    const updatedDate = new Date(project.updated_at).toLocaleDateString('pl-PL');

    return `
        <div class="project-card ${isCurrent ? 'current' : ''}" onclick="openProjectDetails(${project.id})">
            <div class="project-info">
                <div class="project-name">${escapeHtml(project.project_name)}</div>
                <div class="project-client">${escapeHtml(project.client_name)}${project.client_nip ? ` (NIP: ${project.client_nip})` : ''}</div>
                <div class="project-meta">
                    <span>Utworzono: ${createdDate}</span>
                    <span>Zmieniono: ${updatedDate}</span>
                </div>
            </div>
            <div class="project-actions">
                <span class="project-status ${statusClass}">${project.status}</span>
            </div>
        </div>
    `;
}

function debounceSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        loadProjects();
    }, 300);
}

// ============== Project Details ==============

let selectedProjectId = null;

async function openProjectDetails(projectId) {
    selectedProjectId = projectId;

    try {
        // Load project info
        const projectRes = await fetch(`${PROJECTS_API}/projects/${projectId}`);
        const projectResult = await projectRes.json();

        if (!projectResult.success) {
            showToast('Nie znaleziono projektu', 'error');
            return;
        }

        const project = projectResult.project;

        // Update modal content
        document.getElementById('detailsProjectName').textContent = project.project_name;
        document.getElementById('detailsClientName').textContent = project.client_name;
        document.getElementById('detailsClientNip').textContent = project.client_nip || '-';
        document.getElementById('detailsStatus').textContent = project.status;
        document.getElementById('detailsCreated').textContent = new Date(project.created_at).toLocaleString('pl-PL');
        document.getElementById('detailsUpdated').textContent = new Date(project.updated_at).toLocaleString('pl-PL');
        document.getElementById('detailsDescription').textContent = project.description || '-';

        // Load project data types
        const dataRes = await fetch(`${PROJECTS_API}/projects/${projectId}/data`);
        const dataResult = await dataRes.json();

        const dataTypes = [
            { key: 'rawConsumptionData', name: 'Surowe dane zużycia (godzinowe)' },
            { key: 'consumptionData', name: 'Metadane zużycia' },
            { key: 'pvConfig', name: 'Konfiguracja PV' },
            { key: 'analysisResults', name: 'Wyniki analizy' },
            { key: 'hourlyData', name: 'Dane godzinowe PV' },
            { key: 'settings', name: 'Ustawienia' },
            { key: 'economics', name: 'Analiza ekonomiczna' },
            { key: 'masterVariant', name: 'Wybrany wariant' },
            { key: 'currentScenario', name: 'Scenariusz P50/P75/P90' }
        ];

        const dataListEl = document.getElementById('dataTypesList');
        dataListEl.innerHTML = dataTypes.map(dt => {
            const hasSaved = dataResult.data && dataResult.data[dt.key];
            return `
                <div class="data-type-item">
                    <span class="data-type-name">${dt.name}</span>
                    <span class="data-type-status ${hasSaved ? 'saved' : 'missing'}">
                        ${hasSaved ? 'Zapisane' : 'Brak'}
                    </span>
                </div>
            `;
        }).join('');

        // Show modal
        openModal('projectDetailsModal');

    } catch (error) {
        console.error('Error loading project details:', error);
        showToast('Błąd ładowania szczegółów projektu', 'error');
    }
}

// ============== Project Actions ==============

async function loadCurrentProject() {
    if (!selectedProjectId) return;

    try {
        const response = await fetch(`${PROJECTS_API}/projects/${selectedProjectId}/load-full`);
        const result = await response.json();

        if (!result.success) {
            showToast('Błąd wczytywania projektu', 'error');
            return;
        }

        console.log('Loading project data:', {
            hasRawConsumption: !!result.rawConsumptionData,
            rawConsumptionPoints: result.rawConsumptionData ? result.rawConsumptionData.data_points : 0,
            hasConsumption: !!result.consumptionData,
            hasAnalysis: !!result.analysisResults,
            hasSettings: !!result.settings
        });

        // Send loaded data to shell for distribution
        window.parent.postMessage({
            type: 'PROJECT_LOAD_REQUEST',
            data: {
                projectId: selectedProjectId,
                projectName: result.project.project_name,
                clientName: result.project.client_name,
                clientNip: result.project.client_nip,
                consumptionData: result.consumptionData,
                rawConsumptionData: result.rawConsumptionData, // KLUCZOWE: surowe dane godzinowe
                pvConfig: result.pvConfig,
                analysisResults: result.analysisResults,
                hourlyData: result.hourlyData,
                settings: result.settings,
                economics: result.economics,
                masterVariant: result.masterVariant,
                currentScenario: result.currentScenario
            }
        }, '*');

        // Update current project
        setCurrentProject(selectedProjectId, result.project.project_name, result.project.client_name);

        showToast(`Projekt "${result.project.project_name}" wczytany`, 'success');
        closeModal('projectDetailsModal');

    } catch (error) {
        console.error('Error loading project:', error);
        showToast('Błąd wczytywania projektu', 'error');
    }
}

async function deleteCurrentProject() {
    if (!selectedProjectId) return;

    if (!confirm('Czy na pewno chcesz usunąć ten projekt? Ta operacja jest nieodwracalna.')) {
        return;
    }

    try {
        const response = await fetch(`${PROJECTS_API}/projects/${selectedProjectId}`, {
            method: 'DELETE'
        });

        const result = await response.json();

        if (result.success) {
            showToast('Projekt usunięty', 'success');
            closeModal('projectDetailsModal');

            // Clear current project if it was deleted
            if (currentProjectId === selectedProjectId) {
                clearCurrentProject();
            }

            loadProjects();
        } else {
            showToast('Błąd usuwania projektu', 'error');
        }
    } catch (error) {
        console.error('Error deleting project:', error);
        showToast('Błąd usuwania projektu', 'error');
    }
}

async function archiveCurrentProject() {
    if (!selectedProjectId) return;

    try {
        const response = await fetch(`${PROJECTS_API}/projects/${selectedProjectId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'archived' })
        });

        const result = await response.json();

        if (result.success) {
            showToast('Projekt zarchiwizowany', 'success');
            closeModal('projectDetailsModal');
            loadProjects();
        } else {
            showToast('Błąd archiwizacji projektu', 'error');
        }
    } catch (error) {
        console.error('Error archiving project:', error);
        showToast('Błąd archiwizacji projektu', 'error');
    }
}

async function exportCurrentProject() {
    if (!selectedProjectId) return;

    try {
        const response = await fetch(`${PROJECTS_API}/projects/${selectedProjectId}/export`);
        const result = await response.json();

        // Download as JSON file
        const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `projekt_${selectedProjectId}_${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);

        showToast('Projekt wyeksportowany', 'success');
    } catch (error) {
        console.error('Error exporting project:', error);
        showToast('Błąd eksportu projektu', 'error');
    }
}

// ============== Create New Project ==============

function openNewProjectModal() {
    // Clear form
    document.getElementById('projectName').value = '';
    document.getElementById('clientName').value = '';
    document.getElementById('clientNip').value = '';
    document.getElementById('projectDescription').value = '';
    document.getElementById('saveCurrentData').checked = true;

    openModal('newProjectModal');
}

async function createProject() {
    const projectName = document.getElementById('projectName').value.trim();
    const clientName = document.getElementById('clientName').value.trim();
    const clientNip = document.getElementById('clientNip').value.trim();
    const description = document.getElementById('projectDescription').value.trim();
    const saveCurrentData = document.getElementById('saveCurrentData').checked;

    // Validation
    if (!projectName) {
        showToast('Podaj nazwę projektu', 'error');
        return;
    }
    if (!clientName) {
        showToast('Podaj nazwę klienta', 'error');
        return;
    }

    try {
        // Request fresh shared data before saving
        requestSharedData();
        await new Promise(resolve => setTimeout(resolve, 300));

        const projectData = {
            project_name: projectName,
            client_name: clientName,
            client_nip: clientNip || null,
            description: description || null
        };

        // If saving current data, add it to the request
        if (saveCurrentData && sharedData) {
            projectData.consumption_data = sharedData.consumptionData || null;
            projectData.pv_config = sharedData.pvConfig || null;
            projectData.analysis_results = sharedData.analysisResults || null;
            projectData.hourly_data = sharedData.hourlyData || null;
            projectData.settings = sharedData.settings || null;
            projectData.economics = sharedData.economics || null;
            projectData.master_variant = sharedData.masterVariant || null;
            projectData.current_scenario = sharedData.currentScenario || 'P50';
        }

        const response = await fetch(`${PROJECTS_API}/projects/save-full`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(projectData)
        });

        const result = await response.json();

        if (result.success) {
            showToast(`Projekt "${projectName}" utworzony`, 'success');
            setCurrentProject(result.project_id, projectName, clientName);
            closeModal('newProjectModal');
            loadProjects();

            // Notify shell about new project
            window.parent.postMessage({
                type: 'PROJECT_CREATED',
                data: {
                    projectId: result.project_id,
                    projectName: projectName,
                    clientName: clientName
                }
            }, '*');
        } else {
            showToast('Błąd tworzenia projektu', 'error');
        }
    } catch (error) {
        console.error('Error creating project:', error);
        showToast('Błąd tworzenia projektu', 'error');
    }
}

// ============== Save Current Project ==============

async function saveCurrentProject() {
    if (!currentProjectId) {
        showToast('Nie wybrano projektu - utwórz nowy', 'info');
        openNewProjectModal();
        return;
    }

    // Request fresh shared data
    requestSharedData();
    await new Promise(resolve => setTimeout(resolve, 300));

    if (!sharedData) {
        showToast('Brak danych do zapisania', 'error');
        return;
    }

    try {
        // Get current project info first
        const projectRes = await fetch(`${PROJECTS_API}/projects/${currentProjectId}`);
        const projectResult = await projectRes.json();

        if (!projectResult.success) {
            showToast('Projekt nie istnieje', 'error');
            clearCurrentProject();
            return;
        }

        const project = projectResult.project;

        const updateData = {
            project_name: project.project_name,
            client_name: project.client_name,
            client_nip: project.client_nip,
            description: project.description,
            consumption_data: sharedData.consumptionData || null,
            pv_config: sharedData.pvConfig || null,
            analysis_results: sharedData.analysisResults || null,
            hourly_data: sharedData.hourlyData || null,
            settings: sharedData.settings || null,
            economics: sharedData.economics || null,
            master_variant: sharedData.masterVariant || null,
            current_scenario: sharedData.currentScenario || 'P50'
        };

        const response = await fetch(`${PROJECTS_API}/projects/${currentProjectId}/save-full`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updateData)
        });

        const result = await response.json();

        if (result.success) {
            showToast('Projekt zapisany', 'success');
            loadProjects();
        } else {
            showToast('Błąd zapisywania projektu', 'error');
        }
    } catch (error) {
        console.error('Error saving project:', error);
        showToast('Błąd zapisywania projektu', 'error');
    }
}

// ============== Current Project Management ==============

function setCurrentProject(projectId, projectName, clientName) {
    currentProjectId = projectId;

    // Show current project bar
    const bar = document.getElementById('currentProjectBar');
    bar.style.display = 'flex';
    document.getElementById('currentProjectName').textContent = projectName;
    document.getElementById('currentProjectClient').textContent = clientName;

    // Save to localStorage
    localStorage.setItem('pv_current_project', JSON.stringify({
        id: projectId,
        name: projectName,
        client: clientName
    }));

    // Refresh list to show current indicator
    loadProjects();
}

function clearCurrentProject() {
    currentProjectId = null;
    document.getElementById('currentProjectBar').style.display = 'none';
    localStorage.removeItem('pv_current_project');
}

function loadCurrentProjectFromStorage() {
    const stored = localStorage.getItem('pv_current_project');
    if (stored) {
        try {
            const project = JSON.parse(stored);
            currentProjectId = project.id;
            document.getElementById('currentProjectBar').style.display = 'flex';
            document.getElementById('currentProjectName').textContent = project.name;
            document.getElementById('currentProjectClient').textContent = project.client;
        } catch (e) {
            localStorage.removeItem('pv_current_project');
        }
    }
}

// ============== Modal Management ==============

function openModal(modalId) {
    document.getElementById(modalId).classList.add('active');
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('active');
}

// Close modal on backdrop click
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) {
        e.target.classList.remove('active');
    }
});

// ============== Toast Notifications ==============

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 3000);
}

// ============== Utilities ==============

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatNumberEU(value, decimals = 2) {
    return value.toLocaleString('pl-PL', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

console.log('Projects module v1.8 initialized');
