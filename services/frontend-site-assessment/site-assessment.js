/**
 * Site Assessment Module - Full UX Wizard
 *
 * 4-step wizard for PV site assessment:
 * 1. Location - search and select location on map
 * 2. Area - draw polygon/rectangle to define installation area
 * 3. Configuration - select installation type and parameters
 * 4. Results - view calculated capacity and export
 *
 * APIs used:
 * - OpenStreetMap + Leaflet (map display)
 * - Nominatim (geocoding)
 * - PVGIS (solar irradiation and optimal angles)
 */

// ============================================================
// GLOBAL STATE
// ============================================================

const state = {
  currentStep: 1,
  location: {
    lat: 52.2297,
    lng: 21.0122,
    address: null,
    selected: false
  },
  area: {
    polygon: null,
    grossArea: 0,
    perimeter: 0,
    vertices: 0,
    drawn: false
  },
  config: {
    installationType: 'flat_roof',
    tilt: 35,
    azimuth: 180,
    roofAngle: 30,
    gcr: 0.40,
    modulePower: 580,
    moduleWidth: 1134,
    moduleHeight: 2278
  },
  pvgis: {
    optimalTilt: null,
    irradiance: null,
    specificYield: null,
    fetched: false
  },
  results: {
    capacityKwp: 0,
    moduleCount: 0,
    activeArea: 0,
    yearlyYieldMwh: 0,
    specificYield: 0
  }
};

// Map instances
let locationMap = null;
let drawingMap = null;
let drawnItems = null;
let drawControl = null;
let locationMarker = null;
let currentDrawHandler = null;

// Map layers
let streetLayer = null;
let satelliteLayer = null;
let currentLayer = 'satellite';

// ============================================================
// INITIALIZATION
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  initLocationMap();
  setupEventListeners();
  updateProgress();
  updateInstallationTypeUI();
});

function initLocationMap() {
  // Initialize Step 1 location map
  locationMap = L.map('map', {
    center: [state.location.lat, state.location.lng],
    zoom: 6,
    zoomControl: true
  });

  // Add base layers
  streetLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap',
    maxZoom: 19
  });

  satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: '&copy; Esri',
    maxZoom: 19
  });

  // Start with street view for location selection
  streetLayer.addTo(locationMap);

  // Click handler for location selection
  locationMap.on('click', onLocationMapClick);

  // Try geolocation
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        state.location.lat = pos.coords.latitude;
        state.location.lng = pos.coords.longitude;
        locationMap.setView([state.location.lat, state.location.lng], 12);
      },
      () => {} // Ignore errors
    );
  }
}

function initDrawingMap() {
  if (drawingMap) return; // Already initialized

  // Initialize Step 2 drawing map centered on selected location
  drawingMap = L.map('drawingMap', {
    center: [state.location.lat, state.location.lng],
    zoom: 18,
    zoomControl: true
  });

  // Add satellite layer by default for drawing
  satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: '&copy; Esri',
    maxZoom: 19
  }).addTo(drawingMap);

  streetLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap',
    maxZoom: 19
  });

  // Initialize drawing layer
  drawnItems = new L.FeatureGroup();
  drawingMap.addLayer(drawnItems);

  // Initialize drawing control
  drawControl = new L.Control.Draw({
    position: 'topright',
    draw: {
      polygon: {
        allowIntersection: false,
        drawError: {
          color: '#ef4444',
          message: 'Polygon nie może się przecinać!'
        },
        shapeOptions: {
          color: '#3b82f6',
          weight: 3,
          fillColor: '#3b82f6',
          fillOpacity: 0.3
        }
      },
      rectangle: {
        shapeOptions: {
          color: '#3b82f6',
          weight: 3,
          fillColor: '#3b82f6',
          fillOpacity: 0.3
        }
      },
      circle: false,
      circlemarker: false,
      marker: false,
      polyline: false
    },
    edit: {
      featureGroup: drawnItems,
      remove: true
    }
  });
  drawingMap.addControl(drawControl);

  // Drawing event handlers
  drawingMap.on(L.Draw.Event.CREATED, onPolygonCreated);
  drawingMap.on(L.Draw.Event.EDITED, onPolygonEdited);
  drawingMap.on(L.Draw.Event.DELETED, onPolygonDeleted);
  drawingMap.on(L.Draw.Event.DRAWSTART, () => {
    document.getElementById('drawingInstructions').classList.add('hidden');
  });

  // Update layer buttons
  document.getElementById('layerSatellite').classList.add('active');
  document.getElementById('layerStreet').classList.remove('active');
}

