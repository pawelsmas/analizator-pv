/**
 * Site Assessment Module
 *
 * Features:
 * - Interactive map with polygon drawing (Leaflet + OpenStreetMap)
 * - Area calculation from polygon coordinates
 * - PVGIS API integration for optimal tilt and irradiation
 * - PV capacity calculation for different installation types
 *
 * Installation types:
 * - flat_roof: Flat roof with ballast (GCR factor for row spacing)
 * - pitched_roof: Pitched roof (tilt = roof angle)
 * - ground: Ground mount (optimal tilt from PVGIS)
 * - carport: Carport/parking shade structure
 */

// ============================================================
// GLOBAL STATE
// ============================================================

let map = null;
let drawnItems = null;
let drawControl = null;
let currentPolygon = null;
let currentLocation = { lat: 52.2297, lng: 21.0122 }; // Default: Warsaw
let pvgisData = null;

// ============================================================
// INITIALIZATION
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  initMap();
  setupEventListeners();
  updateInstallationTypeUI();
});

function initMap() {
  // Initialize map centered on Warsaw
  map = L.map('map', {
    center: [currentLocation.lat, currentLocation.lng],
    zoom: 17,
    zoomControl: true
  });

  // Add OpenStreetMap tiles (free, no API key needed)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19
  }).addTo(map);

  // Add satellite layer option
  const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: '&copy; Esri',
    maxZoom: 19
  });

  // Layer control
  const baseMaps = {
    'Mapa': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'),
    'Satelita': satellite
  };
  L.control.layers(baseMaps).addTo(map);

  // Initialize drawing layer
  drawnItems = new L.FeatureGroup();
  map.addLayer(drawnItems);

  // Initialize drawing control
  drawControl = new L.Control.Draw({
    position: 'topright',
    draw: {
      polygon: {
        allowIntersection: false,
        drawError: {
          color: '#f44336',
          message: '<strong>Błąd:</strong> Polygon nie może się przecinać!'
        },
        shapeOptions: {
          color: '#4fc3f7',
          weight: 3,
          fillColor: '#4fc3f7',
          fillOpacity: 0.3
        }
      },
      rectangle: {
        shapeOptions: {
          color: '#4fc3f7',
          weight: 3,
          fillColor: '#4fc3f7',
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
  map.addControl(drawControl);

  // Drawing event handlers
  map.on(L.Draw.Event.CREATED, onPolygonCreated);
  map.on(L.Draw.Event.EDITED, onPolygonEdited);
  map.on(L.Draw.Event.DELETED, onPolygonDeleted);

  // Click event to show coordinates
  map.on('click', (e) => {
    currentLocation = { lat: e.latlng.lat, lng: e.latlng.lng };
    updateCoordinatesDisplay();
  });

  // Try to get user's location
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        currentLocation = {
          lat: position.coords.latitude,
          lng: position.coords.longitude
        };
        map.setView([currentLocation.lat, currentLocation.lng], 17);
        updateCoordinatesDisplay();
      },
      () => {
        // Fallback to Warsaw
        updateCoordinatesDisplay();
      }
    );
  }
}

function setupEventListeners() {
  // Installation type change
  document.querySelectorAll('input[name="installationType"]').forEach(radio => {
    radio.addEventListener('change', updateInstallationTypeUI);
  });

  // Enter key on location search
  document.getElementById('locationSearch').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      searchLocation();
    }
  });
}

// ============================================================
// MAP EVENT HANDLERS
// ============================================================

function onPolygonCreated(e) {
  // Clear existing polygon
  drawnItems.clearLayers();

  // Add new polygon
  currentPolygon = e.layer;
  drawnItems.addLayer(currentPolygon);

  // Calculate and display area
  const area = calculatePolygonArea(currentPolygon);
  updateAreaDisplay(area);

  // Update center coordinates
  const center = currentPolygon.getBounds().getCenter();
  currentLocation = { lat: center.lat, lng: center.lng };
  updateCoordinatesDisplay();

  // Clear previous PVGIS data
  pvgisData = null;
  document.getElementById('pvgisData').style.display = 'none';
}

function onPolygonEdited(e) {
  if (currentPolygon) {
    const area = calculatePolygonArea(currentPolygon);
    updateAreaDisplay(area);

    const center = currentPolygon.getBounds().getCenter();
    currentLocation = { lat: center.lat, lng: center.lng };
    updateCoordinatesDisplay();
  }
}

function onPolygonDeleted() {
  currentPolygon = null;
  updateAreaDisplay(0);
  document.getElementById('resultsSection').style.display = 'none';
}

// ============================================================
// AREA CALCULATION
// ============================================================

/**
 * Calculate polygon area in square meters using the Shoelace formula
 * with Haversine distance for accurate geodetic area
 */
