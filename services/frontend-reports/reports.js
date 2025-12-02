/**
 * Reports Frontend - Generator raportów PDF
 */

const API_BASE = 'http://localhost:8011';

// State
let currentPdfData = null;
let previewHtml = null;
let sharedData = null;  // Data from shell

// ============== Initialization ==============

document.addEventListener('DOMContentLoaded', () => {
    // Set default date
    document.getElementById('report-date').value = new Date().toISOString().split('T')[0];

    // Check connection
    checkConnection();

    // Listen for shared data from shell
    window.addEventListener('message', handleShellMessage);

    // Request shared data from shell
    window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');

    console.log('Reports module initialized, requesting shared data...');

    // Initial check (with delay to allow shell response)
    setTimeout(updateDataStatus, 1000);
});

// ============== Connection Check ==============

async function checkConnection() {
    const statusIndicator = document.querySelector('.status-indicator');
    const statusText = document.querySelector('.status-text');

    try {
        const response = await fetch(`${API_BASE}/health`);
        const data = await response.json();

        statusIndicator.classList.add('connected');
        statusIndicator.classList.remove('error');

        if (data.weasyprint_available) {
            statusText.textContent = 'Połączono - PDF dostępny (WeasyPrint)';
        } else {
            statusText.textContent = 'Połączono - PDF niedostępny (brak WeasyPrint)';
        }
    } catch (error) {
        statusIndicator.classList.add('error');
        statusIndicator.classList.remove('connected');
        statusText.textContent = 'Błąd połączenia z serwisem raportów';
    }
}

// ============== Data Status ==============

function updateDataStatus() {
    // Check what data we have from shell
    const hasConsumption = sharedData?.consumptionData || sharedData?.analysisResults?.consumption_stats;
    const hasSeasonality = sharedData?.analysisResults?.seasonality;
    const hasPV = sharedData?.analysisResults?.scenarios || sharedData?.analysisResults?.key_variants;
    const hasEconomics = sharedData?.masterVariant || sharedData?.analysisResults?.key_variants;

    setChecklistStatus('check-consumption', !!hasConsumption);
    setChecklistStatus('check-seasonality', !!hasSeasonality);
    setChecklistStatus('check-pv', !!hasPV);
    setChecklistStatus('check-economics', !!hasEconomics, hasEconomics ? null : 'pending');

    // Log status
    console.log('Data status:', {
        consumption: !!hasConsumption,
        seasonality: !!hasSeasonality,
        pv: !!hasPV,
        economics: !!hasEconomics,
        sharedData: sharedData
    });

    // Update variant selector based on available data
    updateVariantSelector();
}

function updateVariantSelector() {
    const select = document.getElementById('selected-variant');
    const keyVariants = sharedData?.analysisResults?.key_variants;

    if (keyVariants) {
        // Clear existing options except first
        while (select.options.length > 1) {
            select.remove(1);
        }

        // Add available variants
        if (keyVariants.variant_a) {
            addVariantOption(select, 'variant_a', `Wariant A (${keyVariants.variant_a.auto_consumption_pct?.toFixed(0) || 90}% autokons.) - ${(keyVariants.variant_a.capacity/1000).toFixed(1)} MWp`);
        }
        if (keyVariants.variant_b) {
            addVariantOption(select, 'variant_b', `Wariant B (${keyVariants.variant_b.auto_consumption_pct?.toFixed(0) || 80}% autokons.) - ${(keyVariants.variant_b.capacity/1000).toFixed(1)} MWp`);
        }
        if (keyVariants.variant_c) {
            addVariantOption(select, 'variant_c', `Wariant C (${keyVariants.variant_c.auto_consumption_pct?.toFixed(0) || 70}% autokons.) - ${(keyVariants.variant_c.capacity/1000).toFixed(1)} MWp`);
        }
        if (keyVariants.npv_optimal) {
            addVariantOption(select, 'npv_optimal', `NPV Optimal - ${(keyVariants.npv_optimal.capacity/1000).toFixed(1)} MWp`);
        }

        // If master variant is set, select it
        if (sharedData?.masterVariantKey) {
            select.value = sharedData.masterVariantKey;
        }
    }
}

function addVariantOption(select, value, text) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = text;
    select.appendChild(option);
}

function setChecklistStatus(elementId, available, status = null) {
    const element = document.getElementById(elementId);
    const icon = element.querySelector('.check-icon');

    if (available) {
        element.classList.add('ready');
        element.classList.remove('missing');
        icon.textContent = status === 'pending' ? '⏳' : '✅';
    } else {
        element.classList.add('missing');
        element.classList.remove('ready');
        icon.textContent = '❌';
    }
}

// ============== Shell Communication ==============