function setupEventListeners() {
  // Location search enter key
  document.getElementById('locationSearch').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') searchLocation();
  });

  // Installation type change
  document.querySelectorAll('input[name="installationType"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
      state.config.installationType = e.target.value;
      updateInstallationTypeUI();
    });
  });

  // Module parameter preview updates
  ['modulePower', 'moduleWidth', 'moduleHeight'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('input', updateModulePreview);
    }
  });
}

// ============================================================
// STEP NAVIGATION
// ============================================================

function goToStep(stepNumber) {
  // Validate transitions
  if (stepNumber === 2 && !state.location.selected) {
    showToast('Najpierw wybierz lokalizację na mapie', 'warning');
    return;
  }
  if (stepNumber === 3 && !state.area.drawn) {
    showToast('Najpierw narysuj obszar instalacji', 'warning');
    return;
  }

  // Hide current step
  document.getElementById(`step${state.currentStep}`).classList.remove('active');

  // Show target step
  state.currentStep = stepNumber;
  document.getElementById(`step${stepNumber}`).classList.add('active');

  // Update progress
  updateProgress();

  // Initialize step-specific components
  if (stepNumber === 2) {
    initDrawingMap();
    setTimeout(() => {
      drawingMap.invalidateSize();
      drawingMap.setView([state.location.lat, state.location.lng], 18);
    }, 100);
  }

  // Scroll to top
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function updateProgress() {
  const progressFill = document.getElementById('progressFill');
  progressFill.style.width = `${(state.currentStep / 4) * 100}%`;

  // Update step indicators
  document.querySelectorAll('.wizard-progress .step').forEach((step, index) => {
    const stepNum = index + 1;
    step.classList.remove('active', 'completed');

    if (stepNum === state.currentStep) {
      step.classList.add('active');
    } else if (stepNum < state.currentStep) {
      step.classList.add('completed');
    }
  });
}

// ============================================================
// STEP 1: LOCATION
// ============================================================

function onLocationMapClick(e) {
  state.location.lat = e.latlng.lat;
  state.location.lng = e.latlng.lng;
  state.location.selected = true;

  // Update or create marker
  if (locationMarker) {
    locationMarker.setLatLng(e.latlng);
  } else {
    locationMarker = L.marker(e.latlng, {
      icon: L.divIcon({
        className: 'location-marker',
        html: '<div style="background:#3b82f6;width:24px;height:24px;border-radius:50%;border:3px solid white;box-shadow:0 2px 10px rgba(0,0,0,0.3);"></div>',
        iconSize: [24, 24],
        iconAnchor: [12, 12]
      })
    }).addTo(locationMap);
  }

  // Update UI
  updateLocationDisplay();
  reverseGeocode(state.location.lat, state.location.lng);

  // Enable next button
  document.getElementById('btnNextStep1').disabled = false;

  // Show location details
  document.getElementById('locationDetails').style.display = 'grid';
}

async function searchLocation() {
  const query = document.getElementById('locationSearch').value.trim();

  if (!query) {
    showToast('Wpisz adres do wyszukania', 'warning');
    return;
  }

  try {
    const response = await fetch(
      `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=5&countrycodes=pl`,
      { headers: { 'Accept-Language': 'pl' } }
    );

    const results = await response.json();

    if (results.length === 0) {
      showToast('Nie znaleziono lokalizacji', 'error');
      return;
    }

    // Use first result
    const result = results[0];
    state.location.lat = parseFloat(result.lat);
    state.location.lng = parseFloat(result.lon);
    state.location.address = result.display_name;
    state.location.selected = true;

    // Update map
    locationMap.setView([state.location.lat, state.location.lng], 17);

    // Update or create marker
    if (locationMarker) {
      locationMarker.setLatLng([state.location.lat, state.location.lng]);
    } else {
      locationMarker = L.marker([state.location.lat, state.location.lng], {
        icon: L.divIcon({
          className: 'location-marker',
          html: '<div style="background:#3b82f6;width:24px;height:24px;border-radius:50%;border:3px solid white;box-shadow:0 2px 10px rgba(0,0,0,0.3);"></div>',
          iconSize: [24, 24],
          iconAnchor: [12, 12]
        })
      }).addTo(locationMap);
    }

    // Update UI
    updateLocationDisplay();

    // Enable next button
    document.getElementById('btnNextStep1').disabled = false;
    document.getElementById('locationDetails').style.display = 'grid';

    showToast('Lokalizacja znaleziona', 'success');

  } catch (error) {
    console.error('Search error:', error);
    showToast('Błąd wyszukiwania', 'error');
  }
}

async function reverseGeocode(lat, lng) {
  try {
    const response = await fetch(
      `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`,
      { headers: { 'Accept-Language': 'pl' } }
    );

    const result = await response.json();
    state.location.address = result.display_name || 'Nieznany adres';

    document.getElementById('detailAddress').textContent = state.location.address;
  } catch (error) {
    document.getElementById('detailAddress').textContent = 'Nieznany adres';
  }
}

function updateLocationDisplay() {
  const coordsText = `${state.location.lat.toFixed(6)}, ${state.location.lng.toFixed(6)}`;
  document.getElementById('coordsText').textContent = coordsText;
  document.getElementById('detailCoords').textContent = coordsText;
}

// ============================================================
// STEP 2: AREA DRAWING
// ============================================================

function setDrawingTool(tool) {
  // Update button states
  document.querySelectorAll('.tool-group:first-child .tool-btn').forEach(btn => {
    btn.classList.remove('active');
  });

  if (tool === 'polygon') {
    document.getElementById('toolPolygon').classList.add('active');
    if (currentDrawHandler) currentDrawHandler.disable();
    currentDrawHandler = new L.Draw.Polygon(drawingMap, drawControl.options.draw.polygon);
    currentDrawHandler.enable();
  } else if (tool === 'rectangle') {
    document.getElementById('toolRectangle').classList.add('active');
    if (currentDrawHandler) currentDrawHandler.disable();
    currentDrawHandler = new L.Draw.Rectangle(drawingMap, drawControl.options.draw.rectangle);
    currentDrawHandler.enable();
  }
}

function clearDrawing() {
  drawnItems.clearLayers();
  state.area.polygon = null;
  state.area.drawn = false;
  state.area.grossArea = 0;

  document.getElementById('areaStats').style.display = 'none';
  document.getElementById('drawingInstructions').classList.remove('hidden');
  document.getElementById('btnNextStep2').disabled = true;

  showToast('Obszar wyczyszczony', 'success');
}

function toggleMapLayer(layer) {
  if (!drawingMap) return;

  document.getElementById('layerStreet').classList.remove('active');
  document.getElementById('layerSatellite').classList.remove('active');

  if (layer === 'street') {
    drawingMap.removeLayer(satelliteLayer);
    streetLayer.addTo(drawingMap);
    document.getElementById('layerStreet').classList.add('active');
  } else {
    drawingMap.removeLayer(streetLayer);
    satelliteLayer.addTo(drawingMap);
    document.getElementById('layerSatellite').classList.add('active');
  }
}

function onPolygonCreated(e) {
  // Clear existing
  drawnItems.clearLayers();

  // Add new polygon
  state.area.polygon = e.layer;
  drawnItems.addLayer(state.area.polygon);

  // Calculate area
  const latlngs = e.layer.getLatLngs()[0];
  state.area.grossArea = L.GeometryUtil.geodesicArea(latlngs);
  state.area.perimeter = calculatePerimeter(latlngs);
  state.area.vertices = latlngs.length;
  state.area.drawn = true;

  // Update UI
  updateAreaStats();
  document.getElementById('drawingInstructions').classList.add('hidden');
  document.getElementById('btnNextStep2').disabled = false;

  showToast('Obszar zaznaczony', 'success');
}

function onPolygonEdited() {
  if (state.area.polygon) {
    const latlngs = state.area.polygon.getLatLngs()[0];
    state.area.grossArea = L.GeometryUtil.geodesicArea(latlngs);
    state.area.perimeter = calculatePerimeter(latlngs);
    state.area.vertices = latlngs.length;
    updateAreaStats();
  }
}

function onPolygonDeleted() {
  state.area.polygon = null;
  state.area.drawn = false;
  state.area.grossArea = 0;

  document.getElementById('areaStats').style.display = 'none';
  document.getElementById('drawingInstructions').classList.remove('hidden');
  document.getElementById('btnNextStep2').disabled = true;
}

function calculatePerimeter(latlngs) {
  let perimeter = 0;
  for (let i = 0; i < latlngs.length; i++) {
    const next = (i + 1) % latlngs.length;
    perimeter += latlngs[i].distanceTo(latlngs[next]);
  }
  return perimeter;
}

function updateAreaStats() {
  document.getElementById('areaStats').style.display = 'grid';
  document.getElementById('statArea').textContent = `${Math.round(state.area.grossArea).toLocaleString('pl-PL')} m²`;
  document.getElementById('statPerimeter').textContent = `${Math.round(state.area.perimeter).toLocaleString('pl-PL')} m`;
  document.getElementById('statVertices').textContent = state.area.vertices;
}

// ============================================================
// STEP 3: CONFIGURATION
// ============================================================

function updateInstallationTypeUI() {
  const type = state.config.installationType;
  const roofAngleRow = document.getElementById('roofAngleRow');
  const gcrRow = document.getElementById('gcrRow');

  // Show/hide relevant parameters
  switch (type) {
    case 'flat_roof':
      roofAngleRow.style.display = 'none';
      gcrRow.style.display = 'flex';
      document.getElementById('gcrRatio').value = '0.40';
      document.getElementById('tiltAngle').value = '15';
      break;

    case 'pitched_roof':
      roofAngleRow.style.display = 'flex';
      gcrRow.style.display = 'none';
      break;

    case 'ground':
      roofAngleRow.style.display = 'none';
      gcrRow.style.display = 'flex';
      document.getElementById('gcrRatio').value = '0.35';
      document.getElementById('tiltAngle').value = '35';
      break;

    case 'carport':
      roofAngleRow.style.display = 'none';
      gcrRow.style.display = 'none';
      document.getElementById('tiltAngle').value = '10';
      break;
  }
}

function updateModulePreview() {
  document.getElementById('previewPower').textContent = document.getElementById('modulePower').value;
  document.getElementById('previewWidth').textContent = document.getElementById('moduleWidth').value;
  document.getElementById('previewHeight').textContent = document.getElementById('moduleHeight').value;
}

async function fetchOptimalTilt() {
  const btn = document.querySelector('.btn-auto');
  btn.classList.add('loading');
  btn.disabled = true;

  try {
    const { lat, lng } = state.location;

    const url = `https://re.jrc.ec.europa.eu/api/v5_2/PVcalc?lat=${lat}&lon=${lng}&peakpower=1&loss=14&outputformat=json&optimalangles=1`;
    const response = await fetch(url);

    if (!response.ok) throw new Error('PVGIS API error');

    const data = await response.json();

    if (data.inputs?.mounting_system) {
      const optimalTilt = data.inputs.mounting_system.fixed.slope.value || 35;
      const optimalAzimuth = data.inputs.mounting_system.fixed.azimuth.value || 0;
      const azimuthConverted = (optimalAzimuth + 180) % 360;

      state.pvgis.optimalTilt = optimalTilt;
      state.pvgis.irradiance = data.outputs?.totals?.fixed?.H_y || null;
      state.pvgis.specificYield = data.outputs?.totals?.fixed?.E_y || null;
      state.pvgis.fetched = true;

      // Update inputs
      document.getElementById('tiltAngle').value = Math.round(optimalTilt);
      document.getElementById('azimuthAngle').value = Math.round(azimuthConverted);

      // Show PVGIS panel
      document.getElementById('pvgisOptTilt').textContent = `${Math.round(optimalTilt)}°`;
      document.getElementById('pvgisIrradiance').textContent = state.pvgis.irradiance ?
        `${Math.round(state.pvgis.irradiance)} kWh/m²` : '-';
      document.getElementById('pvgisYield').textContent = state.pvgis.specificYield ?
        `${Math.round(state.pvgis.specificYield)} kWh/kWp` : '-';
      document.getElementById('pvgisBlock').style.display = 'block';

      showToast('Dane PVGIS pobrane', 'success');
    }
  } catch (error) {
    console.error('PVGIS error:', error);
    showToast('Błąd pobierania danych PVGIS', 'error');
  } finally {
    btn.classList.remove('loading');
    btn.disabled = false;
  }
}

// ============================================================
// STEP 4: RESULTS
// ============================================================

async function calculateAndShowResults() {
  // Read current config values
  state.config.tilt = parseFloat(document.getElementById('tiltAngle').value);
  state.config.azimuth = parseFloat(document.getElementById('azimuthAngle').value);
  state.config.roofAngle = parseFloat(document.getElementById('roofAngle').value);
  state.config.gcr = parseFloat(document.getElementById('gcrRatio').value);
  state.config.modulePower = parseFloat(document.getElementById('modulePower').value);
  state.config.moduleWidth = parseFloat(document.getElementById('moduleWidth').value) / 1000; // mm to m
  state.config.moduleHeight = parseFloat(document.getElementById('moduleHeight').value) / 1000;

  // Calculate effective area based on installation type
  let effectiveArea;
  let effectiveTilt = state.config.tilt;

  switch (state.config.installationType) {
    case 'flat_roof':
      effectiveArea = state.area.grossArea * state.config.gcr;
      break;
    case 'pitched_roof':
      effectiveArea = state.area.grossArea * 0.85;
      effectiveTilt = state.config.roofAngle;
      break;
    case 'ground':
      effectiveArea = state.area.grossArea * state.config.gcr;
      break;
    case 'carport':
      effectiveArea = state.area.grossArea * 0.90;
      effectiveTilt = Math.min(state.config.tilt, 15);
      break;
    default:
      effectiveArea = state.area.grossArea * 0.80;
  }

  // Calculate module area and count
  const moduleArea = state.config.moduleWidth * state.config.moduleHeight;
  const moduleCount = Math.floor(effectiveArea / moduleArea);
  const activeArea = moduleCount * moduleArea;

  // Calculate capacity
  const capacityKwp = (moduleCount * state.config.modulePower) / 1000;

  // Store results
  state.results.capacityKwp = capacityKwp;
  state.results.moduleCount = moduleCount;
  state.results.activeArea = activeArea;

  // Fetch yearly production from PVGIS
  let yearlyProduction = null;
  if (capacityKwp > 0) {
    yearlyProduction = await fetchYearlyProduction(capacityKwp, effectiveTilt, state.config.azimuth);
  }

  state.results.yearlyYieldMwh = yearlyProduction ? yearlyProduction / 1000 : 0;
  state.results.specificYield = yearlyProduction && capacityKwp > 0 ?
    Math.round(yearlyProduction / capacityKwp) : 0;

  // Update results UI
  updateResultsDisplay();

  // Go to results step
  goToStep(4);
}

async function fetchYearlyProduction(capacityKwp, tilt, azimuth) {
  try {
    const { lat, lng } = state.location;
    const pvgisAzimuth = azimuth - 180;

    const url = `https://re.jrc.ec.europa.eu/api/v5_2/PVcalc?lat=${lat}&lon=${lng}&peakpower=${capacityKwp}&loss=14&angle=${tilt}&aspect=${pvgisAzimuth}&outputformat=json`;
    const response = await fetch(url);

    if (!response.ok) return null;

    const data = await response.json();
    return data.outputs?.totals?.fixed?.E_y || null;
  } catch (error) {
    console.error('PVGIS production error:', error);
    return null;
  }
}

function updateResultsDisplay() {
  const r = state.results;
  const typeNames = {
    'flat_roof': 'Dach płaski',
    'pitched_roof': 'Dach skośny',
    'ground': 'Instalacja naziemna',
    'carport': 'Carport / Wiata'
  };

  // Hero cards
  document.getElementById('resultCapacity').textContent = r.capacityKwp.toFixed(1);
  document.getElementById('resultYield').textContent = r.yearlyYieldMwh.toFixed(1);
  document.getElementById('resultSpecificYield').textContent = r.specificYield;

  // Installation details
  document.getElementById('resultModules').textContent = r.moduleCount.toLocaleString('pl-PL');
  document.getElementById('resultActiveArea').textContent = `${Math.round(r.activeArea).toLocaleString('pl-PL')} m²`;
  document.getElementById('resultTotalArea').textContent = `${Math.round(state.area.grossArea).toLocaleString('pl-PL')} m²`;
  document.getElementById('resultUtilization').textContent = `${Math.round((r.activeArea / state.area.grossArea) * 100)} %`;

  // Configuration details
  document.getElementById('resultInstType').textContent = typeNames[state.config.installationType];
  document.getElementById('resultTilt').textContent = `${state.config.tilt}°`;
  document.getElementById('resultAzimuth').textContent = `${state.config.azimuth}°`;
  document.getElementById('resultModulePower').textContent = `${state.config.modulePower} Wp`;

  // Location details
  document.getElementById('resultCoords').textContent = `${state.location.lat.toFixed(4)}, ${state.location.lng.toFixed(4)}`;
  document.getElementById('resultAddress').textContent = state.location.address || '-';
  document.getElementById('resultIrradiance').textContent = state.pvgis.irradiance ?
    `${Math.round(state.pvgis.irradiance)} kWh/m²/rok` : '-';

  // Quick estimation (rough estimates)
  const capex = r.capacityKwp * 3500;
  const savings = r.yearlyYieldMwh * 800;
  const payback = savings > 0 ? capex / savings : 0;

  document.getElementById('estCapex').textContent = `${(capex / 1000000).toFixed(2)} mln PLN`;
  document.getElementById('estSavings').textContent = `${Math.round(savings / 1000)} tys. PLN`;
  document.getElementById('estPayback').textContent = payback > 0 ? `${payback.toFixed(1)} lat` : '-';
}

// ============================================================
// ACTIONS
// ============================================================

function createProject() {
  const exportData = {
    source: 'site-assessment',
    timestamp: new Date().toISOString(),
    location: state.location,
    area: {
      grossArea: state.area.grossArea,
      coordinates: state.area.polygon ? state.area.polygon.getLatLngs()[0].map(ll => ({ lat: ll.lat, lng: ll.lng })) : []
    },
    config: state.config,
    results: state.results,
    pvgis: state.pvgis
  };

  // Try to send to parent (if embedded in shell)
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({
      type: 'SITE_ASSESSMENT_CREATE_PROJECT',
      data: exportData
    }, '*');
    showToast('Projekt utworzony w Energy Studio', 'success');
  } else {
    // Save to localStorage for standalone mode
    localStorage.setItem('siteAssessmentExport', JSON.stringify(exportData));
    showToast('Dane zapisane - otwórz Energy Studio aby zaimportować', 'success');
  }
}