function calculatePolygonArea(polygon) {
  const latlngs = polygon.getLatLngs()[0];

  if (latlngs.length < 3) return 0;

  // Use Leaflet's built-in geodesic area calculation
  const area = L.GeometryUtil.geodesicArea(latlngs);

  return Math.abs(area);
}

/**
 * Alternative area calculation using Shoelace formula
 * Converts lat/lng to meters using local projection
 */
function calculateAreaShoelace(latlngs) {
  if (latlngs.length < 3) return 0;

  // Convert to local Cartesian coordinates (meters)
  const centerLat = latlngs.reduce((sum, p) => sum + p.lat, 0) / latlngs.length;
  const metersPerDegreeLat = 111320;
  const metersPerDegreeLng = 111320 * Math.cos(centerLat * Math.PI / 180);

  const points = latlngs.map(p => ({
    x: (p.lng - latlngs[0].lng) * metersPerDegreeLng,
    y: (p.lat - latlngs[0].lat) * metersPerDegreeLat
  }));

  // Shoelace formula
  let area = 0;
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    area += points[i].x * points[j].y;
    area -= points[j].x * points[i].y;
  }

  return Math.abs(area) / 2;
}

// ============================================================
// LOCATION SEARCH
// ============================================================

async function searchLocation() {
  const query = document.getElementById('locationSearch').value.trim();

  if (!query) {
    showError('Wprowadź adres lub nazwę miejsca');
    return;
  }

  try {
    // Use Nominatim (OpenStreetMap) geocoding - free, no API key
    const response = await fetch(
      `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=1`,
      {
        headers: {
          'Accept-Language': 'pl'
        }
      }
    );

    const results = await response.json();

    if (results.length === 0) {
      showError('Nie znaleziono lokalizacji');
      return;
    }

    const result = results[0];
    currentLocation = {
      lat: parseFloat(result.lat),
      lng: parseFloat(result.lon)
    };

    map.setView([currentLocation.lat, currentLocation.lng], 17);
    updateCoordinatesDisplay();

    // Clear PVGIS data for new location
    pvgisData = null;

  } catch (error) {
    console.error('Geocoding error:', error);
    showError('Błąd wyszukiwania lokalizacji');
  }
}

// ============================================================
// PVGIS API INTEGRATION
// ============================================================

/**
 * Fetch optimal tilt and irradiation data from PVGIS API
 * https://re.jrc.ec.europa.eu/pvg_tools/en/
 */
async function fetchOptimalTilt() {
  const btn = document.querySelector('.btn-small');
  btn.classList.add('loading');
  btn.disabled = true;

  try {
    const { lat, lng } = currentLocation;

    // PVGIS API - get optimal angle
    const url = `https://re.jrc.ec.europa.eu/api/v5_2/PVcalc?lat=${lat}&lon=${lng}&peakpower=1&loss=14&outputformat=json&optimalangles=1`;

    const response = await fetch(url);

    if (!response.ok) {
      throw new Error(`PVGIS API error: ${response.status}`);
    }

    const data = await response.json();

    if (data.inputs && data.inputs.mounting_system) {
      const optimalTilt = data.inputs.mounting_system.fixed.slope.optimal ?
        data.inputs.mounting_system.fixed.slope.value : 35;
      const optimalAzimuth = data.inputs.mounting_system.fixed.azimuth.optimal ?
        data.inputs.mounting_system.fixed.azimuth.value : 0;

      // PVGIS uses 0=South, we use 0=North, 180=South
      const azimuthConverted = (optimalAzimuth + 180) % 360;

      // Store PVGIS data
      pvgisData = {
        optimalTilt: optimalTilt,
        optimalAzimuth: azimuthConverted,
        yearlyIrradiation: data.outputs?.totals?.fixed?.H_y || null,
        specificYield: data.outputs?.totals?.fixed?.E_y || null
      };

      // Update UI
      document.getElementById('tiltAngle').value = Math.round(optimalTilt);
      document.getElementById('azimuthAngle').value = Math.round(azimuthConverted);

      // Show PVGIS data panel
      document.getElementById('pvgisOptTilt').textContent = `${Math.round(optimalTilt)}°`;
      document.getElementById('pvgisIrradiance').textContent = pvgisData.yearlyIrradiation ?
        `${Math.round(pvgisData.yearlyIrradiation)} kWh/m²/rok` : '-';
      document.getElementById('pvgisYield').textContent = pvgisData.specificYield ?
        `${Math.round(pvgisData.specificYield)} kWh/kWp/rok` : '-';
      document.getElementById('pvgisData').style.display = 'block';

      showSuccess('Dane PVGIS pobrane pomyślnie');

    } else {
      throw new Error('Invalid PVGIS response format');
    }

  } catch (error) {
    console.error('PVGIS error:', error);
    showError('Błąd pobierania danych PVGIS. Sprawdź czy lokalizacja jest w Europie.');
  } finally {
    btn.classList.remove('loading');
    btn.disabled = false;
  }
}