function handleShellMessage(event) {
    const { type, data } = event.data;

    switch (type) {
        case 'SHARED_DATA_RESPONSE':
            console.log('📦 Received shared data from shell:', data);
            sharedData = data;
            updateDataStatus();
            break;

        case 'ANALYSIS_RESULTS':
            console.log('📊 Received analysis results');
            if (data) {
                sharedData = {
                    ...sharedData,
                    analysisResults: data.fullResults || data,
                    hourlyData: data.hourlyData,
                    pvConfig: data.pvConfig
                };
            }
            updateDataStatus();
            break;

        case 'MASTER_VARIANT_CHANGED':
            console.log('🎯 Master variant changed:', data);
            if (data) {
                sharedData = {
                    ...sharedData,
                    masterVariant: data.variantData,
                    masterVariantKey: data.variantKey
                };
            }
            updateDataStatus();
            break;

        case 'SETTINGS_UPDATED':
            console.log('⚙️ Settings updated');
            break;
    }
}

// ============== Report Configuration ==============

function getReportConfig() {
    const sections = Array.from(document.querySelectorAll('.sections-list input:checked'))
        .map(cb => cb.value);

    // Prepare frontend data to send to backend
    const frontendData = {
        analysisResults: sharedData?.analysisResults || {},
        hourlyData: sharedData?.hourlyData || null,
        masterVariant: sharedData?.masterVariant || null,
        masterVariantKey: sharedData?.masterVariantKey || null,
        pvConfig: sharedData?.pvConfig || null,
        consumptionData: sharedData?.consumptionData || null,
        settings: sharedData?.settings || null,
        economics: sharedData?.economics || null  // EaaS comparison data from Economics module
    };

    return {
        client_name: document.getElementById('client-name').value || 'Klient',
        location: document.getElementById('location').value || 'Polska',
        report_date: document.getElementById('report-date').value || null,
        selected_variant: document.getElementById('selected-variant').value || null,
        include_sections: sections,
        frontend_data: frontendData
    };
}

// ============== Preview Report ==============

async function previewReport() {
    const btn = document.getElementById('btn-preview');
    const container = document.getElementById('preview-container');

    btn.disabled = true;
    btn.textContent = '⏳ Generowanie...';

    try {
        const config = getReportConfig();
        console.log('📤 Sending report config:', config);

        const response = await fetch(`${API_BASE}/generate-html`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (!response.ok) {
            throw new Error('Błąd generowania podglądu');
        }

        const html = await response.text();
        previewHtml = html;

        // Create iframe for preview
        container.innerHTML = '';
        const iframe = document.createElement('iframe');
        iframe.className = 'report-preview-frame';
        container.appendChild(iframe);

        // Write HTML to iframe
        const doc = iframe.contentDocument || iframe.contentWindow.document;
        doc.open();
        doc.write(html);
        doc.close();

        // Adjust iframe height
        setTimeout(() => {
            try {
                const height = doc.body.scrollHeight + 50;
                iframe.style.height = Math.max(height, 600) + 'px';
            } catch (e) {
                console.log('Could not adjust iframe height');
            }
        }, 500);

    } catch (error) {
        console.error('Preview error:', error);
        container.innerHTML = `
            <div class="preview-placeholder">
                <div class="placeholder-icon">❌</div>
                <p>Błąd podczas generowania podglądu</p>
                <p class="hint">${error.message}</p>
            </div>
        `;
    } finally {
        btn.disabled = false;
        btn.textContent = '👁️ Podgląd HTML';
    }
}

function refreshPreview() {
    // Re-request shared data before refreshing
    window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
    setTimeout(previewReport, 300);
}

function openInNewTab() {
    if (!previewHtml) {
        alert('Najpierw wygeneruj podgląd raportu');
        return;
    }

    const newWindow = window.open('', '_blank');
    newWindow.document.write(previewHtml);
    newWindow.document.close();
}

// ============== Generate PDF ==============

async function generatePDF() {
    const btn = document.getElementById('btn-generate');
    const loadingOverlay = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');

    btn.disabled = true;
    loadingOverlay.classList.remove('hidden');
    loadingText.textContent = 'Generowanie raportu PDF...';

    try {
        const config = getReportConfig();
        console.log('📤 Generating PDF with config:', config);

        const response = await fetch(`${API_BASE}/generate-pdf`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Błąd generowania PDF');
        }

        const result = await response.json();

        if (result.status === 'success') {
            currentPdfData = result;
            showDownloadModal(result);
        } else {
            throw new Error('Nieoczekiwany błąd');
        }

    } catch (error) {
        console.error('PDF generation error:', error);
        alert(`Błąd generowania PDF: ${error.message}`);
    } finally {
        btn.disabled = false;
        loadingOverlay.classList.add('hidden');
    }
}

// ============== Download Modal ==============

function showDownloadModal(result) {
    const modal = document.getElementById('download-modal');
    const filename = document.getElementById('pdf-filename');
    const size = document.getElementById('pdf-size');

    filename.textContent = result.filename;
    size.textContent = `Rozmiar: ${formatFileSize(result.size_bytes)}`;

    modal.classList.remove('hidden');
}

function closeModal() {
    document.getElementById('download-modal').classList.add('hidden');
}

function downloadPDF() {
    if (!currentPdfData || !currentPdfData.pdf_base64) {
        alert('Brak danych PDF do pobrania');
        return;
    }

    // Convert base64 to blob and download
    const byteCharacters = atob(currentPdfData.pdf_base64);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], { type: 'application/pdf' });

    // Create download link
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = currentPdfData.filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    closeModal();
}

// ============== Utilities ==============

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}