function exportPDF() {
  showToast('Funkcja eksportu PDF w przygotowaniu', 'warning');
}

function copyResults() {
  const r = state.results;
  const typeNames = {
    'flat_roof': 'Dach płaski',
    'pitched_roof': 'Dach skośny',
    'ground': 'Instalacja naziemna',
    'carport': 'Carport / Wiata'
  };

  const text = `SITE ASSESSMENT - OCENA TERENU PV
=====================================
Lokalizacja: ${state.location.lat.toFixed(6)}, ${state.location.lng.toFixed(6)}
Adres: ${state.location.address || '-'}

PARAMETRY:
- Typ instalacji: ${typeNames[state.config.installationType]}
- Powierzchnia całkowita: ${Math.round(state.area.grossArea).toLocaleString('pl-PL')} m²
- Kąt nachylenia: ${state.config.tilt}°
- Azymut: ${state.config.azimuth}°

WYNIKI:
- Moc instalacji: ${r.capacityKwp.toFixed(1)} kWp
- Liczba modułów: ${r.moduleCount.toLocaleString('pl-PL')} szt.
- Produkcja roczna: ${r.yearlyYieldMwh.toFixed(1)} MWh/rok
- Specific yield: ${r.specificYield} kWh/kWp/rok

Wygenerowano: ${new Date().toLocaleString('pl-PL')}
Źródło: Pagra ENERGY Studio - Site Assessment`;

  navigator.clipboard.writeText(text).then(() => {
    showToast('Wyniki skopiowane do schowka', 'success');
  }).catch(() => {
    showToast('Nie udało się skopiować', 'error');
  });
}