/**
 * Fetch yearly production estimate for given parameters
 */
async function fetchYearlyProduction(capacityKwp, tilt, azimuth) {
  try {
    const { lat, lng } = currentLocation;

    // Convert azimuth: our 0=N, 180=S -> PVGIS 0=S
    const pvgisAzimuth = (azimuth - 180 + 360) % 360;
    if (pvgisAzimuth > 180) {
      // PVGIS uses -180 to 180, with negative being East
      // We'll keep it 0-360 for simplicity
    }

    const url = `https://re.jrc.ec.europa.eu/api/v5_2/PVcalc?lat=${lat}&lon=${lng}&peakpower=${capacityKwp}&loss=14&angle=${tilt}&aspect=${pvgisAzimuth - 180}&outputformat=json`;

    const response = await fetch(url);

    if (!response.ok) {
      throw new Error(`PVGIS API error: ${response.status}`);
    }

    const data = await response.json();

    return data.outputs?.totals?.fixed?.E_y || null;

  } catch (error) {
    console.error('PVGIS production fetch error:', error);
    return null;
  }
}

// ============================================================
// CAPACITY CALCULATION
// ============================================================

async function calculateCapacity() {
  if (!currentPolygon) {
    showError('Narysuj najpierw polygon na mapie');
    return;
  }

  const btn = document.querySelector('.btn-calculate');
  btn.classList.add('loading');
  btn.disabled = true;

  try {
    // Get parameters
    const installationType = document.querySelector('input[name="installationType"]:checked').value;
    const tilt = parseFloat(document.getElementById('tiltAngle').value);
    const azimuth = parseFloat(document.getElementById('azimuthAngle').value);
    const roofAngle = parseFloat(document.getElementById('roofAngle').value);
    const gcr = parseFloat(document.getElementById('gcrRatio').value);
    const modulePower = parseFloat(document.getElementById('modulePower').value);
    const moduleWidth = parseFloat(document.getElementById('moduleWidth').value) / 1000; // mm to m
    const moduleHeight = parseFloat(document.getElementById('moduleHeight').value) / 1000; // mm to m

    // Calculate gross area
    const grossArea = calculatePolygonArea(currentPolygon);

    // Calculate module area
    const moduleArea = moduleWidth * moduleHeight;

    // Calculate effective area based on installation type
    let effectiveArea;
    let effectiveTilt = tilt;

    switch (installationType) {
      case 'flat_roof':
        // Flat roof: use GCR to account for row spacing
        effectiveArea = grossArea * gcr;
        break;

      case 'pitched_roof':
        // Pitched roof: tilt = roof angle, full coverage
        effectiveArea = grossArea * 0.85; // 85% utilization (edges, obstructions)
        effectiveTilt = roofAngle;
        break;

      case 'ground':
        // Ground mount: use GCR for optimal row spacing
        effectiveArea = grossArea * gcr;
        break;

      case 'carport':
        // Carport: typically lower tilt, high utilization
        effectiveArea = grossArea * 0.90;
        effectiveTilt = Math.min(tilt, 15); // Carports usually 5-15°
        break;

      default:
        effectiveArea = grossArea * 0.80;
    }

    // Calculate number of modules
    const moduleCount = Math.floor(effectiveArea / moduleArea);

    // Calculate total capacity
    const capacityKwp = (moduleCount * modulePower) / 1000;

    // Calculate active module area
    const activeArea = moduleCount * moduleArea;

    // Fetch yearly production from PVGIS
    let yearlyProduction = null;
    if (capacityKwp > 0) {
      yearlyProduction = await fetchYearlyProduction(capacityKwp, effectiveTilt, azimuth);
    }

    // Display results
    document.getElementById('resultCapacity').textContent = capacityKwp.toFixed(1);
    document.getElementById('resultModules').textContent = moduleCount.toLocaleString('pl-PL');
    document.getElementById('resultActiveArea').textContent = activeArea.toFixed(0);
    document.getElementById('resultYield').textContent = yearlyProduction ?
      (yearlyProduction / 1000).toFixed(1) : '-';

    document.getElementById('resultsSection').style.display = 'block';

    // Scroll to results
    document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });

  } catch (error) {
    console.error('Calculation error:', error);
    showError('Błąd obliczeń');
  } finally {
    btn.classList.remove('loading');
    btn.disabled = false;
  }
}

// ============================================================
// UI HELPERS
// ============================================================