function startNew() {
  // Reset state
  state.currentStep = 1;
  state.location.selected = false;
  state.area.drawn = false;
  state.area.polygon = null;
  state.pvgis.fetched = false;

  // Reset UI
  if (locationMarker) {
    locationMap.removeLayer(locationMarker);
    locationMarker = null;
  }
  if (drawnItems) {
    drawnItems.clearLayers();
  }

  document.getElementById('locationDetails').style.display = 'none';
  document.getElementById('btnNextStep1').disabled = true;
  document.getElementById('areaStats').style.display = 'none';
  document.getElementById('pvgisBlock').style.display = 'none';

  // Go to step 1
  goToStep(1);
  showToast('Rozpocznij nową analizę', 'success');
}

// ============================================================
// UI HELPERS
// ============================================================

function goToMainApp() {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: 'NAVIGATE_TO_CONFIG' }, '*');
  } else {
    window.location.href = '/';
  }
}

function openHelp() {
  document.getElementById('helpModal').style.display = 'flex';
}

function closeHelp() {
  document.getElementById('helpModal').style.display = 'none';
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const icons = {
    success: '✓',
    error: '✕',
    warning: '⚠',
    info: 'ℹ'
  };

  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || icons.info}</span>
    <span class="toast-message">${message}</span>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = 'slideIn 0.3s ease reverse';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ============================================================
// EXPORTS
// ============================================================

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    state,
    calculateAndShowResults
  };
}