function updateInstallationTypeUI() {
  const type = document.querySelector('input[name="installationType"]:checked').value;
  const roofAngleGroup = document.getElementById('roofAngle').closest('.param-group');
  const gcrGroup = document.getElementById('gcrRatio').closest('.param-group');
  const tiltGroup = document.getElementById('tiltAngle').closest('.param-group');

  // Show/hide relevant parameters
  switch (type) {
    case 'flat_roof':
      roofAngleGroup.style.display = 'none';
      gcrGroup.style.display = 'block';
      tiltGroup.style.display = 'block';
      document.getElementById('gcrRatio').value = '0.40';
      break;

    case 'pitched_roof':
      roofAngleGroup.style.display = 'block';
      gcrGroup.style.display = 'none';
      tiltGroup.style.display = 'none';
      break;

    case 'ground':
      roofAngleGroup.style.display = 'none';
      gcrGroup.style.display = 'block';
      tiltGroup.style.display = 'block';
      document.getElementById('gcrRatio').value = '0.35';
      break;

    case 'carport':
      roofAngleGroup.style.display = 'none';
      gcrGroup.style.display = 'none';
      tiltGroup.style.display = 'block';
      document.getElementById('tiltAngle').value = '10';
      break;
  }
}

function updateCoordinatesDisplay() {
  const display = document.getElementById('coordsDisplay');
  display.textContent = `Lat: ${currentLocation.lat.toFixed(6)}, Lng: ${currentLocation.lng.toFixed(6)}`;
}

function updateAreaDisplay(area) {
  const display = document.getElementById('areaDisplay');
  display.textContent = `Obszar: ${area.toFixed(0).toLocaleString('pl-PL')} m²`;
}

function showError(message) {
  const toast = document.createElement('div');
  toast.className = 'error-toast';
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.remove();
  }, 3000);
}

function showSuccess(message) {
  const toast = document.createElement('div');
  toast.className = 'success-toast';
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.remove();
  }, 3000);
}

// ============================================================
// EXPORT FUNCTIONS
// ============================================================

function exportToProject() {
  // Get calculated values
  const capacity = document.getElementById('resultCapacity').textContent;
  const modules = document.getElementById('resultModules').textContent;
  const activeArea = document.getElementById('resultActiveArea').textContent;
  const yearlyYield = document.getElementById('resultYield').textContent;
  const tilt = document.getElementById('tiltAngle').value;
  const azimuth = document.getElementById('azimuthAngle').value;
  const installationType = document.querySelector('input[name="installationType"]:checked').value;

  const exportData = {
    source: 'site-assessment',
    timestamp: new Date().toISOString(),
    location: currentLocation,
    installationType: installationType,
    parameters: {
      tilt: parseFloat(tilt),
      azimuth: parseFloat(azimuth),
      modulePower: parseFloat(document.getElementById('modulePower').value)
    },
    results: {
      capacityKwp: parseFloat(capacity),
      moduleCount: parseInt(modules.replace(/\s/g, '')),
      activeAreaM2: parseFloat(activeArea),
      yearlyYieldMwh: yearlyYield !== '-' ? parseFloat(yearlyYield) : null
    },
    pvgisData: pvgisData
  };

  // Post to parent window (shell)
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({
      type: 'SITE_ASSESSMENT_EXPORT',
      data: exportData
    }, '*');

    showSuccess('Dane wysłane do projektu');
  } else {
    // Fallback: copy to clipboard
    copyResults();
  }
}

function copyResults() {
  const capacity = document.getElementById('resultCapacity').textContent;
  const modules = document.getElementById('resultModules').textContent;
  const activeArea = document.getElementById('resultActiveArea').textContent;
  const yearlyYield = document.getElementById('resultYield').textContent;
  const installationType = document.querySelector('input[name="installationType"]:checked').value;

  const typeNames = {
    'flat_roof': 'Dach płaski',
    'pitched_roof': 'Dach skośny',
    'ground': 'Instalacja naziemna',
    'carport': 'Carport'
  };

  const text = `Site Assessment - Ocena Terenu PV
=====================================
Lokalizacja: ${currentLocation.lat.toFixed(6)}, ${currentLocation.lng.toFixed(6)}
Typ instalacji: ${typeNames[installationType]}

WYNIKI:
- Moc instalacji: ${capacity} kWp
- Liczba modułów: ${modules} szt.
- Powierzchnia aktywna: ${activeArea} m²
- Prognoza roczna: ${yearlyYield} MWh/rok

Wygenerowano: ${new Date().toLocaleString('pl-PL')}`;

  navigator.clipboard.writeText(text).then(() => {
    showSuccess('Wyniki skopiowane do schowka');
  }).catch(() => {
    showError('Nie udało się skopiować');
  });
}

// ============================================================
// EXPORTS FOR TESTING
// ============================================================

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    calculatePolygonArea,
    calculateAreaShoelace
  };
}
