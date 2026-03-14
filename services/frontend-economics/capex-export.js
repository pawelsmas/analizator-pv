// ============================================================================
// === CAPEX EXCEL EXPORT ===
// ============================================================================
// Version: v14 - Non-linear sensitivity + error handling
// ============================================================================
console.log('📦 capex-export.js LOADED v14 - timestamp:', new Date().toISOString());

// ============================================================================
// === INLINE WATERMARK (self-contained, no cross-file dependency) ===
// ============================================================================
function _capexWatermarkHash(input) {
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  for (let i = 0; i < input.length; i++) {
    const ch = input.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36).padStart(12, '0');
}

function _capexEncodeZW(payload) {
  let e = '\uFEFF';
  for (let i = 0; i < payload.length; i++) {
    if (i > 0) e += '\u200D';
    const bits = payload.charCodeAt(i).toString(2).padStart(8, '0');
    for (const b of bits) e += b === '0' ? '\u200B' : '\u200C';
  }
  return e + '\uFEFF';
}

function _capexApplyWatermark(workbook, options = {}) {
  const proj = (window.parent && window.parent.sharedData && window.parent.sharedData.currentProject) || {};
  const now = new Date();
  const pid = proj.id || proj.uuid || 'unknown';
  const cid = proj.companyId || 'none';
  const variant = (typeof currentVariant !== 'undefined' ? currentVariant : '?');
  const payload = `${pid}|${cid}|${now.toISOString()}|${variant}`;
  const hash = _capexWatermarkHash(payload);
  const shortId = `PV-${pid}-${hash}`;

  console.log(`🔒 CAPEX Watermark: fingerprint=${hash}, project=${pid}`);

  // LAYER 1: Document properties
  workbook.creator = 'Analizator PV';
  workbook.lastModifiedBy = 'Analizator PV';
  workbook.created = now;
  workbook.modified = now;
  workbook.subject = shortId;
  workbook.keywords = `pv,analizator,${hash}`;

  // LAYER 2: veryHidden sheet
  const ws = workbook.addWorksheet('_sys_config', { state: 'veryHidden' });
  ws.state = 'veryHidden';
  ws.getCell('A1').value = 'WATERMARK_V1';
  ws.getCell('A2').value = hash;
  ws.getCell('A3').value = String(pid);
  ws.getCell('A4').value = String(cid);
  ws.getCell('A5').value = proj.name || 'draft';
  ws.getCell('A6').value = now.toISOString();
  ws.getCell('A7').value = variant;
  ws.getCell('A8').value = payload;
  ws.getCell('A9').value = _capexWatermarkHash(hash + payload);
  console.log(`🔒 CAPEX Watermark: veryHidden sheet created, worksheets count=${workbook.worksheets.length}`);

  // LAYER 3: Zero-width chars in title cells
  const zwPayload = _capexEncodeZW(hash);
  (options.visibleSheets || []).forEach(name => {
    const s = workbook.getWorksheet(name);
    if (!s) return;
    for (let c = 1; c <= 10; c++) {
      const cell = s.getRow(1).getCell(c);
      if (cell.value && typeof cell.value === 'string' && cell.value.length > 5) {
        cell.value = cell.value + zwPayload;
        break;
      }
    }
  });

  console.log(`🔒 CAPEX Watermark: ALL 3 layers applied`);
  return { hash, shortId };
}

// ============================================================================
// === NATIVE EXCEL CHART INJECTION ===
// ============================================================================

/**
 * Inject native Excel charts into an ExcelJS-generated workbook buffer
 * Charts are DYNAMIC - they update automatically when data changes in Excel
 */
async function injectNativeExcelCharts(buffer, chartConfigs, defaultSheetIndex = 1) {
  console.log('📊 Injecting native Excel charts...');

  if (typeof JSZip === 'undefined') {
    console.error('JSZip not available');
    return new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  }

  try {
    const zip = await JSZip.loadAsync(buffer);

    // Create folders
    zip.folder('xl/charts');
    zip.folder('xl/drawings');
    zip.folder('xl/drawings/_rels');
    zip.folder('xl/worksheets/_rels');

    // Group charts by sheet index
    const chartsBySheet = {};
    chartConfigs.forEach((config, idx) => {
      const sheetIdx = config.sheetIndex !== undefined ? config.sheetIndex : defaultSheetIndex;
      if (!chartsBySheet[sheetIdx]) {
        chartsBySheet[sheetIdx] = [];
      }
      chartsBySheet[sheetIdx].push({ config, globalIdx: idx });
    });

    let contentTypesXml = await zip.file('[Content_Types].xml').async('string');

    // Process each sheet separately
    for (const [sheetIdxStr, chartsInSheet] of Object.entries(chartsBySheet)) {
      const sheetIdx = parseInt(sheetIdxStr);
      const chartFiles = [];
      const chartPositions = [];

      // Generate chart XML files for this sheet
      chartsInSheet.forEach((item, localIdx) => {
        const { config, globalIdx } = item;
        const chartFileName = `chart${globalIdx + 1}.xml`;
        const axId1 = 100000000 + globalIdx * 2;
        const axId2 = 100000001 + globalIdx * 2;

        let chartXml;
        if (config.type === 'bar') {
          chartXml = generateBarChartXml(config, axId1, axId2);
        } else {
          chartXml = generateLineChartXml(config, axId1, axId2);
        }

        zip.file(`xl/charts/${chartFileName}`, chartXml);
        chartFiles.push(chartFileName);
        chartPositions.push({
          fromCol: config.position.fromCol,
          fromRow: config.position.fromRow,
          toCol: config.position.toCol,
          toRow: config.position.toRow,
          chartRid: `rId${localIdx + 1}`
        });
        console.log(`  📈 Created chart: ${config.title} (sheet ${sheetIdx})`);

        // Add to content types
        if (!contentTypesXml.includes(`/xl/charts/${chartFileName}`)) {
          contentTypesXml = contentTypesXml.replace('</Types>',
            `<Override PartName="/xl/charts/${chartFileName}" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/></Types>`);
        }
      });

      // Create drawing XML for this sheet
      const drawingFileName = `drawing${sheetIdx + 1}.xml`;
      let anchors = '';
      chartPositions.forEach((pos, idx) => {
        anchors += `
  <xdr:twoCellAnchor>
    <xdr:from><xdr:col>${pos.fromCol}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>${pos.fromRow}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
    <xdr:to><xdr:col>${pos.toCol}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>${pos.toRow}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
    <xdr:graphicFrame macro="">
      <xdr:nvGraphicFramePr>
        <xdr:cNvPr id="${idx + 2}" name="Chart ${idx + 1}"/>
        <xdr:cNvGraphicFramePr><a:graphicFrameLocks/></xdr:cNvGraphicFramePr>
      </xdr:nvGraphicFramePr>
      <xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>
      <a:graphic>
        <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">
          <c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" r:id="${pos.chartRid}"/>
        </a:graphicData>
      </a:graphic>
    </xdr:graphicFrame>
    <xdr:clientData/>
  </xdr:twoCellAnchor>`;
      });

      const drawingXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
          xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">${anchors}
</xdr:wsDr>`;
      zip.file(`xl/drawings/${drawingFileName}`, drawingXml);

      // Create drawing relationships for this sheet
      let drawingRels = '';
      chartFiles.forEach((f, i) => {
        drawingRels += `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/${f}"/>`;
      });
      zip.file(`xl/drawings/_rels/${drawingFileName}.rels`,
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${drawingRels}</Relationships>`);

      // Update worksheet
      const sheetFileName = `xl/worksheets/sheet${sheetIdx + 1}.xml`;
      let sheetXml = await zip.file(sheetFileName).async('string');
      if (!sheetXml.includes('<drawing')) {
        sheetXml = sheetXml.replace('</worksheet>', `<drawing r:id="rIdDrawing"/></worksheet>`);
        if (!sheetXml.includes('xmlns:r=')) {
          sheetXml = sheetXml.replace('<worksheet', '<worksheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"');
        }
      }
      zip.file(sheetFileName, sheetXml);

      // Update worksheet relationships
      const sheetRelsPath = `xl/worksheets/_rels/sheet${sheetIdx + 1}.xml.rels`;
      let sheetRelsXml = zip.file(sheetRelsPath)
        ? await zip.file(sheetRelsPath).async('string')
        : `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>`;
      if (!sheetRelsXml.includes('relationships/drawing')) {
        sheetRelsXml = sheetRelsXml.replace('</Relationships>',
          `<Relationship Id="rIdDrawing" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/${drawingFileName}"/></Relationships>`);
      }
      zip.file(sheetRelsPath, sheetRelsXml);

      // Add drawing to content types
      if (!contentTypesXml.includes(`/xl/drawings/${drawingFileName}`)) {
        contentTypesXml = contentTypesXml.replace('</Types>',
          `<Override PartName="/xl/drawings/${drawingFileName}" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/></Types>`);
      }
    }

    zip.file('[Content_Types].xml', contentTypesXml);

    console.log('✅ Native Excel charts injected');
    return await zip.generateAsync({ type: 'blob' });
  } catch (error) {
    console.error('❌ Chart injection error:', error);
    return new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  }
}

function escapeXml(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function generateLineChartXml(config, axId1, axId2) {
  // Clean look - no gridlines
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <c:lang val="pl-PL"/>
  <c:chart>
    <c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="pl-PL" sz="1200" b="1"/><a:t>${escapeXml(config.title)}</a:t></a:r></a:p></c:rich></c:tx></c:title>
    <c:autoTitleDeleted val="0"/>
    <c:plotArea>
      <c:layout/>
      <c:lineChart>
        <c:grouping val="standard"/>
        <c:ser>
          <c:idx val="0"/><c:order val="0"/>
          <c:spPr><a:ln w="25400"><a:solidFill><a:srgbClr val="4CAF50"/></a:solidFill></a:ln></c:spPr>
          <c:marker><c:symbol val="circle"/><c:size val="4"/><c:spPr><a:solidFill><a:srgbClr val="4CAF50"/></a:solidFill></c:spPr></c:marker>
          <c:cat><c:numRef><c:f>'${config.sheetName}'!${config.categoryRange}</c:f></c:numRef></c:cat>
          <c:val><c:numRef><c:f>'${config.sheetName}'!${config.valueRange}</c:f></c:numRef></c:val>
        </c:ser>
        <c:axId val="${axId1}"/><c:axId val="${axId2}"/>
      </c:lineChart>
      <c:catAx><c:axId val="${axId1}"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="b"/><c:tickLblPos val="nextTo"/><c:crossAx val="${axId2}"/></c:catAx>
      <c:valAx><c:axId val="${axId2}"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="l"/><c:tickLblPos val="nextTo"/><c:crossAx val="${axId1}"/></c:valAx>
    </c:plotArea>
  </c:chart>
</c:chartSpace>`;
}

function generateBarChartXml(config, axId1, axId2) {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <c:lang val="pl-PL"/>
  <c:chart>
    <c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="pl-PL" sz="1200" b="1"/><a:t>${escapeXml(config.title)}</a:t></a:r></a:p></c:rich></c:tx></c:title>
    <c:autoTitleDeleted val="0"/>
    <c:plotArea>
      <c:layout/>
      <c:barChart>
        <c:barDir val="col"/><c:grouping val="clustered"/>
        <c:ser>
          <c:idx val="0"/><c:order val="0"/>
          <c:spPr><a:solidFill><a:srgbClr val="2196F3"/></a:solidFill></c:spPr>
          <c:cat><c:numRef><c:f>'${config.sheetName}'!${config.categoryRange}</c:f></c:numRef></c:cat>
          <c:val><c:numRef><c:f>'${config.sheetName}'!${config.valueRange}</c:f></c:numRef></c:val>
        </c:ser>
        <c:axId val="${axId1}"/><c:axId val="${axId2}"/>
      </c:barChart>
      <c:catAx><c:axId val="${axId1}"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="b"/><c:tickLblPos val="nextTo"/><c:crossAx val="${axId2}"/></c:catAx>
      <c:valAx><c:axId val="${axId2}"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="l"/><c:tickLblPos val="nextTo"/><c:crossAx val="${axId1}"/></c:valAx>
    </c:plotArea>
  </c:chart>
</c:chartSpace>`;
}

// ============================================================================

/**
 * Compute annual self-consumption [kWh] for a given yield factor using hourly profiles.
 * Returns null if hourly data is not available (caller should use linear fallback).
 *
 * yieldFactor: 1.0 = base, 1.15 = +15% yield, 0.85 = -15% yield
 * Applies scenario factor (P50/P75/P90) on top of yieldFactor.
 */
function _computeSelfConsumptionForYield(yieldFactor) {
  const hourlyLoad = hourlyData?.values || hourlyData || [];
  const variantKey = typeof currentVariant !== 'undefined' ? currentVariant : 'B';
  const variantData = analysisResults?.key_variants?.[variantKey];
  const hourlyPV = variantData?.hourly_production || [];
  const scenarioFactor = window.currentScenarioFactor || 1.0;

  if (!Array.isArray(hourlyLoad) || !Array.isArray(hourlyPV) ||
      hourlyLoad.length < 720 || hourlyPV.length < 720) {
    return null;
  }

  const n = Math.min(hourlyLoad.length, hourlyPV.length);
  let selfConsumed = 0;
  for (let h = 0; h < n; h++) {
    const pv = (hourlyPV[h] || 0) * scenarioFactor * yieldFactor;
    const load = hourlyLoad[h] || 0;
    selfConsumed += Math.min(pv, load);
  }

  // Annualize if data is less than a full year
  if (n < 8760 && n >= 720) {
    selfConsumed = selfConsumed * (8760 / n);
  }

  return selfConsumed; // kWh
}

/**
 * Export CAPEX year-by-year analysis to Excel
 * Similar structure to EaaS export but for investor (CAPEX) perspective
 */
async function exportCapexToExcel(withFormulas = false) {
  console.log('📥 exportCapexToExcel() CALLED', { withFormulas, currentVariant, hasCentralizedMetrics: !!centralizedMetrics?.[currentVariant] });
  try {
  const scenarioName = window.currentProductionScenario || 'P50';
  const scenarioFactor = window.currentScenarioFactor || 1.0;
  console.log(`📥 Exporting CAPEX analysis to Excel (${scenarioName}, factor=${scenarioFactor})...`, withFormulas ? '(WITH FORMULAS)' : '(values only)');

  // Get centralized CAPEX metrics
  const centralizedCalc = centralizedMetrics[currentVariant];
  if (!centralizedCalc || !centralizedCalc.capex) {
    alert('Brak danych CAPEX do eksportu. Najpierw wykonaj analizę.');
    return;
  }

  const variant = variants[currentVariant];
  if (!variant) {
    alert('Brak wariantu do eksportu.');
    return;
  }

  // Get economic parameters
  const params = getEconomicParameters();
  const cashFlows = centralizedCalc.capex.cashFlows;
  const investment = centralizedCalc.capex.investment;
  const discountRate = centralizedCalc.common.discountRate;
  const inflationRate = centralizedCalc.common.inflationRate;
  const totalEnergyPrice = centralizedCalc.common.totalEnergyPrice;
  const analysisPeriod = params.analysis_period || cashFlows.length;
  const useInflation = centralizedCalc.common.useInflation ?? false;

  // Capacity and production data
  const capacityKwp = variant.capacity;
  const annualConsumptionKwh = getAnnualConsumptionKwh();
  const annualConsumptionMwh = annualConsumptionKwh / 1000;

  // In RDN mode, compute effective price per MWh from actual TCSL annual cost
  // Must be AFTER annualConsumptionMwh declaration
  const isRdn = !!window._rdnExportMode;
  const rdnBL = isRdn ? (centralizedCalc.capex?.rdnBaseline || null) : null;
  const rdnGridCostYear1Tys = rdnBL ? rdnBL.nopvRdnTcslAnnual / 1000 : 0;
  const rdnEffectivePrice = (rdnBL && annualConsumptionMwh > 0)
    ? rdnBL.nopvRdnTcslAnnual / annualConsumptionMwh
    : totalEnergyPrice;
  const effectiveEnergyPrice = isRdn ? rdnEffectivePrice : totalEnergyPrice;
  const baseAutoconsumptionMwh = centralizedCalc.common.selfConsumedMwh || (variant.self_consumed || 0) / 1000;

  // Degradation rates — LID already in profile when precise data available
  const hasPreciseBaseCapex = !!(window.preciseAnnualSavings?.energy?.self_consumed_mwh);
  const pvDegradationYear1 = hasPreciseBaseCapex
    ? 0 : (systemSettings?.pvDegradationYear1 !== undefined ? systemSettings.pvDegradationYear1 : 1.0) / 100;
  const pvDegradationYears2Plus = params.degradation_rate;
  const bessDegradationRate = (systemSettings?.bessDegradationRate !== undefined ? systemSettings.bessDegradationRate : 2.5) / 100;

  console.log('📥 CAPEX Export - Investment:', investment, 'PLN, Years:', analysisPeriod);
  console.log('📥 CAPEX Export - baseAutoconsumptionMwh:', baseAutoconsumptionMwh);

  // Create workbook using ExcelJS
  const workbook = new ExcelJS.Workbook();

  // Load and add logo image
  let logoImageId = null;
  try {
    const logoResponse = await fetch('logo.png');
    if (logoResponse.ok) {
      const logoBlob = await logoResponse.blob();
      const logoBase64 = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result.split(',')[1]);
        reader.readAsDataURL(logoBlob);
      });
      logoImageId = workbook.addImage({
        base64: logoBase64,
        extension: 'png'
      });
      console.log('📷 Logo loaded successfully');
    }
  } catch (e) {
    console.warn('⚠️ Could not load logo:', e);
  }

  // ========== SHEET 1: Podsumowanie CAPEX ==========
  const sheet1 = workbook.addWorksheet('Podsumowanie CAPEX');
  sheet1.columns = [
    { width: 5 },
    { width: 35 },
    { width: 18 }
  ];
  sheet1.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Set row heights for header area
  sheet1.getRow(1).height = 20;
  sheet1.getRow(2).height = 20;
  sheet1.getRow(3).height = 24;

  // Title
  sheet1.mergeCells('B1:C3');
  const rdnLabel = window._rdnExportMode ? ' (ceny RDN)' : '';
  sheet1.getCell('B1').value = `ANALIZA CAPEX${rdnLabel} - Perspektywa Inwestora - Scenariusz ${scenarioName}`;
  sheet1.getCell('B1').font = { bold: true, size: 14, color: { argb: 'FF1565C0' } };
  sheet1.getCell('B1').alignment = { horizontal: 'center', vertical: 'bottom' };

  // Add logo to Sheet 1 (above title, like EaaS)
  if (logoImageId !== null) {
    sheet1.addImage(logoImageId, {
      tl: { col: 1.3, row: 0.1 },
      ext: { width: 200, height: 50 }
    });
  }

  // Calculate additional metrics
  const totalUndiscountedSavings = cashFlows.reduce((sum, cf) => sum + (cf.net_cash_flow || 0), 0);
  const roi = ((totalUndiscountedSavings - investment) / investment) * 100;

  // Summary data - reference to Sheet 2 for formulas
  const dataStartRow = 18; // First data row in Sheet 2 (Year 1) - row 17 is Year 0
  const lastDataRow = 17 + analysisPeriod; // Header row 16, Year 0 row 17, data from row 18

  const summaryRows = [
    ['', ''],
    ['DANE INSTALACJI', ''],
    ['Moc instalacji [kWp]:', capacityKwp],
    ['Zużycie roczne zakładu [MWh]:', roundNum(annualConsumptionMwh, 1)],
    ['Autokonsumpcja PV [MWh/rok]:', roundNum(baseAutoconsumptionMwh, 1)],
    ['Pokrycie zużycia [%]:', roundNum((baseAutoconsumptionMwh / annualConsumptionMwh) * 100, 1)],
    ['', ''],
    ['PARAMETRY INWESTYCJI', ''],
    ['CAPEX [tys. PLN]:', roundNum(investment / 1000, 0)],
    ['CAPEX [PLN/kWp]:', roundNum(investment / capacityKwp, 0)],
    ['Okres analizy [lat]:', analysisPeriod],
    ['Stopa dyskontowa [%]:', roundNum(discountRate * 100, 1)],
    ['Inflacja [%]:', roundNum(inflationRate * 100, 1)],
    ['', ''],
    ['DEGRADACJA', ''],
    ['Degradacja PV rok 1 [%]:', roundNum(pvDegradationYear1 * 100, 1)],
    ['Degradacja PV lata 2+ [%/rok]:', roundNum(pvDegradationYears2Plus * 100, 2)],
    ['Degradacja BESS [%/rok]:', roundNum(bessDegradationRate * 100, 1)],
    ['', ''],
    ['WYNIKI EKONOMICZNE', ''],
  ];

  // Add KPI rows with formulas or values [label, value, numFmt]
  // Note: Sheet2 has margin column A, so: B=Rok, L=Oszcz., M=NPV Skum., F=Parameters
  if (withFormulas) {
    summaryRows.push(['NPV [mln PLN]:', { formula: "'CAPEX Rok po Roku'!M" + lastDataRow }, '0.00']);
    summaryRows.push(['IRR [%]:', roundNum(centralizedCalc.capex.irr * 100, 1), '0.0']);
    summaryRows.push(['ROI [%]:', { formula: "(SUM('CAPEX Rok po Roku'!L" + dataStartRow + ":L" + lastDataRow + ")*1000-'CAPEX Rok po Roku'!F10*1000)/('CAPEX Rok po Roku'!F10*1000)*100" }, '0.0']);
    summaryRows.push(['Prosty zwrot [lat]:', { formula: "'CAPEX Rok po Roku'!F10*1000/AVERAGE('CAPEX Rok po Roku'!L" + dataStartRow + ":L" + (dataStartRow + 4) + ")/1000" }, '0.0']);
  } else {
    summaryRows.push(['NPV [mln PLN]:', roundNum(centralizedCalc.capex.npv / 1000000, 2), '0.00']);
    summaryRows.push(['IRR [%]:', roundNum(centralizedCalc.capex.irr * 100, 1), '0.0']);
    summaryRows.push(['ROI [%]:', roundNum(roi, 1), '0.0']);
    summaryRows.push(['Prosty zwrot [lat]:', roundNum(centralizedCalc.capex.simplePayback, 1), '0.0']);
  }
  const dpp = centralizedCalc.capex.discountedPayback;
  summaryRows.push(['Zdyskontowany zwrot [lat]:', (dpp !== null && dpp !== undefined) ? roundNum(dpp, 1) : 'Powyzej okresu analizy', '0.0']);
  summaryRows.push(['LCOE [PLN/MWh]:', roundNum(centralizedCalc.capex.lcoe, 0), '0']);

  summaryRows.forEach((row, idx) => {
    const excelRow = sheet1.getRow(idx + 5);
    excelRow.getCell(2).value = row[0];
    if (typeof row[1] === 'object' && row[1].formula) {
      excelRow.getCell(3).value = row[1];
    } else {
      excelRow.getCell(3).value = row[1];
    }
    // Apply number format if specified
    if (row[2] && typeof row[1] !== 'string') {
      excelRow.getCell(3).numFmt = row[2];
    }
    // Style section headers
    if (row[0] && (row[0].includes('INSTALACJI') || row[0].includes('INWESTYCJI') || row[0] === 'DEGRADACJA' || row[0].includes('EKONOMICZNE'))) {
      excelRow.getCell(2).font = { bold: true, color: { argb: 'FF1565C0' } };
      excelRow.getCell(2).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
      excelRow.getCell(3).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
    }
  });

  // ========== SHEET 2: CAPEX Rok po Roku ==========
  const sheet2 = workbook.addWorksheet('CAPEX Rok po Roku');
  sheet2.columns = [
    { width: 3 },   // A: margin column (empty) - for clean look
    { width: 6 },   // B: Rok
    { width: 10 },  // C: Deg PV
    { width: 10 },  // D: Deg BESS
    { width: 12 },  // E: Zużycie
    { width: 16 },  // F: Koszt OSD
    { width: 12 },  // G: Auto PV
    { width: 12 },  // H: Auto BESS
    { width: 12 },  // I: Suma Auto
    { width: 16 },  // J: Równow. OSD
    { width: 14 },  // K: OPEX
    { width: 16 },  // L: Oszczędn.
    { width: 16 }   // M: NPV Skum.
  ];

  // Hide gridlines and headers for clean look
  sheet2.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Title row with height
  sheet2.getRow(1).height = 22;
  sheet2.getCell('B1').value = `ANALIZA CAPEX${rdnLabel} ROK PO ROKU Z NPV - Scenariusz ${scenarioName}`;
  sheet2.getCell('B1').font = { bold: true, size: 14, color: { argb: 'FF1565C0' } };

  // Add logo to Sheet 2 (after charts - col R)
  if (logoImageId !== null) {
    sheet2.addImage(logoImageId, {
      tl: { col: 17, row: 0.3 },  // Column R, after charts end at col P (16)
      ext: { width: 180, height: 45 }
    });
    console.log('📷 Logo added to Sheet 2 at col 17');
  }

  // Parameters section (rows 3-14) - merge B:D, align labels right, values right with spacing
  // Number format with space as thousands separator: # ##0.00 (Polish locale)
  // Get base OPEX (before inflation) in tys. PLN
  const baseOpexTysPln = cashFlows.length > 0 ? cashFlows[0].opex / 1000 : 0;

  const paramData = [
    { row: 3, label: 'PARAMETRY:', value: null, numFmt: null, isHeader: true },
    { row: 4, label: 'Stopa dyskontowa:', value: discountRate, numFmt: '0.00%' },
    { row: 5, label: 'Inflacja:', value: inflationRate, numFmt: '0.00%' },
    { row: 6, label: 'Degradacja PV Rok 1:', value: pvDegradationYear1, numFmt: '0.00%' },
    { row: 7, label: 'Degradacja PV Lata 2+:', value: pvDegradationYears2Plus, numFmt: '0.00%' },
    { row: 8, label: 'Degradacja BESS:', value: bessDegradationRate, numFmt: '0.00%' },
    { row: 9, label: 'Okres analizy [lat]:', value: analysisPeriod, numFmt: '0' },
    { row: 10, label: 'CAPEX [tys. PLN]:', value: roundNum(investment / 1000, 2), numFmt: '# ##0.00' },
    { row: 11, label: 'Autokonsumpcja bazowa [MWh]:', value: roundNum(baseAutoconsumptionMwh, 2), numFmt: '# ##0.00' },
    isRdn
      ? { row: 12, label: 'Koszt RDN bez PV rok 1 [tys. PLN]:', value: roundNum(rdnGridCostYear1Tys, 2), numFmt: '# ##0.00', rdnFormula: true }
      : { row: 12, label: 'Cena sieci bazowa [PLN/MWh]:', value: roundNum(totalEnergyPrice, 2), numFmt: '# ##0.00' },
    { row: 13, label: 'Zużycie roczne [MWh]:', value: roundNum(annualConsumptionMwh, 2), numFmt: '# ##0.00' },
    { row: 14, label: 'OPEX bazowy [tys. PLN/rok]:', value: roundNum(baseOpexTysPln, 2), numFmt: '# ##0.00' }
  ];

  paramData.forEach(p => {
    // Merge cells C:E for label (shifted +1 for margin column A)
    sheet2.mergeCells(`C${p.row}:E${p.row}`);
    const labelCell = sheet2.getCell(`C${p.row}`);
    labelCell.value = p.label + ' '; // 1 space suffix (right-aligned label)
    labelCell.alignment = { horizontal: 'right' };
    if (p.isHeader) {
      labelCell.font = { bold: true, color: { argb: 'FF5D4037' } };
    } else {
      labelCell.font = { color: { argb: 'FF616161' } };
    }
    // Subtle border
    labelCell.border = { bottom: { style: 'thin', color: { argb: 'FFEEEEEE' } } };

    // Value in column F - left aligned with bold blue color (shifted +1)
    if (p.value !== null) {
      const valueCell = sheet2.getCell(`F${p.row}`);
      // RDN formula: F12 references audit sheet D31 (nopv TCSL RAZEM) / 1000
      if (p.rdnFormula && withFormulas) {
        valueCell.value = { formula: "'Dane bazowe TCSL (Rok 1)'!D31/1000", result: p.value };
      } else {
        valueCell.value = p.value;
      }
      valueCell.alignment = { horizontal: 'left', indent: 1 };
      valueCell.font = { bold: true, color: { argb: 'FF1976D2' } };
      valueCell.border = { bottom: { style: 'thin', color: { argb: 'FFEEEEEE' } } };
      if (p.numFmt) {
        valueCell.numFmt = p.numFmt;
      }
    }
  });

  // Header row (row 16) - shifted +1 for margin column
  const headers = ['Rok', 'Deg PV [%]', 'Deg BESS [%]', 'Zużycie [MWh]', isRdn ? 'Koszt RDN [tys.]' : 'Koszt OSD [tys.]',
    'Auto PV [MWh]', 'Auto BESS [MWh]', 'Suma Auto [MWh]', isRdn ? 'Oszcz. RDN [tys.]' : 'Równow. OSD [tys.]',
    'OPEX [tys.]', 'Oszczędn. [tys.]', 'NPV Skum. [mln]'];
  const headerRow = sheet2.getRow(16);
  headerRow.height = 40;  // Taller for wrapped text
  headers.forEach((h, i) => {
    const cell = headerRow.getCell(i + 2);  // Start from column B (index 2)
    cell.value = h;
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF37474F' } };  // Dark blue-grey
    cell.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 9 };
    cell.alignment = { horizontal: 'center', vertical: 'middle', wrapText: true };
    cell.border = {
      top: { style: 'thin', color: { argb: 'FF263238' } },
      bottom: { style: 'thin', color: { argb: 'FF263238' } }
    };
  });

  // Year 0 - Initial investment (row 17) - shifted +1
  const year0Row = sheet2.getRow(17);
  year0Row.getCell(2).value = 0;  // Column B (was A)
  year0Row.getCell(12).value = roundNum(-investment / 1000, 0);  // Column L (was K)
  year0Row.getCell(12).numFmt = '# ##0';
  year0Row.getCell(12).alignment = { horizontal: 'right', indent: 1 };
  year0Row.getCell(13).value = roundNum(-investment / 1000000, 2);  // Column M (was L)
  year0Row.getCell(13).numFmt = '# ##0.00';
  year0Row.getCell(13).alignment = { horizontal: 'right', indent: 1 };
  year0Row.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFEBEE' } };

  // Number format for data columns: # ##0.00 (space as thousands separator)
  const numFmtStandard = '# ##0.00';
  const numFmtMln = '# ##0.000';

  // Data rows (years 1-N) - all columns shifted +1 for margin column A
  let cumulativeNPV = -investment;
  for (let i = 0; i < cashFlows.length; i++) {
    const cf = cashFlows[i];
    const year = cf.year;
    const row = sheet2.getRow(17 + year);
    const dataRow = 17 + year;

    // Calculate values
    const pvDeg = year === 1 ? (1 - pvDegradationYear1) : (1 - pvDegradationYear1) * Math.pow(1 - pvDegradationYears2Plus, year - 1);
    const bessDeg = Math.pow(1 - bessDegradationRate, year);
    const savingsInflFactor = useInflation ? Math.pow(1 + inflationRate, year - 1) : 1;  // grid cost + savings: year-1
    const autoPvMwh = baseAutoconsumptionMwh * pvDeg;
    const autoBessMwh = (cf.selfConsumedBess || 0) / 1000;
    const sumaAutoMwh = autoPvMwh + autoBessMwh;
    const discountedCF = cf.net_cash_flow / Math.pow(1 + discountRate, year);
    cumulativeNPV += discountedCF;

    if (withFormulas) {
      row.getCell(2).value = year;  // Column B (was A)
      // Degradation PV (formula) - stored as decimal (0.98), displayed as %
      if (year === 1) {
        row.getCell(3).value = { formula: '1-$F$6', result: pvDeg };  // Changed E->F
      } else {
        row.getCell(3).value = { formula: '(1-$F$6)*POWER(1-$F$7,' + (year - 1) + ')', result: pvDeg };
      }
      row.getCell(3).numFmt = '0.0%';
      // Degradation BESS
      row.getCell(4).value = { formula: 'POWER(1-$F$8,' + year + ')', result: bessDeg };
      row.getCell(4).numFmt = '0.0%';
      // Zużycie
      row.getCell(5).value = { formula: '$F$13', result: annualConsumptionMwh };
      row.getCell(5).numFmt = numFmtStandard;
      row.getCell(5).alignment = { horizontal: 'right', indent: 1 };
      // Koszt OSD / Koszt RDN — CPI^(year-1): rok 1 = cena bazowa, rok 2+ eskalacja
      if (isRdn) {
        const gridCpiPart = useInflation ? '*POWER(1+$F$5,' + (year - 1) + ')' : '';
        row.getCell(6).value = { formula: '$F$12' + gridCpiPart, result: rdnGridCostYear1Tys * savingsInflFactor };
      } else {
        const gridCpiPart = useInflation ? '*POWER(1+$F$5,' + (year - 1) + ')' : '';
        row.getCell(6).value = { formula: '$F$13*$F$12' + gridCpiPart + '/1000', result: annualConsumptionMwh * totalEnergyPrice * savingsInflFactor / 1000 };
      }
      row.getCell(6).numFmt = numFmtStandard;
      row.getCell(6).alignment = { horizontal: 'right', indent: 1 };
      // Auto PV - formula: F11 (base autoconsumption) * degradation from column C
      row.getCell(7).value = { formula: '$F$11*C' + dataRow, result: autoPvMwh };
      row.getCell(7).numFmt = numFmtStandard;
      row.getCell(7).alignment = { horizontal: 'right', indent: 1 };
      // Auto BESS
      row.getCell(8).value = autoBessMwh > 0 ? roundNum(autoBessMwh, 2) : 0;
      row.getCell(8).numFmt = numFmtStandard;
      row.getCell(8).alignment = { horizontal: 'right', indent: 1 };
      // Suma Auto
      row.getCell(9).value = { formula: 'G' + dataRow + '+H' + dataRow, result: sumaAutoMwh };
      row.getCell(9).numFmt = numFmtStandard;
      row.getCell(9).alignment = { horizontal: 'right', indent: 1 };
      // Równow. OSD / Oszcz. RDN — CPI^(year-1): rok 1 = cena bazowa
      if (isRdn) {
        const A = "'Dane bazowe TCSL (Rok 1)'!";
        const cpi = useInflation ? `POWER(1+$F$5,${year}-1)` : '1';
        const rdnFormula = `(${A}F18*C${dataRow}*${cpi}+${A}F21*${cpi})/1000`;
        row.getCell(10).value = { formula: rdnFormula, result: roundNum(cf.savings / 1000, 2) };
      } else {
        const savCpiPart = useInflation ? '*POWER(1+$F$5,' + (year - 1) + ')' : '';
        row.getCell(10).value = { formula: 'I' + dataRow + '*$F$12' + savCpiPart + '/1000', result: cf.savings / 1000 };
      }
      row.getCell(10).numFmt = numFmtStandard;
      row.getCell(10).alignment = { horizontal: 'right', indent: 1 };
      // OPEX - formula with inflation: base OPEX * (1+inflation)^year (always applied)
      row.getCell(11).value = { formula: '$F$14*POWER(1+$F$5,' + year + ')', result: cf.opex / 1000 };
      row.getCell(11).numFmt = numFmtStandard;
      row.getCell(11).alignment = { horizontal: 'right', indent: 1 };
      // Oszczędn. (net)
      row.getCell(12).value = { formula: 'J' + dataRow + '-K' + dataRow, result: cf.net_cash_flow / 1000 };
      row.getCell(12).numFmt = numFmtStandard;
      row.getCell(12).alignment = { horizontal: 'right', indent: 1 };
      // NPV Skum.
      if (year === 1) {
        row.getCell(13).value = { formula: 'M17+L' + dataRow + '/POWER(1+$F$4,' + year + ')/1000', result: cumulativeNPV / 1000000 };
      } else {
        row.getCell(13).value = { formula: 'M' + (dataRow - 1) + '+L' + dataRow + '/POWER(1+$F$4,' + year + ')/1000', result: cumulativeNPV / 1000000 };
      }
      row.getCell(13).numFmt = numFmtMln;
      row.getCell(13).alignment = { horizontal: 'right', indent: 1 };
    } else {
      // Values only - all with formatting (shifted +1)
      row.getCell(2).value = year;
      row.getCell(3).value = pvDeg;
      row.getCell(3).numFmt = '0.0%';
      row.getCell(4).value = bessDeg;
      row.getCell(4).numFmt = '0.0%';
      row.getCell(5).value = roundNum(annualConsumptionMwh, 2);
      row.getCell(5).numFmt = numFmtStandard;
      row.getCell(5).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(6).value = isRdn
        ? roundNum(rdnGridCostYear1Tys * savingsInflFactor, 2)
        : roundNum(annualConsumptionMwh * totalEnergyPrice * savingsInflFactor / 1000, 2);
      row.getCell(6).numFmt = numFmtStandard;
      row.getCell(6).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(7).value = roundNum(autoPvMwh, 2);
      row.getCell(7).numFmt = numFmtStandard;
      row.getCell(7).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(8).value = roundNum(autoBessMwh, 2);
      row.getCell(8).numFmt = numFmtStandard;
      row.getCell(8).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(9).value = roundNum(sumaAutoMwh, 2);
      row.getCell(9).numFmt = numFmtStandard;
      row.getCell(9).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(10).value = roundNum(cf.savings / 1000, 2);
      row.getCell(10).numFmt = numFmtStandard;
      row.getCell(10).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(11).value = roundNum(cf.opex / 1000, 2);
      row.getCell(11).numFmt = numFmtStandard;
      row.getCell(11).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(12).value = roundNum(cf.net_cash_flow / 1000, 2);
      row.getCell(12).numFmt = numFmtStandard;
      row.getCell(12).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(13).value = roundNum(cumulativeNPV / 1000000, 3);
      row.getCell(13).numFmt = numFmtMln;
      row.getCell(13).alignment = { horizontal: 'right', indent: 1 };
    }
  }

  // Conditional formatting for NPV column (column M - shifted from L)
  sheet2.addConditionalFormatting({
    ref: 'M17:M' + lastDataRow,
    rules: [
      {
        type: 'cellIs',
        operator: 'greaterThanOrEqual',
        formulae: [0],
        style: { font: { color: { argb: 'FF2E7D32' } }, fill: { type: 'pattern', pattern: 'solid', bgColor: { argb: 'FFE8F5E9' } } },
        priority: 1
      },
      {
        type: 'cellIs',
        operator: 'lessThan',
        formulae: [0],
        style: { font: { color: { argb: 'FFC62828' } }, fill: { type: 'pattern', pattern: 'solid', bgColor: { argb: 'FFFFEBEE' } } },
        priority: 2
      }
    ]
  });

  // DPP Row Highlighting - DYNAMIC conditional formatting (updates when parameters change)
  // Condition: this row's cumulative NPV >= 0 AND previous row's cumulative NPV < 0
  // Only amber border frame (no fill/font change)
  sheet2.addConditionalFormatting({
    ref: 'B' + dataStartRow + ':M' + lastDataRow,
    rules: [{
      type: 'expression',
      formulae: ['AND($M' + dataStartRow + '>=0,$M' + (dataStartRow - 1) + '<0)'],
      style: {
        border: {
          top: { style: 'medium', color: { argb: 'FFFFC107' } },
          bottom: { style: 'medium', color: { argb: 'FFFFC107' } }
        }
      },
      priority: 3
    }]
  });

  // Freeze header row (row 16) with clean look
  sheet2.views = [{ state: 'frozen', ySplit: 16, xSplit: 0, showGridLines: false, showRowColHeaders: false }];

  // Summary section below data (shifted +1 column)
  const summaryStartRow = lastDataRow + 3;
  sheet2.getCell('C' + summaryStartRow).value = 'PODSUMOWANIE KPI';
  sheet2.getCell('C' + summaryStartRow).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  sheet2.mergeCells('C' + summaryStartRow + ':H' + summaryStartRow);
  sheet2.getCell('C' + summaryStartRow).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

  // KPI rows with formulas - columns shifted: E->F, K->L, L->M, etc.
  // IRR formula: Excel IRR function on cash flows (L17:L{lastRow}) - L17 contains -CAPEX, L18+ are net savings
  const irrFormula = 'IRR(L17:L' + lastDataRow + ')*100';

  // Simple Payback formula: CAPEX / average annual savings (first 5 years)
  const simplePaybackFormula = '$F$10/(AVERAGE(L' + dataStartRow + ':L' + Math.min(dataStartRow + 4, lastDataRow) + '))';

  // DPP formula: Find first year where cumulative NPV >= 0, with interpolation
  // n = count of years with negative NPV, p = last negative NPV, q = first non-negative NPV
  // DPP = n + (-p) / (q - p) for fractional year precision
  // Using repeated SUMPRODUCT instead of LET for ExcelJS compatibility (LET adds @)
  const _n = 'SUMPRODUCT((M' + dataStartRow + ':M' + lastDataRow + '<0)*1)';
  const _mRange = 'M' + (dataStartRow - 1) + ':M' + lastDataRow;
  const dppFormula = _n + '\n+ (-INDEX(' + _mRange + ', ' + _n + ' + 1))\n/ (INDEX(' + _mRange + ', ' + _n + ' + 2)\n   - INDEX(' + _mRange + ', ' + _n + ' + 1))';

  // LCOE formula — EXACT from reference Excel
  const lcoeFormula = '($F$10 * 1000\n + SUMPRODUCT(\n     K' + dataStartRow + ':K' + lastDataRow + '\n     / POWER(1 + $F$4,\n             B' + dataStartRow + ':B' + lastDataRow + ')))\n/ SUMPRODUCT(\n     I' + dataStartRow + ':I' + lastDataRow + '\n     / POWER(1 + $F$4,\n             B' + dataStartRow + ':B' + lastDataRow + '))';

  const kpiRows = [
    ['CAPEX (inwestycja):', withFormulas ? { formula: '$F$10' } : roundNum(investment / 1000, 2), 'tys. PLN', '= Nakład początkowy', '# ##0.00'],
    ['Suma oszczędności:', withFormulas ? { formula: 'SUM(L' + dataStartRow + ':L' + lastDataRow + ')' } : roundNum(cashFlows.reduce((s, cf) => s + cf.net_cash_flow, 0) / 1000, 2), 'tys. PLN', '= Suma kolumny L', '# ##0.00'],
    ['NPV:', withFormulas ? { formula: 'M' + lastDataRow } : roundNum(centralizedCalc.capex.npv / 1000000, 3), 'mln PLN', '= Wartość bieżąca netto', '# ##0.000'],
    ['IRR:', withFormulas ? { formula: irrFormula } : roundNum(centralizedCalc.capex.irr * 100, 2), '%', '= Wewnętrzna stopa zwrotu', '# ##0.00'],
    ['ROI:', withFormulas ? { formula: '(F' + (summaryStartRow + 2) + '-F' + (summaryStartRow + 1) + ')/F' + (summaryStartRow + 1) + '*100' } : roundNum(roi, 2), '%', '= (Oszczędności - CAPEX) / CAPEX', '# ##0.00'],
    ['Prosty zwrot (Payback):', withFormulas ? { formula: simplePaybackFormula } : roundNum(centralizedCalc.capex.simplePayback, 2), 'lat', '= CAPEX / średnie roczne oszczędności', '# ##0.00'],
    ['Zdyskontowany zwrot (DPP):', withFormulas ? { formula: dppFormula } : (centralizedCalc.capex.discountedPayback !== null && centralizedCalc.capex.discountedPayback !== undefined ? roundNum(centralizedCalc.capex.discountedPayback, 2) : '-'), 'lat', '= Rok gdy NPV >= 0', '# ##0.00'],
    ['LCOE (koszt energii):', withFormulas ? { formula: lcoeFormula } : roundNum(centralizedCalc.capex.lcoe, 2), 'PLN/MWh', '= Levelized Cost of Energy', '# ##0.00']
  ];

  kpiRows.forEach((kpi, idx) => {
    const row = sheet2.getRow(summaryStartRow + 1 + idx);
    row.getCell(3).value = kpi[0];  // Column C (shifted from B)
    row.getCell(3).font = { bold: true };
    if (typeof kpi[1] === 'object' && kpi[1].formula) {
      row.getCell(6).value = kpi[1];  // Column F (shifted from E)
    } else {
      row.getCell(6).value = kpi[1];
    }
    row.getCell(6).font = { bold: true };
    row.getCell(6).alignment = { horizontal: 'right', indent: 1 };
    // Apply number format if value is a number (not '-' string)
    if (kpi[4] && kpi[1] !== '-') {
      row.getCell(6).numFmt = kpi[4];
    }
    row.getCell(7).value = kpi[2];  // Column G (shifted from F)
    row.getCell(8).value = kpi[3];  // Column H (shifted from G)
    row.getCell(8).font = { italic: true, color: { argb: 'FF757575' } };

    // Highlight NPV, IRR rows
    if (kpi[0].includes('NPV') || kpi[0].includes('IRR')) {
      const npvVal = kpi[0].includes('NPV') ? centralizedCalc.capex.npv : centralizedCalc.capex.irr;
      if (npvVal > 0) {
        row.getCell(6).font = { bold: true, color: { argb: 'FF2E7D32' } };
        row.getCell(6).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
      }
    }
  });

  // Note about formulas + cell notes on complex KPI formulas
  if (withFormulas) {
    // DPP note (row index 6 in kpiRows)
    sheet2.getRow(summaryStartRow + 7).getCell(6).note = `-- Interpolowany DPP\n-- n = lata z ujemnym NPV\n-- DPP = n + (-ostatni_ujemny) / (pierwszy_dodatni - ostatni_ujemny)`;
    // LCOE note (row index 7 in kpiRows)
    sheet2.getRow(summaryStartRow + 8).getCell(6).note = `-- (CAPEX + PV_OPEX) / PV_produkcja\n-- Levelized Cost of Energy`;

    const noteRow = summaryStartRow + 11;
    sheet2.getCell('C' + noteRow).value = 'UWAGA: Zmień parametry w komórkach F4:F14 aby zobaczyć wpływ na wyniki.';
    sheet2.getCell('C' + noteRow).font = { italic: true, color: { argb: 'FF666666' } };
    sheet2.getCell('C' + (noteRow + 1)).value = 'Wszystkie obliczenia w kolumnach C-M zawierają formuły Excel.';
    sheet2.getCell('C' + (noteRow + 1)).font = { italic: true, color: { argb: 'FF666666' } };
  }

  // ========== SHEET 3: Analiza CFO ==========
  const sheet3 = workbook.addWorksheet('Analiza CFO');
  sheet3.columns = [
    { width: 3 },   // A: margin
    { width: 32 },  // B: labels
    { width: 18 },  // C: values
    { width: 16 },  // D: values
    { width: 16 },  // E: values
    { width: 16 },  // F: values
    { width: 16 },  // G: values
    { width: 18 }   // H: values
  ];
  sheet3.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Sheet2 reference prefix for formulas
  const s2 = "'CAPEX Rok po Roku'!";

  // --- HEADER ---
  sheet3.mergeCells('B1:H1');
  sheet3.getCell('B1').value = 'ANALIZA CFO - Model CAPEX (Inwestor)';
  sheet3.getCell('B1').font = { bold: true, size: 16, color: { argb: 'FF1565C0' } };
  sheet3.getCell('B1').alignment = { horizontal: 'center', vertical: 'middle' };

  // Add logo to Sheet 3 (top-right)
  if (logoImageId !== null) {
    sheet3.addImage(logoImageId, {
      tl: { col: 7.2, row: 0.1 },
      ext: { width: 200, height: 50 }
    });
  }

  sheet3.mergeCells('B2:H2');
  sheet3.getCell('B2').value = `Perspektywa inwestora - okres analizy: ${analysisPeriod} lat`;
  sheet3.getCell('B2').font = { italic: true, size: 11, color: { argb: 'FF616161' } };
  sheet3.getCell('B2').alignment = { horizontal: 'center', vertical: 'middle' };

  // --- SECTION 0: PARAMETRY (row 4) ---
  let cfoRow = 4;
  sheet3.mergeCells(`B${cfoRow}:H${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = 'PARAMETRY MODELU';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11, color: { argb: 'FF5D4037' } };
  sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEFEBE9' } };

  cfoRow++;
  // Row 5: Parameters - with formulas referencing Sheet2 (column F after margin shift)
  sheet3.getCell(`B${cfoRow}`).value = 'CAPEX [tys. PLN]';
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: `${s2}F10`, result: roundNum(investment / 1000, 0) }
    : roundNum(investment / 1000, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true };
  sheet3.getCell(`D${cfoRow}`).value = 'Okres analizy [lat]';
  sheet3.getCell(`E${cfoRow}`).value = withFormulas
    ? { formula: `${s2}F9`, result: analysisPeriod }
    : analysisPeriod;
  sheet3.getCell(`E${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet3.getCell(`F${cfoRow}`).value = 'Stopa dyskontowa';
  sheet3.getCell(`G${cfoRow}`).value = withFormulas
    ? { formula: `${s2}F4`, result: discountRate }
    : discountRate;
  sheet3.getCell(`G${cfoRow}`).numFmt = '0.0%';
  sheet3.getCell(`G${cfoRow}`).font = { bold: true };

  cfoRow++;
  // Row 6: More parameters
  sheet3.getCell(`B${cfoRow}`).value = 'Autokonsumpcja [MWh/rok]';
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: `${s2}F11`, result: roundNum(baseAutoconsumptionMwh, 1) }
    : roundNum(baseAutoconsumptionMwh, 1);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0.0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true };
  sheet3.getCell(`D${cfoRow}`).value = isRdn ? 'Efekt. cena RDN [PLN/MWh]' : 'Cena energii [PLN/MWh]';
  sheet3.getCell(`E${cfoRow}`).value = isRdn
    ? roundNum(effectiveEnergyPrice, 0)
    : (withFormulas ? { formula: `${s2}F12`, result: roundNum(totalEnergyPrice, 0) } : roundNum(totalEnergyPrice, 0));
  sheet3.getCell(`E${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`E${cfoRow}`).font = { bold: true };
  sheet3.getCell(`F${cfoRow}`).value = 'Inflacja';
  sheet3.getCell(`G${cfoRow}`).value = withFormulas
    ? { formula: `${s2}F5`, result: inflationRate }
    : inflationRate;
  sheet3.getCell(`G${cfoRow}`).numFmt = '0.0%';
  sheet3.getCell(`G${cfoRow}`).font = { bold: true };

  cfoRow++;
  // Row 7: Degradation
  sheet3.getCell(`B${cfoRow}`).value = 'Degradacja PV Rok 1';
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: `${s2}F6`, result: pvDegradationYear1 }
    : pvDegradationYear1;
  sheet3.getCell(`C${cfoRow}`).numFmt = '0.0%';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true };
  sheet3.getCell(`D${cfoRow}`).value = 'Degradacja PV Lata 2+';
  sheet3.getCell(`E${cfoRow}`).value = withFormulas
    ? { formula: `${s2}F7`, result: pvDegradationYears2Plus }
    : pvDegradationYears2Plus;
  sheet3.getCell(`E${cfoRow}`).numFmt = '0.00%';
  sheet3.getCell(`E${cfoRow}`).font = { bold: true };

  // --- SECTION 1: KLUCZOWE KPI DLA ZARZĄDU ---
  cfoRow += 2;
  const kpiSectionRow = cfoRow;
  sheet3.mergeCells(`B${cfoRow}:H${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = `KLUCZOWE KPI DLA ZARZĄDU (analiza ${analysisPeriod} lat)`;
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF2E7D32' } };
  sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  // Calculate total savings from cash flows
  const totalSavings = cashFlows.reduce((sum, cf) => sum + (cf.net_cash_flow || 0), 0);
  const npvValue = centralizedCalc.capex.npv;
  const irrValue = centralizedCalc.capex.irr;
  const simplePaybackValue = centralizedCalc.capex.simplePayback;
  const dppValue = centralizedCalc.capex.discountedPayback;
  const lcoeValue = centralizedCalc.capex.lcoe;
  const roiValue = ((totalSavings - investment) / investment) * 100;

  // Formula references for KPIs (referencing Sheet2 data)
  // Sheet2 data: row 17 = Year 0 (-CAPEX), rows 18+ = Years 1-N
  // Column mapping after margin column A: B=Rok, I=SumaAuto, K=OPEX, L=Oszczędn., M=NPV Skum., F=params
  const kpiCapexFormula = `${s2}F10`;
  const kpiSavingsFormula = `SUM(${s2}L${dataStartRow}:${s2}L${lastDataRow})`;  // Oszczędności in column L
  const kpiNpvFormula = `${s2}M${lastDataRow}`;  // Last row cumulative NPV in mln PLN (column M)
  const kpiIrrFormula = `IRR(${s2}L17:${s2}L${lastDataRow})`;  // IRR needs Year 0 (-CAPEX) - column L
  const kpiRoiFormula = `(SUM(${s2}L${dataStartRow}:${s2}L${lastDataRow})-${s2}F10)/${s2}F10`;
  const kpiPaybackFormula = `${s2}F10/AVERAGE(${s2}L${dataStartRow}:${s2}L${Math.min(dataStartRow + 4, lastDataRow)})`;
  const _nCfo = `SUMPRODUCT((${s2}M${dataStartRow}:${s2}M${lastDataRow}<0)*1)`;
  const _mCfo = `${s2}M${dataStartRow - 1}:${s2}M${lastDataRow}`;
  const kpiDppFormula = `${_nCfo}+(-INDEX(${_mCfo},${_nCfo}+1))/(INDEX(${_mCfo},${_nCfo}+2)-INDEX(${_mCfo},${_nCfo}+1))`;
  const kpiLcoeFormula = `(${s2}F10*1000+SUMPRODUCT(${s2}K${dataStartRow}:${s2}K${lastDataRow}/POWER(1+${s2}F4,${s2}B${dataStartRow}:${s2}B${lastDataRow})))/SUMPRODUCT(${s2}I${dataStartRow}:${s2}I${lastDataRow}/POWER(1+${s2}F4,${s2}B${dataStartRow}:${s2}B${lastDataRow}))`;

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = 'CAPEX (inwestycja początkowa)';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: kpiCapexFormula, result: roundNum(investment / 1000, 0) }
    : roundNum(investment / 1000, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FFC62828' } };
  sheet3.getCell(`D${cfoRow}`).value = 'tys. PLN';
  sheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  sheet3.getCell(`E${cfoRow}`).value = 'Nakład inwestycyjny (jednorazowy)';
  sheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '💰 Suma oszczędności (niedyskontowane)';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: kpiSavingsFormula, result: roundNum(totalSavings / 1000, 0) }
    : roundNum(totalSavings / 1000, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  sheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  sheet3.getCell(`D${cfoRow}`).value = 'tys. PLN';
  sheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  sheet3.getCell(`E${cfoRow}`).value = `Suma oszczędności przez ${analysisPeriod} lat`;
  sheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '📊 NPV (wartość bieżąca netto)';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: kpiNpvFormula, result: roundNum(npvValue / 1000000, 2) }
    : roundNum(npvValue / 1000000, 2);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0.00';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: npvValue > 0 ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  sheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: npvValue > 0 ? 'FFE8F5E9' : 'FFFFEBEE' } };
  sheet3.getCell(`D${cfoRow}`).value = 'mln PLN';
  sheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  sheet3.getCell(`E${cfoRow}`).value = npvValue > 0 ? 'Projekt opłacalny (NPV > 0)' : 'Projekt nieopłacalny (NPV < 0)';
  sheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '📈 IRR (wewnętrzna stopa zwrotu)';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: kpiIrrFormula, result: irrValue }
    : irrValue;
  sheet3.getCell(`C${cfoRow}`).numFmt = '0.0%';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: irrValue > discountRate ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  sheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: irrValue > discountRate ? 'FFE8F5E9' : 'FFFFEBEE' } };
  sheet3.getCell(`D${cfoRow}`).value = '';
  sheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  sheet3.getCell(`E${cfoRow}`).value = irrValue > discountRate ? `IRR > stopa dyskontowa (${roundNum(discountRate * 100, 1)}%)` : `IRR < stopa dyskontowa (${roundNum(discountRate * 100, 1)}%)`;
  sheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '💵 ROI (zwrot z inwestycji)';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: kpiRoiFormula, result: roiValue / 100 }
    : roiValue / 100;
  sheet3.getCell(`C${cfoRow}`).numFmt = '0.0%';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: roiValue > 0 ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  sheet3.getCell(`D${cfoRow}`).value = '';
  sheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  sheet3.getCell(`E${cfoRow}`).value = '= (Oszczędności - CAPEX) / CAPEX';
  sheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '⏱️ Prosty zwrot (Payback)';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: kpiPaybackFormula, result: roundNum(simplePaybackValue, 1) }
    : roundNum(simplePaybackValue, 1);
  sheet3.getCell(`C${cfoRow}`).numFmt = '0.0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet3.getCell(`D${cfoRow}`).value = 'lat';
  sheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  sheet3.getCell(`E${cfoRow}`).value = 'CAPEX / średnie roczne oszczędności';
  sheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '⏱️ Zdyskontowany zwrot (DPP)';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  const hasDpp = dppValue !== null && dppValue !== undefined;
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: kpiDppFormula, result: hasDpp ? roundNum(dppValue, 1) : analysisPeriod + 1 }
    : (hasDpp ? roundNum(dppValue, 1) : 'Powyzej okresu');
  sheet3.getCell(`C${cfoRow}`).numFmt = hasDpp ? '0.0' : '@';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet3.getCell(`D${cfoRow}`).value = hasDpp ? 'lat' : '';
  sheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  sheet3.getCell(`E${cfoRow}`).value = 'Rok gdy skumulowane NPV >= 0';
  sheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '⚡ LCOE (koszt energii)';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: kpiLcoeFormula, result: roundNum(lcoeValue, 0) }
    : roundNum(lcoeValue, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: lcoeValue < effectiveEnergyPrice ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  sheet3.getCell(`D${cfoRow}`).value = 'PLN/MWh';
  sheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  const priceLabel = isRdn ? 'efekt. cena RDN' : 'cena sieci';
  sheet3.getCell(`E${cfoRow}`).value = lcoeValue < effectiveEnergyPrice ? `LCOE < ${priceLabel} (${roundNum(effectiveEnergyPrice, 0)} PLN/MWh)` : `LCOE > ${priceLabel}`;
  sheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  // Add borders to KPI section
  for (let r = kpiSectionRow + 1; r <= cfoRow; r++) {
    sheet3.getRow(r).getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    sheet3.getRow(r).getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
  }

  // --- SECTION 2: ANALIZA WRAŻLIWOŚCI - TORNADO ---
  cfoRow += 2;
  sheet3.mergeCells(`B${cfoRow}:H${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = 'ANALIZA WRAŻLIWOŚCI - TORNADO CHART';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

  cfoRow++;
  sheet3.mergeCells(`B${cfoRow}:G${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = `Wpływ na NPV [mln PLN] przy zmianie parametru:`;
  sheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };

  // Calculate sensitivity - proper NPV recalculation for each scenario
  // NPV = -CAPEX + Σ(discounted cash flows), so parameter changes have leverage effect
  const baseNpvMln = npvValue / 1000000;

  // Base parameters for calculateCapexNPV() recalculation
  const capexNpvBaseParams = {
    capacity_kwp: capacityKwp,
    self_consumed_annual_kwh: baseAutoconsumptionMwh * 1000,
    total_energy_price_per_kwh: effectiveEnergyPrice / 1000,
    capex_per_kwp: investment / capacityKwp,
    opex_per_kwp: params.opex_per_kwp,
    degradation_rate: pvDegradationYears2Plus,
    discount_rate: discountRate,
    analysis_period: analysisPeriod,
    inflation_rate: inflationRate
  };

  // Recalculate NPV for each tornado scenario using full financial model
  const npvEnergyPess = calculateCapexNPV({...capexNpvBaseParams, total_energy_price_per_kwh: effectiveEnergyPrice / 1000 * 0.80});
  const npvEnergyOpt  = calculateCapexNPV({...capexNpvBaseParams, total_energy_price_per_kwh: effectiveEnergyPrice / 1000 * 1.20});
  const npvCapexPess  = calculateCapexNPV({...capexNpvBaseParams, capex_per_kwp: (investment / capacityKwp) * 1.20});
  const npvCapexOpt   = calculateCapexNPV({...capexNpvBaseParams, capex_per_kwp: (investment / capacityKwp) * 0.80});
  const npvYieldPess  = calculateCapexNPV({...capexNpvBaseParams, self_consumed_annual_kwh: baseAutoconsumptionMwh * 1000 * 0.85});
  const npvYieldOpt   = calculateCapexNPV({...capexNpvBaseParams, self_consumed_annual_kwh: baseAutoconsumptionMwh * 1000 * 1.15});
  const npvDiscPess   = calculateCapexNPV({...capexNpvBaseParams, discount_rate: discountRate + 0.02});
  const npvDiscOpt    = calculateCapexNPV({...capexNpvBaseParams, discount_rate: Math.max(0.01, discountRate - 0.02)});

  // Build tornado data array with proper values, sorted by impact
  const tornadoItems = [
    {
      param: 'Cena energii z sieci', variation: '±20%',
      pessNpv: npvEnergyPess / 1e6, optNpv: npvEnergyOpt / 1e6,
      pessFormula: `(${s2}M${lastDataRow} + ${s2}F10 / 1000)\n* 0.8\n- ${s2}F10 / 1000`,
      optFormula: `(${s2}M${lastDataRow} + ${s2}F10 / 1000)\n* 1.2\n- ${s2}F10 / 1000`,
      pessNote: `-- NPV CAPEX: cena sieci -20%\n-- (NPV+CAPEX)×0.8 - CAPEX`,
      optNote: `-- NPV CAPEX: cena sieci +20%`
    },
    {
      param: 'CAPEX (koszt inwestycji)', variation: '±20%',
      pessNpv: npvCapexPess / 1e6, optNpv: npvCapexOpt / 1e6,
      pessFormula: `${s2}M${lastDataRow}\n- ${s2}F10 * 0.2 / 1000`,
      optFormula: `${s2}M${lastDataRow}\n+ ${s2}F10 * 0.2 / 1000`,
      pessNote: `-- NPV CAPEX: inwestycja +20%`,
      optNote: `-- NPV CAPEX: inwestycja -20%`
    },
    {
      param: 'Yield PV (produkcja)', variation: '±15%',
      pessNpv: npvYieldPess / 1e6, optNpv: npvYieldOpt / 1e6,
      pessFormula: `(${s2}M${lastDataRow} + ${s2}F10 / 1000)\n* 0.85\n- ${s2}F10 / 1000`,
      optFormula: `(${s2}M${lastDataRow} + ${s2}F10 / 1000)\n* 1.15\n- ${s2}F10 / 1000`,
      pessNote: `-- NPV CAPEX: yield PV -15%`,
      optNote: `-- NPV CAPEX: yield PV +15%`
    },
    {
      param: 'Stopa dyskontowa', variation: '±2pp',
      pessNpv: npvDiscPess / 1e6, optNpv: npvDiscOpt / 1e6,
      pessFormula: `${s2}M${lastDataRow}\n* ${roundNum(npvDiscPess / npvValue, 4)}`,
      optFormula: `${s2}M${lastDataRow}\n* ${roundNum(npvDiscOpt / npvValue, 4)}`,
      pessNote: `-- NPV CAPEX: stopa dyskontowa +2pp`,
      optNote: `-- NPV CAPEX: stopa dyskontowa -2pp`
    }
  ];

  // Calculate range and sort by impact (biggest first)
  tornadoItems.forEach(t => { t.range = Math.abs(t.optNpv - t.pessNpv); });
  tornadoItems.sort((a, b) => b.range - a.range);

  console.log('📊 CAPEX Tornado (recalculated):', tornadoItems.map(t =>
    `${t.param}: ${roundNum(t.pessNpv, 2)} / ${roundNum(baseNpvMln, 2)} / ${roundNum(t.optNpv, 2)} (range: ${roundNum(t.range, 2)})`
  ));

  // Tornado table header
  cfoRow += 2;
  const tornadoHeaderRow = cfoRow;
  sheet3.getCell(`B${cfoRow}`).value = 'Parametr';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = 'Zmiana';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`D${cfoRow}`).value = 'Pesymistyczny';
  sheet3.getCell(`D${cfoRow}`).font = { bold: true, color: { argb: 'FFC62828' } };
  sheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`E${cfoRow}`).value = 'Bazowy';
  sheet3.getCell(`E${cfoRow}`).font = { bold: true };
  sheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`F${cfoRow}`).value = 'Optymistyczny';
  sheet3.getCell(`F${cfoRow}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  sheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`G${cfoRow}`).value = 'Rozpiętość';
  sheet3.getCell(`G${cfoRow}`).font = { bold: true };
  sheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };

  // Style header row
  for (let c = 2; c <= 7; c++) {
    sheet3.getRow(cfoRow).getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
    sheet3.getRow(cfoRow).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
  }

  // Render tornado data rows (sorted by impact)
  tornadoItems.forEach(t => {
    cfoRow++;
    sheet3.getCell(`B${cfoRow}`).value = t.param;
    sheet3.getCell(`C${cfoRow}`).value = t.variation;
    sheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };

    // Pessimistic
    sheet3.getCell(`D${cfoRow}`).value = withFormulas
      ? { formula: t.pessFormula, result: roundNum(t.pessNpv, 2) }
      : roundNum(t.pessNpv, 2);
    if (withFormulas && t.pessNote) sheet3.getCell(`D${cfoRow}`).note = t.pessNote;
    sheet3.getCell(`D${cfoRow}`).numFmt = '# ##0.00';
    sheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };
    sheet3.getCell(`D${cfoRow}`).font = { color: { argb: 'FFC62828' } };
    sheet3.getCell(`D${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFEBEE' } };

    // Base
    sheet3.getCell(`E${cfoRow}`).value = withFormulas
      ? { formula: `${s2}M${lastDataRow}`, result: roundNum(baseNpvMln, 2) }
      : roundNum(baseNpvMln, 2);
    sheet3.getCell(`E${cfoRow}`).numFmt = '# ##0.00';
    sheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };
    sheet3.getCell(`E${cfoRow}`).font = { bold: true };
    sheet3.getCell(`E${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    // Optimistic
    sheet3.getCell(`F${cfoRow}`).value = withFormulas
      ? { formula: t.optFormula, result: roundNum(t.optNpv, 2) }
      : roundNum(t.optNpv, 2);
    if (withFormulas && t.optNote) sheet3.getCell(`F${cfoRow}`).note = t.optNote;
    sheet3.getCell(`F${cfoRow}`).numFmt = '# ##0.00';
    sheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
    sheet3.getCell(`F${cfoRow}`).font = { color: { argb: 'FF2E7D32' } };
    sheet3.getCell(`F${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

    // Range
    sheet3.getCell(`G${cfoRow}`).value = withFormulas
      ? { formula: `F${cfoRow}-D${cfoRow}`, result: roundNum(t.range, 2) }
      : roundNum(t.range, 2);
    sheet3.getCell(`G${cfoRow}`).numFmt = '# ##0.00';
    sheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };
    sheet3.getCell(`G${cfoRow}`).font = { bold: true };
  });

  // Add borders to tornado rows
  for (let r = tornadoHeaderRow + 1; r <= cfoRow; r++) {
    for (let c = 2; c <= 7; c++) {
      sheet3.getRow(r).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  }

  // --- SECTION 3: MACIERZ WRAŻLIWOŚCI - NPV vs Cena Sieci vs Yield ---
  cfoRow += 3;
  sheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = 'MACIERZ WRAŻLIWOŚCI - NPV vs Cena Sieci vs Yield';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF7B1FA2' } };
  sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF3E5F5' } };

  const yieldVariations = [-0.15, -0.10, -0.05, 0, 0.05, 0.10, 0.15];
  const priceVariations = [-0.20, -0.10, 0, 0.10, 0.20];
  const _col = (n) => String.fromCharCode(64 + n); // 1=A, 2=B, 3=C, ...

  // Pre-compute self-consumption for each yield variation using hourly profiles
  const selfConsumptionByYield = {};
  let hasHourlyData = false;
  try {
    hasHourlyData = yieldVariations.some(yv => _computeSelfConsumptionForYield(1 + yv) !== null);
    yieldVariations.forEach(yv => {
      const sc = _computeSelfConsumptionForYield(1 + yv);
      selfConsumptionByYield[yv] = sc !== null ? sc : baseAutoconsumptionMwh * 1000 * (1 + yv);
    });
  } catch (scErr) {
    console.warn('⚠️ Self-consumption pre-compute failed, using linear fallback:', scErr);
    yieldVariations.forEach(yv => {
      selfConsumptionByYield[yv] = baseAutoconsumptionMwh * 1000 * (1 + yv);
    });
  }
  if (hasHourlyData) {
    console.log('📊 Sensitivity matrix: using non-linear self-consumption from hourly profiles');
  } else {
    console.log('📊 Sensitivity matrix: hourly data unavailable, using linear approximation');
  }

  const baseNpvTys = npvValue / 1000;
  const capexNpvBaseForMatrix = {
    capacity_kwp: capacityKwp,
    capex_per_kwp: investment / capacityKwp,
    opex_per_kwp: params.opex_per_kwp || 24,
    degradation_rate: pvDegradationYears2Plus || 0.004,
    discount_rate: discountRate,
    analysis_period: analysisPeriod || 30,
    inflation_rate: inflationRate
  };

  // Matrix headers
  cfoRow += 2;
  sheet3.getCell(`B${cfoRow}`).value = 'NPV [tys. PLN]';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
  sheet3.mergeCells(`C${cfoRow}:I${cfoRow}`);
  sheet3.getCell(`C${cfoRow}`).value = '← Yield PV →';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, size: 10 };
  sheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };

  cfoRow++;
  const matrixHeaderRow = cfoRow;
  sheet3.getCell(`B${cfoRow}`).value = 'Cena sieci ↓';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
  sheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'right' };
  yieldVariations.forEach((yv, i) => {
    sheet3.getCell(cfoRow, 3 + i).value = yv;
    sheet3.getCell(cfoRow, 3 + i).numFmt = '+0%;-0%;0%';
    sheet3.getCell(cfoRow, 3 + i).font = { bold: true, size: 9 };
    sheet3.getCell(cfoRow, 3 + i).alignment = { horizontal: 'center' };
    sheet3.getCell(cfoRow, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  // Matrix data — full NPV recalculation per cell
  priceVariations.forEach(pv => {
    cfoRow++;
    sheet3.getCell(`B${cfoRow}`).value = pv;
    sheet3.getCell(`B${cfoRow}`).numFmt = '+0%;-0%;0%';
    sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
    sheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'right' };
    sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    yieldVariations.forEach((yv, i) => {
      // Always compute the value (used as result hint for formulas or as the cell value)
      let adjNpv;
      try {
        adjNpv = calculateCapexNPV({
          ...capexNpvBaseForMatrix,
          self_consumed_annual_kwh: selfConsumptionByYield[yv],
          total_energy_price_per_kwh: effectiveEnergyPrice / 1000 * (1 + pv)
        }) / 1000;
      } catch (npvErr) {
        console.error(`❌ NPV calc failed for pv=${pv}, yv=${yv}:`, npvErr);
        const sm = (1 + pv) * (1 + yv);
        adjNpv = (baseNpvTys + (investment / 1000)) * sm - (investment / 1000);
      }
      if (!isFinite(adjNpv)) adjNpv = 0;

      const cell = sheet3.getCell(cfoRow, 3 + i);
      if (withFormulas) {
        const colLetter = _col(3 + i);
        const yieldRef = `${colLetter}$${matrixHeaderRow}`;
        const priceRef = `$B${cfoRow}`;
        const bRange = `${s2}$B$${dataStartRow}:$B$${lastDataRow}`;
        const cRange = `${s2}$C$${dataStartRow}:$C$${lastDataRow}`;
        const kRange = `${s2}$K$${dataStartRow}:$K$${lastDataRow}`;
        const iRange = `${s2}$I$${dataStartRow}:$I$${lastDataRow}`;
        let formula;
        if (isRdn) {
          // RDN mode: uses TCSL audit sheet (F18=variable energy savings, F21=capacity fee savings)
          const A = "'Dane bazowe TCSL (Rok 1)'!";
          formula = `SUMPRODUCT(\n  (${A}$F$18 * ${cRange}\n   * (1 + ${yieldRef}) * (1 + ${priceRef})\n   * POWER(1 + ${s2}$F$5, ${bRange} - 1)\n   + ${A}$F$21 * (1 + ${yieldRef})\n   * POWER(1 + ${s2}$F$5, ${bRange} - 1))\n  / 1000 - ${kRange},\n  1 / POWER(1 + ${s2}$F$4, ${bRange}))\n- ${s2}$F$10`;
        } else {
          // Non-RDN: uses Suma Auto (col I) * energy price ($F$12) with CPI
          formula = `SUMPRODUCT(\n  (${iRange} * ${s2}$F$12\n   * (1 + ${yieldRef}) * (1 + ${priceRef})\n   * POWER(1 + ${s2}$F$5, ${bRange} - 1))\n  / 1000 - ${kRange},\n  1 / POWER(1 + ${s2}$F$4, ${bRange}))\n- ${s2}$F$10`;
        }
        cell.value = { formula, result: roundNum(adjNpv, 0) };
        cell.note = `-- NPV CAPEX przy yield ${yieldRef} i cena ${priceRef}`;
      } else {
        cell.value = roundNum(adjNpv, 0);
      }
      cell.numFmt = '# ##0';
      cell.alignment = { horizontal: 'center' };

      // Color coding
      if (adjNpv > baseNpvTys * 1.1) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
        cell.font = { color: { argb: 'FF2E7D32' }, bold: true };
      } else if (adjNpv > baseNpvTys * 0.9) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFFDE' } };
      } else if (adjNpv > 0) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFECB3' } };
      } else {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFCDD2' } };
        cell.font = { color: { argb: 'FFC62828' }, bold: true };
      }

      cell.border = {
        top: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        left: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        right: { style: 'thin', color: { argb: 'FFE0E0E0' } }
      };
    });
  });

  // --- SECTION 4: ESG ---
  const co2FactorKgPerKwh = 0.7;
  const annualCO2Tons = baseAutoconsumptionMwh * co2FactorKgPerKwh;
  const degradationFactor = 1 - pvDegradationYears2Plus * analysisPeriod / 2;
  const totalCO2Tons = annualCO2Tons * analysisPeriod * degradationFactor;

  cfoRow += 3;
  sheet3.mergeCells(`B${cfoRow}:H${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = `ESG - WPŁYW ŚRODOWISKOWY (${analysisPeriod} lat)`;
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF00695C' } };
  sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0F2F1' } };

  // ESG formulas reference autokonsumpcja from Sheet2
  // Annual CO2 = autokonsumpcja * 0.7 (co2 factor)
  const esgAutoFormula = `${s2}F11`;
  const esgCo2AnnualFormula = `${s2}F11*0.7`;
  const esgCo2TotalFormula = `${s2}F11*0.7*${s2}F9*(1-${s2}F7*${s2}F9/2)`;
  const esgCarsFormula = `${s2}F11*0.7/4.6`;
  const esgTreesFormula = `${s2}F11*0.7/0.022`;
  const esgFlightsFormula = `${s2}F11*0.7/0.255`;

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = 'Autokonsumpcja PV [MWh/rok]';
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: esgAutoFormula, result: roundNum(baseAutoconsumptionMwh, 0) }
    : roundNum(baseAutoconsumptionMwh, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  sheet3.getCell(`D${cfoRow}`).value = 'Energia zielona zamiast z sieci';
  sheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = 'Współczynnik emisji sieci [t CO₂/MWh]';
  sheet3.getCell(`C${cfoRow}`).value = 0.7;
  sheet3.getCell(`C${cfoRow}`).numFmt = '0.0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  sheet3.getCell(`D${cfoRow}`).value = 'Średnia dla Polski';
  sheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  const esgCo2AnnualRow = cfoRow;
  sheet3.getCell(`B${cfoRow}`).value = '🌍 Redukcja CO₂ rocznie [tony]';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: esgCo2AnnualFormula, result: roundNum(annualCO2Tons, 0) }
    : roundNum(annualCO2Tons, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  sheet3.getCell(`D${cfoRow}`).value = `= Autokonsumpcja × 0.7 t/MWh`;
  sheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  const esgCo2TotalRow = cfoRow;  // Store for decision summary formulas
  sheet3.getCell(`B${cfoRow}`).value = `🌍 Redukcja CO₂ (${analysisPeriod} lat) [tony]`;
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: esgCo2TotalFormula, result: roundNum(totalCO2Tons, 0) }
    : roundNum(totalCO2Tons, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  sheet3.getCell(`D${cfoRow}`).value = 'Całkowity wpływ projektu';
  sheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '🚗 Ekwiwalent samochodów (rocznie)';
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: esgCarsFormula, result: roundNum(annualCO2Tons / 4.6, 0) }
    : roundNum(annualCO2Tons / 4.6, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  sheet3.getCell(`D${cfoRow}`).value = 'Roczna emisja tylu aut osobowych';
  sheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '🌳 Ekwiwalent drzew';
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: esgTreesFormula, result: roundNum(annualCO2Tons / 0.022, 0) }
    : roundNum(annualCO2Tons / 0.022, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  sheet3.getCell(`D${cfoRow}`).value = 'Drzew pochłaniających CO₂';
  sheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '✈️ Ekwiwalent lotów WAW-LON';
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: esgFlightsFormula, result: roundNum(annualCO2Tons / 0.255, 0) }
    : roundNum(annualCO2Tons / 0.255, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  sheet3.getCell(`D${cfoRow}`).value = 'Lotów w klasie ekonomicznej';
  sheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  // --- SECTION 5: BREAK-EVEN ---
  const breakEvenPrice = lcoeValue;
  const safetyMarginPct = (effectiveEnergyPrice - lcoeValue) / effectiveEnergyPrice;

  // Break-even formulas
  const bePriceFormula = `${s2}F12`;
  const beLcoeFormula = kpiLcoeFormula;
  const beMarginFormula = `(${s2}F12-${kpiLcoeFormula})/${s2}F12`;

  cfoRow += 2;
  sheet3.mergeCells(`B${cfoRow}:H${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = 'ANALIZA BREAK-EVEN';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FFE65100' } };
  sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = 'Przy jakiej cenie energii inwestycja przestaje się opłacać?';
  sheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };

  cfoRow++;
  const bePriceRow = cfoRow;
  sheet3.getCell(`B${cfoRow}`).value = isRdn ? 'Efektywna cena RDN (TCSL/MWh)' : 'Obecna cena energii z sieci';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = isRdn
    ? roundNum(effectiveEnergyPrice, 0)
    : (withFormulas ? { formula: bePriceFormula, result: roundNum(totalEnergyPrice, 0) } : roundNum(totalEnergyPrice, 0));
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet3.getCell(`D${cfoRow}`).value = 'PLN/MWh';

  cfoRow++;
  const beLcoeRow = cfoRow;
  sheet3.getCell(`B${cfoRow}`).value = 'LCOE instalacji PV';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: beLcoeFormula, result: roundNum(lcoeValue, 0) }
    : roundNum(lcoeValue, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet3.getCell(`D${cfoRow}`).value = 'PLN/MWh';

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '⚠️ BREAK-EVEN: Min. cena sieci';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: `C${beLcoeRow}`, result: roundNum(breakEvenPrice, 0) }
    : roundNum(breakEvenPrice, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FFE65100' }, size: 12 };
  sheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };
  sheet3.getCell(`D${cfoRow}`).value = 'PLN/MWh';

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '🛡️ Margines bezpieczeństwa';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: `(C${bePriceRow}-C${beLcoeRow})/C${bePriceRow}`, result: safetyMarginPct > 0 ? safetyMarginPct : 0 }
    : (safetyMarginPct > 0 ? safetyMarginPct : 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '0%';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: safetyMarginPct > 0.3 ? { argb: 'FF2E7D32' } : { argb: 'FFE65100' }, size: 12 };
  sheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: safetyMarginPct > 0.3 ? 'FFE8F5E9' : 'FFFFF3E0' } };
  sheet3.getCell(`D${cfoRow}`).value = '%';

  cfoRow++;
  if (safetyMarginPct <= 0) {
    sheet3.getCell(`B${cfoRow}`).value = `Jeśli cena energii spadnie poniżej ${roundNum(lcoeValue, 0)} PLN/MWh, inwestycja nie jest opłacalna.`;
    sheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FFE65100' } };
  }

  // --- SECTION 6: ANALIZA SCENARIUSZY ---
  cfoRow += 2;
  sheet3.mergeCells(`B${cfoRow}:H${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = 'ANALIZA SCENARIUSZY';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF5E35B1' } };
  sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEDE7F6' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = 'Projekcja NPV przy różnych założeniach:';
  sheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };

  // Scenario table header
  cfoRow += 2;
  const scenarioHeaders = ['Scenariusz', 'Cena sieci', 'Yield PV', 'NPV [tys. PLN]', 'Prawdop.', 'Ważona'];
  scenarioHeaders.forEach((h, i) => {
    sheet3.getCell(cfoRow, 2 + i).value = h;
    sheet3.getCell(cfoRow, 2 + i).font = { bold: true, size: 10 };
    sheet3.getCell(cfoRow, 2 + i).alignment = { horizontal: 'center' };
    sheet3.getCell(cfoRow, 2 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  // Scenario data
  const scenarios = [
    { name: '⛔ Pesymistyczny', priceChg: -0.15, yieldChg: -0.10, prob: 0.15, color: 'FFFFCDD2', textColor: 'FFC62828' },
    { name: '🔵 Bazowy', priceChg: 0, yieldChg: 0, prob: 0.50, color: 'FFE3F2FD', textColor: 'FF1565C0' },
    { name: '🟢 Optymistyczny', priceChg: 0.15, yieldChg: 0.05, prob: 0.25, color: 'FFE8F5E9', textColor: 'FF2E7D32' },
    { name: '🔥 Boom energetyczny', priceChg: 0.30, yieldChg: 0, prob: 0.10, color: 'FFFFF3E0', textColor: 'FFE65100' }
  ];

  let weightedNpvSum = 0;
  const scenarioStartRow = cfoRow + 1;
  scenarios.forEach((s, idx) => {
    cfoRow++;
    const scenarioNpv = (baseNpvTys + (investment / 1000)) * (1 + s.priceChg) * (1 + s.yieldChg) - (investment / 1000);
    const weightedNpv = scenarioNpv * s.prob;
    weightedNpvSum += weightedNpv;

    // Scenario NPV formula: (NPV*1000 + CAPEX) * priceMultiplier * yieldMultiplier - CAPEX
    const priceMultiplier = (1 + s.priceChg).toFixed(2);
    const yieldMultiplier = (1 + s.yieldChg).toFixed(2);
    const scenarioNpvFormula = `(${s2}M${lastDataRow}*1000+${s2}F10)*${priceMultiplier}*${yieldMultiplier}-${s2}F10`;

    sheet3.getCell(`B${cfoRow}`).value = s.name;
    sheet3.getCell(`B${cfoRow}`).font = { bold: true, color: { argb: s.textColor } };
    sheet3.getCell(`C${cfoRow}`).value = `${s.priceChg >= 0 ? '+' : ''}${(s.priceChg * 100).toFixed(0)}%`;
    sheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };
    sheet3.getCell(`D${cfoRow}`).value = `${s.yieldChg >= 0 ? '+' : ''}${(s.yieldChg * 100).toFixed(0)}%`;
    sheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };

    // NPV for scenario with formula
    sheet3.getCell(`E${cfoRow}`).value = withFormulas
      ? { formula: scenarioNpvFormula, result: roundNum(scenarioNpv, 0) }
      : roundNum(scenarioNpv, 0);
    sheet3.getCell(`E${cfoRow}`).numFmt = '# ##0';
    sheet3.getCell(`E${cfoRow}`).font = { bold: true, color: { argb: s.textColor } };
    sheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };

    sheet3.getCell(`F${cfoRow}`).value = s.prob;
    sheet3.getCell(`F${cfoRow}`).numFmt = '0%';
    sheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };

    // Weighted NPV = NPV * probability
    sheet3.getCell(`G${cfoRow}`).value = withFormulas
      ? { formula: `E${cfoRow}*F${cfoRow}`, result: roundNum(weightedNpv, 0) }
      : roundNum(weightedNpv, 0);
    sheet3.getCell(`G${cfoRow}`).numFmt = '# ##0';
    sheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };

    // Row background
    for (let c = 2; c <= 7; c++) {
      sheet3.getRow(cfoRow).getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: s.color } };
      sheet3.getRow(cfoRow).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });

  // Weighted NPV total
  const scenarioEndRow = cfoRow;
  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '⚖️ WARTOŚĆ OCZEKIWANA NPV';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  sheet3.getCell(`E${cfoRow}`).value = 'Suma ważona scenariuszy';
  sheet3.getCell(`E${cfoRow}`).font = { italic: true, size: 9 };
  sheet3.getCell(`G${cfoRow}`).value = withFormulas
    ? { formula: `SUM(G${scenarioStartRow}:G${scenarioEndRow})`, result: roundNum(weightedNpvSum, 0) }
    : roundNum(weightedNpvSum, 0);
  sheet3.getCell(`G${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`G${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  sheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`H${cfoRow}`).value = 'tys. PLN';
  for (let c = 2; c <= 8; c++) {
    sheet3.getRow(cfoRow).getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
  }

  // --- SECTION 7: WRAŻLIWOŚĆ NA INFLACJĘ ---
  cfoRow += 3;
  sheet3.mergeCells(`B${cfoRow}:H${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = 'WRAŻLIWOŚĆ NA INFLACJĘ CEN ENERGII';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF00838F' } };
  sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0F7FA' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = 'Jak zmienia się NPV przy różnej inflacji cen energii:';
  sheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };

  cfoRow += 2;
  const inflationRates = [0, 0.02, 0.03, 0.05, 0.07, 0.10];
  sheet3.getCell(`B${cfoRow}`).value = 'Roczna inflacja cen energii';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  inflationRates.forEach((ir, i) => {
    sheet3.getCell(cfoRow, 3 + i).value = `${(ir * 100).toFixed(0)}%`;
    sheet3.getCell(cfoRow, 3 + i).font = { bold: true };
    sheet3.getCell(cfoRow, 3 + i).alignment = { horizontal: 'center' };
    sheet3.getCell(cfoRow, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = 'NPV [tys. PLN]';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  inflationRates.forEach((ir, i) => {
    // Higher energy price inflation = higher future savings = higher NPV
    // Approximate: NPV increases by ~period/2 * inflationRate relative multiplier
    const inflationMultiplier = 1 + (ir - inflationRate) * analysisPeriod * 0.4;
    const adjNpv = baseNpvTys * inflationMultiplier;

    // Formula: NPV * (1 + (ir - baseInflation) * period * 0.4)
    const inflMultiplierVal = inflationMultiplier.toFixed(3);
    const inflNpvFormula = `${s2}M${lastDataRow}*1000*${inflMultiplierVal}`;

    const cell = sheet3.getCell(cfoRow, 3 + i);
    cell.value = withFormulas
      ? { formula: inflNpvFormula, result: roundNum(adjNpv, 0) }
      : roundNum(adjNpv, 0);
    cell.numFmt = '# ##0';
    cell.font = { bold: true };
    cell.alignment = { horizontal: 'center' };

    // Highlight base case (3% = current inflation)
    if (ir === inflationRate || (ir === 0.03 && inflationRate > 0.02 && inflationRate < 0.04)) {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
      cell.font = { bold: true, color: { argb: 'FF1565C0' } };
    } else if (adjNpv > baseNpvTys * 1.1) {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
      cell.font = { bold: true, color: { argb: 'FF2E7D32' } };
    }
  });

  // --- SECTION 8: PODSUMOWANIE DECYZJI - CAPEX vs STATUS QUO ---
  cfoRow += 3;
  sheet3.mergeCells(`B${cfoRow}:H${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = 'PODSUMOWANIE DECYZJI - CAPEX vs STATUS QUO';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

  cfoRow += 2;
  // Decision table header
  const decisionHeaders = ['Kryterium', 'Inwestycja CAPEX', 'Status Quo', 'Wygrywa'];
  decisionHeaders.forEach((h, i) => {
    sheet3.getCell(cfoRow, 2 + i).value = h;
    sheet3.getCell(cfoRow, 2 + i).font = { bold: true };
    sheet3.getCell(cfoRow, 2 + i).alignment = { horizontal: 'center' };
    sheet3.getCell(cfoRow, 2 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  // Calculate 30-year grid cost without PV
  const gridCost30Years = isRdn
    ? rdnGridCostYear1Tys * analysisPeriod  // RDN: use real annual cost from TCSL
    : baseAutoconsumptionMwh * totalEnergyPrice * analysisPeriod / 1000; // tys. PLN (simplified)

  // Decision criteria — with formula support for dynamic rows
  const decisionRows = [
    { criterion: 'Nakład inwestycyjny', capex: `${roundNum(investment / 1000, 0)} tys. PLN`, statusQuo: '0 PLN', winner: 'Status Quo', useFormula: true, formulaType: 'investment' },
    { criterion: `Koszt energii ${analysisPeriod} lat`, capex: '0 tys.', statusQuo: `${roundNum(gridCost30Years, 0)} tys.`, winner: 'CAPEX', useFormula: true, formulaType: 'energyCost' },
    { criterion: `Oszczędności ${analysisPeriod} lat`, capex: `${roundNum(totalSavings / 1000, 0)} tys. PLN`, statusQuo: '0 PLN', winner: 'CAPEX', useFormula: true, formulaType: 'savings' },
    { criterion: 'NPV (wartość bieżąca)', capex: `${roundNum(npvValue / 1000, 0)} tys. PLN`, statusQuo: '0 PLN', winner: npvValue > 0 ? 'CAPEX' : 'Status Quo', useFormula: true, formulaType: 'npv' },
    { criterion: 'Ryzyko cenowe', capex: 'Częściowe zabezp.', statusQuo: '100% ekspozycji', winner: 'CAPEX', useFormula: false },
    { criterion: 'Własność aktywów', capex: 'TAK', statusQuo: 'NIE', winner: 'CAPEX', useFormula: false },
    { criterion: 'Zielona energia', capex: 'TAK', statusQuo: 'NIE', winner: 'CAPEX', useFormula: false },
    { criterion: `Redukcja CO₂ (${analysisPeriod} lat)`, capex: `${roundNum(totalCO2Tons, 0)} ton`, statusQuo: '0 ton', winner: 'CAPEX', useFormula: true, formulaType: 'co2' }
  ];

  const capexDecisionFirstRow = cfoRow + 1;
  let capexWins = 0;
  decisionRows.forEach(row => {
    cfoRow++;
    sheet3.getCell(`B${cfoRow}`).value = row.criterion;
    sheet3.getCell(`B${cfoRow}`).font = { color: { argb: 'FF424242' } };

    // C column (CAPEX value) — formulas matching reference ROUND pattern
    if (withFormulas && row.useFormula) {
      if (row.formulaType === 'investment') {
        sheet3.getCell(`C${cfoRow}`).value = { formula: `ROUND(${s2}F10,0)\n&" tys. PLN"`, result: row.capex };
      } else if (row.formulaType === 'savings') {
        sheet3.getCell(`C${cfoRow}`).value = {
          formula: `ROUND(\n  SUM(${s2}L${dataStartRow}:${s2}L${lastDataRow}),\n  0)\n&" tys. PLN"`,
          result: row.capex
        };
      } else if (row.formulaType === 'npv') {
        sheet3.getCell(`C${cfoRow}`).value = {
          formula: `ROUND(\n  ${s2}M${lastDataRow}*1000,\n  0)\n&" tys. PLN"`,
          result: row.capex
        };
      } else if (row.formulaType === 'co2') {
        sheet3.getCell(`C${cfoRow}`).value = {
          formula: `ROUND(\n  SUM(${s2}I${dataStartRow}:${s2}I${lastDataRow})*0.7,\n  0)\n&" ton"`,
          result: row.capex
        };
      } else {
        sheet3.getCell(`C${cfoRow}`).value = row.capex;
      }
    } else {
      sheet3.getCell(`C${cfoRow}`).value = row.capex;
    }
    sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
    sheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };

    // D column (Status Quo value) — formulas when applicable
    if (withFormulas && row.useFormula && row.formulaType === 'energyCost') {
      sheet3.getCell(`D${cfoRow}`).value = {
        formula: `ROUND(\n  ${s2}F12*${s2}F9,\n  0)\n&" tys."`,
        result: row.statusQuo
      };
    } else {
      sheet3.getCell(`D${cfoRow}`).value = row.statusQuo;
    }
    sheet3.getCell(`D${cfoRow}`).font = { color: { argb: 'FFC62828' } };
    sheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };

    // E column (Winner) — formulas when applicable
    if (withFormulas && row.useFormula) {
      if (row.formulaType === 'investment') {
        sheet3.getCell(`E${cfoRow}`).value = { formula: `IF(${s2}F10>0,\n  "Status Quo","Remis")`, result: row.winner };
      } else if (row.formulaType === 'energyCost') {
        sheet3.getCell(`E${cfoRow}`).value = {
          formula: `IF(\n  SUM(${s2}F${dataStartRow}:${s2}F${lastDataRow})>0,\n  "CAPEX","Status Quo")`,
          result: row.winner
        };
      } else if (row.formulaType === 'savings') {
        sheet3.getCell(`E${cfoRow}`).value = {
          formula: `IF(\n  SUM(${s2}L${dataStartRow}:${s2}L${lastDataRow})>0,\n  "CAPEX","Status Quo")`,
          result: row.winner
        };
      } else if (row.formulaType === 'npv') {
        sheet3.getCell(`E${cfoRow}`).value = { formula: `IF(${s2}M${lastDataRow}>0,\n  "CAPEX","Status Quo")`, result: row.winner };
      } else if (row.formulaType === 'co2') {
        sheet3.getCell(`E${cfoRow}`).value = { formula: `IF($C$${esgCo2TotalRow}>0,\n  "CAPEX","Status Quo")`, result: row.winner };
      } else {
        sheet3.getCell(`E${cfoRow}`).value = row.winner;
      }
    } else {
      sheet3.getCell(`E${cfoRow}`).value = row.winner;
    }
    sheet3.getCell(`E${cfoRow}`).font = { bold: true, color: { argb: row.winner === 'CAPEX' ? 'FF2E7D32' : 'FFE65100' } };
    sheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };

    if (row.winner === 'CAPEX') capexWins++;

    for (let c = 2; c <= 5; c++) {
      sheet3.getRow(cfoRow).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });
  const capexDecisionLastRow = cfoRow;

  // Final recommendation — dynamic COUNTIF formula
  cfoRow += 2;
  const recommendation = capexWins >= 5 ? 'CAPEX' : 'Status Quo';
  sheet3.mergeCells(`B${cfoRow}:E${cfoRow}`);
  if (withFormulas) {
    const eRange = `E${capexDecisionFirstRow}:E${capexDecisionLastRow}`;
    const nCrit = decisionRows.length;
    sheet3.getCell(`B${cfoRow}`).value = {
      formula: `IF(\n  COUNTIF(${eRange},"CAPEX")\n  > COUNTIF(${eRange},"Status Quo"),\n  "✅ REKOMENDACJA: Inwestycja CAPEX - wygrywa w "\n  & COUNTIF(${eRange},"CAPEX")\n  & " z ${nCrit} kryteriów",\n  "⛔ REKOMENDACJA: Status Quo - wygrywa w "\n  & COUNTIF(${eRange},"Status Quo")\n  & " z ${nCrit} kryteriów")`,
      result: `✅ REKOMENDACJA: Inwestycja CAPEX - wygrywa w ${capexWins} z ${nCrit} kryteriów`
    };
  } else {
    sheet3.getCell(`B${cfoRow}`).value = `✅ REKOMENDACJA: Inwestycja CAPEX - wygrywa w ${capexWins} z ${decisionRows.length} kryteriów`;
  }
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: recommendation === 'CAPEX' ? 'FF2E7D32' : 'FFC62828' } };
  sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: recommendation === 'CAPEX' ? 'FFE8F5E9' : 'FFFFEBEE' } };
  sheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'center' };

  cfoRow++;
  sheet3.mergeCells(`B${cfoRow}:E${cfoRow}`);
  if (withFormulas) {
    sheet3.getCell(`B${cfoRow}`).value = {
      formula: `"NPV = "\n&ROUND(${s2}M${lastDataRow}*1000,0)\n&" tys. PLN | IRR = "\n&ROUND(${kpiIrrFormula}*100,0)\n&"% | Zwrot = "\n&FIXED(${kpiPaybackFormula},1)\n&" lat"`,
      result: `NPV = ${roundNum(npvValue / 1000, 0)} tys. PLN | IRR = ${roundNum(irrValue * 100, 1)}% | Zwrot = ${roundNum(simplePaybackValue, 1)} lat`
    };
  } else {
    sheet3.getCell(`B${cfoRow}`).value = `NPV = ${roundNum(npvValue / 1000, 0)} tys. PLN | IRR = ${roundNum(irrValue * 100, 1)}% | Zwrot = ${roundNum(simplePaybackValue, 1)} lat`;
  }
  sheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FF1565C0' } };
  sheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'center' };

  // ========== ADD ENGLISH SHEETS ==========
  // Sheet 4: CAPEX Summary (ENG)
  const sheet4 = workbook.addWorksheet('CAPEX Summary');
  sheet4.columns = [
    { width: 5 },
    { width: 35 },
    { width: 18 }
  ];
  sheet4.views = [{ showGridLines: false, showRowColHeaders: false }];

  sheet4.getRow(1).height = 20;
  sheet4.getRow(2).height = 20;
  sheet4.getRow(3).height = 24;

  sheet4.mergeCells('B1:C3');
  const rdnLabelEng = window._rdnExportMode ? ' (RDN prices)' : '';
  sheet4.getCell('B1').value = `CAPEX ANALYSIS${rdnLabelEng} - Investor Perspective - Scenario ${scenarioName}`;
  sheet4.getCell('B1').font = { bold: true, size: 14, color: { argb: 'FF1565C0' } };
  sheet4.getCell('B1').alignment = { horizontal: 'center', vertical: 'bottom' };

  if (logoImageId !== null) {
    sheet4.addImage(logoImageId, {
      tl: { col: 1.3, row: 0.1 },
      ext: { width: 200, height: 50 }
    });
  }

  const summaryRowsEng = [
    ['', ''],
    ['INSTALLATION DATA', ''],
    ['System capacity [kWp]:', capacityKwp],
    ['Annual facility consumption [MWh]:', roundNum(annualConsumptionMwh, 1)],
    ['PV self-consumption [MWh/year]:', roundNum(baseAutoconsumptionMwh, 1)],
    ['Consumption coverage [%]:', roundNum((baseAutoconsumptionMwh / annualConsumptionMwh) * 100, 1)],
    ['', ''],
    ['INVESTMENT PARAMETERS', ''],
    ['CAPEX [k PLN]:', roundNum(investment / 1000, 0)],
    ['CAPEX [PLN/kWp]:', roundNum(investment / capacityKwp, 0)],
    ['Analysis period [years]:', analysisPeriod],
    ['Discount rate [%]:', roundNum(discountRate * 100, 1)],
    ['Inflation [%]:', roundNum(inflationRate * 100, 1)],
    ['', ''],
    ['DEGRADATION', ''],
    ['PV degradation year 1 [%]:', roundNum(pvDegradationYear1 * 100, 1)],
    ['PV degradation years 2+ [%/year]:', roundNum(pvDegradationYears2Plus * 100, 2)],
    ['BESS degradation [%/year]:', roundNum(bessDegradationRate * 100, 1)],
    ['', ''],
    ['ECONOMIC RESULTS', ''],
  ];

  if (withFormulas) {
    summaryRowsEng.push(['NPV [M PLN]:', { formula: "'CAPEX Year by Year'!M" + lastDataRow }, '0.00']);
    summaryRowsEng.push(['IRR [%]:', roundNum(centralizedCalc.capex.irr * 100, 1), '0.0']);
    summaryRowsEng.push(['ROI [%]:', { formula: "(SUM('CAPEX Year by Year'!L" + dataStartRow + ":L" + lastDataRow + ")*1000-'CAPEX Year by Year'!F10*1000)/('CAPEX Year by Year'!F10*1000)*100" }, '0.0']);
    summaryRowsEng.push(['Simple payback [years]:', { formula: "'CAPEX Year by Year'!F10*1000/AVERAGE('CAPEX Year by Year'!L" + dataStartRow + ":L" + (dataStartRow + 4) + ")/1000" }, '0.0']);
  } else {
    summaryRowsEng.push(['NPV [M PLN]:', roundNum(centralizedCalc.capex.npv / 1000000, 2), '0.00']);
    summaryRowsEng.push(['IRR [%]:', roundNum(centralizedCalc.capex.irr * 100, 1), '0.0']);
    summaryRowsEng.push(['ROI [%]:', roundNum(roi, 1), '0.0']);
    summaryRowsEng.push(['Simple payback [years]:', roundNum(centralizedCalc.capex.simplePayback, 1), '0.0']);
  }
  const dppEng = centralizedCalc.capex.discountedPayback;
  summaryRowsEng.push(['Discounted payback [years]:', (dppEng !== null && dppEng !== undefined) ? roundNum(dppEng, 1) : 'Beyond analysis period', '0.0']);
  summaryRowsEng.push(['LCOE [PLN/MWh]:', roundNum(centralizedCalc.capex.lcoe, 0), '0']);

  summaryRowsEng.forEach((row, idx) => {
    const excelRow = sheet4.getRow(idx + 5);
    excelRow.getCell(2).value = row[0];
    if (typeof row[1] === 'object' && row[1].formula) {
      excelRow.getCell(3).value = row[1];
    } else {
      excelRow.getCell(3).value = row[1];
    }
    if (row[2] && typeof row[1] !== 'string') {
      excelRow.getCell(3).numFmt = row[2];
    }
    if (row[0] && (row[0].includes('INSTALLATION') || row[0].includes('INVESTMENT') || row[0] === 'DEGRADATION' || row[0].includes('ECONOMIC'))) {
      excelRow.getCell(2).font = { bold: true, color: { argb: 'FF1565C0' } };
      excelRow.getCell(2).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
      excelRow.getCell(3).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
    }
  });

  // Sheet 5: CAPEX Year by Year (ENG)
  const sheet5 = workbook.addWorksheet('CAPEX Year by Year');
  sheet5.columns = [
    { width: 3 },
    { width: 6 },
    { width: 10 },
    { width: 10 },
    { width: 12 },
    { width: 16 },
    { width: 12 },
    { width: 12 },
    { width: 12 },
    { width: 16 },
    { width: 14 },
    { width: 16 },
    { width: 16 }
  ];

  sheet5.views = [{ showGridLines: false, showRowColHeaders: false }];

  sheet5.getRow(1).height = 22;
  sheet5.getCell('B1').value = `CAPEX${rdnLabelEng} YEAR BY YEAR ANALYSIS WITH NPV - Scenario ${scenarioName}`;
  sheet5.getCell('B1').font = { bold: true, size: 14, color: { argb: 'FF1565C0' } };

  if (logoImageId !== null) {
    sheet5.addImage(logoImageId, {
      tl: { col: 17, row: 0.3 },
      ext: { width: 180, height: 45 }
    });
  }

  const baseOpexTysPlnEng = cashFlows.length > 0 ? cashFlows[0].opex / 1000 : 0;

  const paramDataEng = [
    { row: 3, label: 'PARAMETERS:', value: null, numFmt: null, isHeader: true },
    { row: 4, label: 'Discount rate:', value: discountRate, numFmt: '0.00%' },
    { row: 5, label: 'Inflation:', value: inflationRate, numFmt: '0.00%' },
    { row: 6, label: 'PV Degradation Year 1:', value: pvDegradationYear1, numFmt: '0.00%' },
    { row: 7, label: 'PV Degradation Years 2+:', value: pvDegradationYears2Plus, numFmt: '0.00%' },
    { row: 8, label: 'BESS Degradation:', value: bessDegradationRate, numFmt: '0.00%' },
    { row: 9, label: 'Analysis period [years]:', value: analysisPeriod, numFmt: '0' },
    { row: 10, label: 'CAPEX [k PLN]:', value: roundNum(investment / 1000, 2), numFmt: '# ##0.00' },
    { row: 11, label: 'Base self-consumption [MWh]:', value: roundNum(baseAutoconsumptionMwh, 2), numFmt: '# ##0.00' },
    isRdn
      ? { row: 12, label: 'RDN annual cost w/o PV Yr1 [k PLN]:', value: roundNum(rdnGridCostYear1Tys, 2), numFmt: '# ##0.00' }
      : { row: 12, label: 'Base grid price [PLN/MWh]:', value: roundNum(totalEnergyPrice, 2), numFmt: '# ##0.00' },
    { row: 13, label: 'Annual consumption [MWh]:', value: roundNum(annualConsumptionMwh, 2), numFmt: '# ##0.00' },
    { row: 14, label: 'Base OPEX [k PLN/year]:', value: roundNum(baseOpexTysPlnEng, 2), numFmt: '# ##0.00' }
  ];

  paramDataEng.forEach(p => {
    sheet5.mergeCells(`C${p.row}:E${p.row}`);
    const labelCell = sheet5.getCell(`C${p.row}`);
    labelCell.value = p.label + ' ';
    labelCell.alignment = { horizontal: 'right' };
    if (p.isHeader) {
      labelCell.font = { bold: true, color: { argb: 'FF5D4037' } };
    } else {
      labelCell.font = { color: { argb: 'FF616161' } };
    }
    labelCell.border = { bottom: { style: 'thin', color: { argb: 'FFEEEEEE' } } };

    if (p.value !== null) {
      const valueCell = sheet5.getCell(`F${p.row}`);
      valueCell.value = p.value;
      valueCell.alignment = { horizontal: 'left', indent: 1 };
      valueCell.font = { bold: true, color: { argb: 'FF1976D2' } };
      valueCell.border = { bottom: { style: 'thin', color: { argb: 'FFEEEEEE' } } };
      if (p.numFmt) {
        valueCell.numFmt = p.numFmt;
      }
    }
  });

  // Header row (row 16)
  const headersEng = ['Year', 'PV Deg [%]', 'BESS Deg [%]', 'Consump. [MWh]', isRdn ? 'RDN Cost [k]' : 'Grid Cost [k]',
    'Self PV [MWh]', 'Self BESS [MWh]', 'Total Self [MWh]', isRdn ? 'RDN Savings [k]' : 'Grid Equiv. [k]',
    'OPEX [k]', 'Savings [k]', 'Cumul. NPV [M]'];
  const headerRowEng = sheet5.getRow(16);
  headerRowEng.height = 40;
  headersEng.forEach((h, i) => {
    const cell = headerRowEng.getCell(i + 2);
    cell.value = h;
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF37474F' } };
    cell.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 9 };
    cell.alignment = { horizontal: 'center', vertical: 'middle', wrapText: true };
    cell.border = {
      top: { style: 'thin', color: { argb: 'FF263238' } },
      bottom: { style: 'thin', color: { argb: 'FF263238' } }
    };
  });

  // Year 0 - Initial investment (row 17)
  const year0RowEng = sheet5.getRow(17);
  year0RowEng.getCell(2).value = 0;
  year0RowEng.getCell(12).value = roundNum(-investment / 1000, 0);
  year0RowEng.getCell(12).numFmt = '# ##0';
  year0RowEng.getCell(12).alignment = { horizontal: 'right', indent: 1 };
  year0RowEng.getCell(13).value = roundNum(-investment / 1000000, 2);
  year0RowEng.getCell(13).numFmt = '# ##0.00';
  year0RowEng.getCell(13).alignment = { horizontal: 'right', indent: 1 };
  year0RowEng.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFEBEE' } };

  // Data rows (years 1-N)
  let cumulativeNPVEng = -investment;
  for (let i = 0; i < cashFlows.length; i++) {
    const cf = cashFlows[i];
    const year = cf.year;
    const row = sheet5.getRow(17 + year);
    const dataRowEng = 17 + year;

    const pvDeg = year === 1 ? (1 - pvDegradationYear1) : (1 - pvDegradationYear1) * Math.pow(1 - pvDegradationYears2Plus, year - 1);
    const bessDeg = Math.pow(1 - bessDegradationRate, year);
    const savingsInflFactor = useInflation ? Math.pow(1 + inflationRate, year - 1) : 1;  // grid cost + savings: year-1
    const autoPvMwh = baseAutoconsumptionMwh * pvDeg;
    const autoBessMwh = (cf.selfConsumedBess || 0) / 1000;
    const sumaAutoMwh = autoPvMwh + autoBessMwh;
    const discountedCF = cf.net_cash_flow / Math.pow(1 + discountRate, year);
    cumulativeNPVEng += discountedCF;

    if (withFormulas) {
      row.getCell(2).value = year;
      if (year === 1) {
        row.getCell(3).value = { formula: '1-$F$6', result: pvDeg };
      } else {
        row.getCell(3).value = { formula: '(1-$F$6)*POWER(1-$F$7,' + (year - 1) + ')', result: pvDeg };
      }
      row.getCell(3).numFmt = '0.0%';
      row.getCell(4).value = { formula: 'POWER(1-$F$8,' + year + ')', result: bessDeg };
      row.getCell(4).numFmt = '0.0%';
      row.getCell(5).value = { formula: '$F$13', result: annualConsumptionMwh };
      row.getCell(5).numFmt = numFmtStandard;
      row.getCell(5).alignment = { horizontal: 'right', indent: 1 };
      // Grid cost EN — CPI^(year-1): year 1 = base price, year 2+ escalated
      if (isRdn) {
        const gridCpiPart = useInflation ? '*POWER(1+$F$5,' + (year - 1) + ')' : '';
        row.getCell(6).value = { formula: '$F$12' + gridCpiPart, result: rdnGridCostYear1Tys * savingsInflFactor };
      } else {
        const gridCpiPart = useInflation ? '*POWER(1+$F$5,' + (year - 1) + ')' : '';
        row.getCell(6).value = { formula: '$F$13*$F$12' + gridCpiPart + '/1000', result: annualConsumptionMwh * totalEnergyPrice * savingsInflFactor / 1000 };
      }
      row.getCell(6).numFmt = numFmtStandard;
      row.getCell(6).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(7).value = { formula: '$F$11*C' + dataRowEng, result: autoPvMwh };
      row.getCell(7).numFmt = numFmtStandard;
      row.getCell(7).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(8).value = autoBessMwh > 0 ? roundNum(autoBessMwh, 2) : 0;
      row.getCell(8).numFmt = numFmtStandard;
      row.getCell(8).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(9).value = { formula: 'G' + dataRowEng + '+H' + dataRowEng, result: sumaAutoMwh };
      row.getCell(9).numFmt = numFmtStandard;
      row.getCell(9).alignment = { horizontal: 'right', indent: 1 };
      // Savings EN — CPI^(year-1): year 1 = base price
      if (isRdn) {
        row.getCell(10).value = roundNum(cf.savings / 1000, 2);
      } else {
        const savCpiPart = useInflation ? '*POWER(1+$F$5,' + (year - 1) + ')' : '';
        row.getCell(10).value = { formula: 'I' + dataRowEng + '*$F$12' + savCpiPart + '/1000', result: cf.savings / 1000 };
      }
      row.getCell(10).numFmt = numFmtStandard;
      row.getCell(10).alignment = { horizontal: 'right', indent: 1 };
      // OPEX EN - formula with inflation: base OPEX * (1+inflation)^year (always applied)
      row.getCell(11).value = { formula: '$F$14*POWER(1+$F$5,' + year + ')', result: cf.opex / 1000 };
      row.getCell(11).numFmt = numFmtStandard;
      row.getCell(11).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(12).value = { formula: 'J' + dataRowEng + '-K' + dataRowEng, result: cf.net_cash_flow / 1000 };
      row.getCell(12).numFmt = numFmtStandard;
      row.getCell(12).alignment = { horizontal: 'right', indent: 1 };
      if (year === 1) {
        row.getCell(13).value = { formula: 'M17+L' + dataRowEng + '/POWER(1+$F$4,' + year + ')/1000', result: cumulativeNPVEng / 1000000 };
      } else {
        row.getCell(13).value = { formula: 'M' + (dataRowEng - 1) + '+L' + dataRowEng + '/POWER(1+$F$4,' + year + ')/1000', result: cumulativeNPVEng / 1000000 };
      }
      row.getCell(13).numFmt = numFmtMln;
      row.getCell(13).alignment = { horizontal: 'right', indent: 1 };
    } else {
      row.getCell(2).value = year;
      row.getCell(3).value = pvDeg;
      row.getCell(3).numFmt = '0.0%';
      row.getCell(4).value = bessDeg;
      row.getCell(4).numFmt = '0.0%';
      row.getCell(5).value = roundNum(annualConsumptionMwh, 2);
      row.getCell(5).numFmt = numFmtStandard;
      row.getCell(5).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(6).value = isRdn
        ? roundNum(rdnGridCostYear1Tys * savingsInflFactor, 2)
        : roundNum(annualConsumptionMwh * totalEnergyPrice * savingsInflFactor / 1000, 2);
      row.getCell(6).numFmt = numFmtStandard;
      row.getCell(6).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(7).value = roundNum(autoPvMwh, 2);
      row.getCell(7).numFmt = numFmtStandard;
      row.getCell(7).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(8).value = roundNum(autoBessMwh, 2);
      row.getCell(8).numFmt = numFmtStandard;
      row.getCell(8).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(9).value = roundNum(sumaAutoMwh, 2);
      row.getCell(9).numFmt = numFmtStandard;
      row.getCell(9).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(10).value = roundNum(cf.savings / 1000, 2);
      row.getCell(10).numFmt = numFmtStandard;
      row.getCell(10).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(11).value = roundNum(cf.opex / 1000, 2);
      row.getCell(11).numFmt = numFmtStandard;
      row.getCell(11).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(12).value = roundNum(cf.net_cash_flow / 1000, 2);
      row.getCell(12).numFmt = numFmtStandard;
      row.getCell(12).alignment = { horizontal: 'right', indent: 1 };
      row.getCell(13).value = roundNum(cumulativeNPVEng / 1000000, 3);
      row.getCell(13).numFmt = numFmtMln;
      row.getCell(13).alignment = { horizontal: 'right', indent: 1 };
    }
  }

  // Conditional formatting for NPV column
  sheet5.addConditionalFormatting({
    ref: 'M17:M' + lastDataRow,
    rules: [
      {
        type: 'cellIs',
        operator: 'greaterThanOrEqual',
        formulae: [0],
        style: { font: { color: { argb: 'FF2E7D32' } }, fill: { type: 'pattern', pattern: 'solid', bgColor: { argb: 'FFE8F5E9' } } },
        priority: 1
      },
      {
        type: 'cellIs',
        operator: 'lessThan',
        formulae: [0],
        style: { font: { color: { argb: 'FFC62828' } }, fill: { type: 'pattern', pattern: 'solid', bgColor: { argb: 'FFFFEBEE' } } },
        priority: 2
      }
    ]
  });

  // DPP Row Highlighting - DYNAMIC conditional formatting (ENG)
  // Only amber top+bottom border (no fill/font change)
  sheet5.addConditionalFormatting({
    ref: 'B' + dataStartRow + ':M' + lastDataRow,
    rules: [{
      type: 'expression',
      formulae: ['AND($M' + dataStartRow + '>=0,$M' + (dataStartRow - 1) + '<0)'],
      style: {
        border: {
          top: { style: 'medium', color: { argb: 'FFFFC107' } },
          bottom: { style: 'medium', color: { argb: 'FFFFC107' } }
        }
      },
      priority: 3
    }]
  });

  sheet5.views = [{ state: 'frozen', ySplit: 16, xSplit: 0, showGridLines: false, showRowColHeaders: false }];

  // Summary section below data
  const summaryStartRowEng = lastDataRow + 3;
  sheet5.getCell('C' + summaryStartRowEng).value = 'KPI SUMMARY';
  sheet5.getCell('C' + summaryStartRowEng).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  sheet5.mergeCells('C' + summaryStartRowEng + ':H' + summaryStartRowEng);
  sheet5.getCell('C' + summaryStartRowEng).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

  const irrFormulaEng = 'IRR(L17:L' + lastDataRow + ')*100';
  const simplePaybackFormulaEng = '$F$10/(AVERAGE(L' + dataStartRow + ':L' + Math.min(dataStartRow + 4, lastDataRow) + '))';
  const _nEng = 'SUMPRODUCT((M' + dataStartRow + ':M' + lastDataRow + '<0)*1)';
  const _mRangeEng = 'M' + (dataStartRow - 1) + ':M' + lastDataRow;
  const dppFormulaEng = _nEng + '\n+ (-INDEX(' + _mRangeEng + ', ' + _nEng + ' + 1))\n/ (INDEX(' + _mRangeEng + ', ' + _nEng + ' + 2)\n   - INDEX(' + _mRangeEng + ', ' + _nEng + ' + 1))';
  // LCOE formula — EXACT from reference Excel
  const lcoeFormulaEng = '($F$10 * 1000\n + SUMPRODUCT(\n     K' + dataStartRow + ':K' + lastDataRow + '\n     / POWER(1 + $F$4,\n             B' + dataStartRow + ':B' + lastDataRow + ')))\n/ SUMPRODUCT(\n     I' + dataStartRow + ':I' + lastDataRow + '\n     / POWER(1 + $F$4,\n             B' + dataStartRow + ':B' + lastDataRow + '))';

  const kpiRowsEng = [
    ['CAPEX (investment):', withFormulas ? { formula: '$F$10' } : roundNum(investment / 1000, 2), 'k PLN', '= Initial investment', '# ##0.00'],
    ['Total savings:', withFormulas ? { formula: 'SUM(L' + dataStartRow + ':L' + lastDataRow + ')' } : roundNum(cashFlows.reduce((s, cf) => s + cf.net_cash_flow, 0) / 1000, 2), 'k PLN', '= Sum of column L', '# ##0.00'],
    ['NPV:', withFormulas ? { formula: 'M' + lastDataRow } : roundNum(centralizedCalc.capex.npv / 1000000, 3), 'M PLN', '= Net Present Value', '# ##0.000'],
    ['IRR:', withFormulas ? { formula: irrFormulaEng } : roundNum(centralizedCalc.capex.irr * 100, 2), '%', '= Internal Rate of Return', '# ##0.00'],
    ['ROI:', withFormulas ? { formula: '(F' + (summaryStartRowEng + 2) + '-F' + (summaryStartRowEng + 1) + ')/F' + (summaryStartRowEng + 1) + '*100' } : roundNum(roi, 2), '%', '= (Savings - CAPEX) / CAPEX', '# ##0.00'],
    ['Simple Payback:', withFormulas ? { formula: simplePaybackFormulaEng } : roundNum(centralizedCalc.capex.simplePayback, 2), 'years', '= CAPEX / avg annual savings', '# ##0.00'],
    ['Discounted Payback (DPP):', withFormulas ? { formula: dppFormulaEng } : (centralizedCalc.capex.discountedPayback !== null && centralizedCalc.capex.discountedPayback !== undefined ? roundNum(centralizedCalc.capex.discountedPayback, 2) : '-'), 'years', '= Year when NPV >= 0', '# ##0.00'],
    ['LCOE (energy cost):', withFormulas ? { formula: lcoeFormulaEng } : roundNum(centralizedCalc.capex.lcoe, 2), 'PLN/MWh', '= Levelized Cost of Energy', '# ##0.00']
  ];

  kpiRowsEng.forEach((kpi, idx) => {
    const row = sheet5.getRow(summaryStartRowEng + 1 + idx);
    row.getCell(3).value = kpi[0];
    row.getCell(3).font = { bold: true };
    if (typeof kpi[1] === 'object' && kpi[1].formula) {
      row.getCell(6).value = kpi[1];
    } else {
      row.getCell(6).value = kpi[1];
    }
    row.getCell(6).font = { bold: true };
    row.getCell(6).alignment = { horizontal: 'right', indent: 1 };
    if (kpi[4] && kpi[1] !== '-') {
      row.getCell(6).numFmt = kpi[4];
    }
    row.getCell(7).value = kpi[2];
    row.getCell(8).value = kpi[3];
    row.getCell(8).font = { italic: true, color: { argb: 'FF757575' } };

    if (kpi[0].includes('NPV') || kpi[0].includes('IRR')) {
      const npvVal = kpi[0].includes('NPV') ? centralizedCalc.capex.npv : centralizedCalc.capex.irr;
      if (npvVal > 0) {
        row.getCell(6).font = { bold: true, color: { argb: 'FF2E7D32' } };
        row.getCell(6).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
      }
    }
  });

  if (withFormulas) {
    // DPP note (row index 6 in kpiRowsEng)
    sheet5.getRow(summaryStartRowEng + 7).getCell(6).note = `-- Interpolated DPP\n-- n = years with negative NPV\n-- DPP = n + (-last_negative) / (first_positive - last_negative)`;
    // LCOE note (row index 7 in kpiRowsEng)
    sheet5.getRow(summaryStartRowEng + 8).getCell(6).note = `-- (CAPEX + PV_OPEX) / PV_production\n-- Levelized Cost of Energy`;

    const noteRowEng = summaryStartRowEng + 11;
    sheet5.getCell('C' + noteRowEng).value = 'NOTE: Change parameters in cells F4:F14 to see impact on results.';
    sheet5.getCell('C' + noteRowEng).font = { italic: true, color: { argb: 'FF666666' } };
    sheet5.getCell('C' + (noteRowEng + 1)).value = 'All calculations in columns C-M contain Excel formulas.';
    sheet5.getCell('C' + (noteRowEng + 1)).font = { italic: true, color: { argb: 'FF666666' } };
  }

  // Sheet 6: CFO Analysis (ENG)
  const sheet6 = workbook.addWorksheet('CFO Analysis');
  sheet6.columns = [
    { width: 3 },
    { width: 32 },
    { width: 18 },
    { width: 16 },
    { width: 16 },
    { width: 16 },
    { width: 16 },
    { width: 18 }
  ];
  sheet6.views = [{ showGridLines: false, showRowColHeaders: false }];

  const s5 = "'CAPEX Year by Year'!";

  sheet6.mergeCells('B1:H1');
  sheet6.getCell('B1').value = `CFO ANALYSIS - CAPEX Model (Investor) - Scenario ${scenarioName}`;
  sheet6.getCell('B1').font = { bold: true, size: 16, color: { argb: 'FF1565C0' } };
  sheet6.getCell('B1').alignment = { horizontal: 'center', vertical: 'middle' };

  if (logoImageId !== null) {
    sheet6.addImage(logoImageId, {
      tl: { col: 7.2, row: 0.1 },
      ext: { width: 200, height: 50 }
    });
  }

  sheet6.mergeCells('B2:H2');
  sheet6.getCell('B2').value = `Investor perspective - analysis period: ${analysisPeriod} years`;
  sheet6.getCell('B2').font = { italic: true, size: 11, color: { argb: 'FF616161' } };
  sheet6.getCell('B2').alignment = { horizontal: 'center', vertical: 'middle' };

  // MODEL PARAMETERS
  let cfoRowEng = 4;
  sheet6.mergeCells(`B${cfoRowEng}:H${cfoRowEng}`);
  sheet6.getCell(`B${cfoRowEng}`).value = 'MODEL PARAMETERS';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 11, color: { argb: 'FF5D4037' } };
  sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEFEBE9' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'CAPEX [k PLN]';
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}F10`, result: roundNum(investment / 1000, 0) }
    : roundNum(investment / 1000, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`D${cfoRowEng}`).value = 'Analysis period [years]';
  sheet6.getCell(`E${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}F9`, result: analysisPeriod }
    : analysisPeriod;
  sheet6.getCell(`E${cfoRowEng}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet6.getCell(`F${cfoRowEng}`).value = 'Discount rate';
  sheet6.getCell(`G${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}F4`, result: discountRate }
    : discountRate;
  sheet6.getCell(`G${cfoRowEng}`).numFmt = '0.0%';
  sheet6.getCell(`G${cfoRowEng}`).font = { bold: true };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'Self-consumption [MWh/year]';
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}F11`, result: roundNum(baseAutoconsumptionMwh, 1) }
    : roundNum(baseAutoconsumptionMwh, 1);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0.0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`D${cfoRowEng}`).value = isRdn ? 'Eff. RDN price [PLN/MWh]' : 'Energy price [PLN/MWh]';
  sheet6.getCell(`E${cfoRowEng}`).value = isRdn
    ? roundNum(effectiveEnergyPrice, 0)
    : (withFormulas ? { formula: `${s5}F12`, result: roundNum(totalEnergyPrice, 0) } : roundNum(totalEnergyPrice, 0));
  sheet6.getCell(`E${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`E${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`F${cfoRowEng}`).value = 'Inflation';
  sheet6.getCell(`G${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}F5`, result: inflationRate }
    : inflationRate;
  sheet6.getCell(`G${cfoRowEng}`).numFmt = '0.0%';
  sheet6.getCell(`G${cfoRowEng}`).font = { bold: true };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'PV Degradation Year 1';
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}F6`, result: pvDegradationYear1 }
    : pvDegradationYear1;
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '0.0%';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`D${cfoRowEng}`).value = 'PV Degradation Years 2+';
  sheet6.getCell(`E${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}F7`, result: pvDegradationYears2Plus }
    : pvDegradationYears2Plus;
  sheet6.getCell(`E${cfoRowEng}`).numFmt = '0.00%';
  sheet6.getCell(`E${cfoRowEng}`).font = { bold: true };

  // KEY KPIs FOR MANAGEMENT
  cfoRowEng += 2;
  const kpiSectionRowEng = cfoRowEng;
  sheet6.mergeCells(`B${cfoRowEng}:H${cfoRowEng}`);
  sheet6.getCell(`B${cfoRowEng}`).value = `KEY KPIs FOR MANAGEMENT (${analysisPeriod} years analysis)`;
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 12, color: { argb: 'FF2E7D32' } };
  sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  const kpiCapexFormulaEng = `${s5}F10`;
  const kpiSavingsFormulaEng = `SUM(${s5}L${dataStartRow}:${s5}L${lastDataRow})`;
  const kpiNpvFormulaEng = `${s5}M${lastDataRow}`;
  const kpiIrrFormulaEng = `IRR(${s5}L17:${s5}L${lastDataRow})`;
  const kpiRoiFormulaEng = `(SUM(${s5}L${dataStartRow}:${s5}L${lastDataRow})-${s5}F10)/${s5}F10`;
  const kpiPaybackFormulaEng = `${s5}F10/AVERAGE(${s5}L${dataStartRow}:${s5}L${Math.min(dataStartRow + 4, lastDataRow)})`;
  const _nCfoEng = `SUMPRODUCT((${s5}M${dataStartRow}:${s5}M${lastDataRow}<0)*1)`;
  const _mCfoEng = `${s5}M${dataStartRow - 1}:${s5}M${lastDataRow}`;
  const kpiDppFormulaEng = `${_nCfoEng}+(-INDEX(${_mCfoEng},${_nCfoEng}+1))/(INDEX(${_mCfoEng},${_nCfoEng}+2)-INDEX(${_mCfoEng},${_nCfoEng}+1))`;
  const kpiLcoeFormulaEng = `(${s5}F10*1000+SUMPRODUCT(${s5}K${dataStartRow}:${s5}K${lastDataRow}/POWER(1+${s5}F4,${s5}B${dataStartRow}:${s5}B${lastDataRow})))/SUMPRODUCT(${s5}I${dataStartRow}:${s5}I${lastDataRow}/POWER(1+${s5}F4,${s5}B${dataStartRow}:${s5}B${lastDataRow}))`;

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'CAPEX (initial investment)';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: kpiCapexFormulaEng, result: roundNum(investment / 1000, 0) }
    : roundNum(investment / 1000, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FFC62828' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'k PLN';
  sheet6.mergeCells(`E${cfoRowEng}:G${cfoRowEng}`);
  sheet6.getCell(`E${cfoRowEng}`).value = 'Investment outlay (one-time)';
  sheet6.getCell(`E${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '💰 Total savings (undiscounted)';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: kpiSavingsFormulaEng, result: roundNum(totalSavings / 1000, 0) }
    : roundNum(totalSavings / 1000, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  sheet6.getCell(`C${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'k PLN';
  sheet6.mergeCells(`E${cfoRowEng}:G${cfoRowEng}`);
  sheet6.getCell(`E${cfoRowEng}`).value = `Total savings over ${analysisPeriod} years`;
  sheet6.getCell(`E${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '📊 NPV (Net Present Value)';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: kpiNpvFormulaEng, result: roundNum(npvValue / 1000000, 2) }
    : roundNum(npvValue / 1000000, 2);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0.00';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: npvValue > 0 ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  sheet6.getCell(`C${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: npvValue > 0 ? 'FFE8F5E9' : 'FFFFEBEE' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'M PLN';
  sheet6.mergeCells(`E${cfoRowEng}:G${cfoRowEng}`);
  sheet6.getCell(`E${cfoRowEng}`).value = npvValue > 0 ? 'Project profitable (NPV > 0)' : 'Project unprofitable (NPV < 0)';
  sheet6.getCell(`E${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '📈 IRR (Internal Rate of Return)';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: kpiIrrFormulaEng, result: irrValue }
    : irrValue;
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '0.0%';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: irrValue > discountRate ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  sheet6.getCell(`C${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: irrValue > discountRate ? 'FFE8F5E9' : 'FFFFEBEE' } };
  sheet6.getCell(`D${cfoRowEng}`).value = '';
  sheet6.mergeCells(`E${cfoRowEng}:G${cfoRowEng}`);
  sheet6.getCell(`E${cfoRowEng}`).value = irrValue > discountRate ? `IRR > discount rate (${roundNum(discountRate * 100, 1)}%)` : `IRR < discount rate (${roundNum(discountRate * 100, 1)}%)`;
  sheet6.getCell(`E${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '💵 ROI (Return on Investment)';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: kpiRoiFormulaEng, result: roiValue / 100 }
    : roiValue / 100;
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '0.0%';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: roiValue > 0 ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  sheet6.getCell(`D${cfoRowEng}`).value = '';
  sheet6.mergeCells(`E${cfoRowEng}:G${cfoRowEng}`);
  sheet6.getCell(`E${cfoRowEng}`).value = '= (Savings - CAPEX) / CAPEX';
  sheet6.getCell(`E${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '⏱️ Simple Payback';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: kpiPaybackFormulaEng, result: roundNum(simplePaybackValue, 1) }
    : roundNum(simplePaybackValue, 1);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '0.0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'years';
  sheet6.mergeCells(`E${cfoRowEng}:G${cfoRowEng}`);
  sheet6.getCell(`E${cfoRowEng}`).value = 'CAPEX / avg annual savings';
  sheet6.getCell(`E${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '⏱️ Discounted Payback (DPP)';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  const hasDppEng = dppValue !== null && dppValue !== undefined;
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: kpiDppFormulaEng, result: hasDppEng ? roundNum(dppValue, 1) : analysisPeriod + 1 }
    : (hasDppEng ? roundNum(dppValue, 1) : 'Beyond period');
  sheet6.getCell(`C${cfoRowEng}`).numFmt = hasDppEng ? '0.0' : '@';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet6.getCell(`D${cfoRowEng}`).value = hasDppEng ? 'years' : '';
  sheet6.mergeCells(`E${cfoRowEng}:G${cfoRowEng}`);
  sheet6.getCell(`E${cfoRowEng}`).value = 'Year when cumulative NPV >= 0';
  sheet6.getCell(`E${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '⚡ LCOE (energy cost)';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: kpiLcoeFormulaEng, result: roundNum(lcoeValue, 0) }
    : roundNum(lcoeValue, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: lcoeValue < effectiveEnergyPrice ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'PLN/MWh';
  sheet6.mergeCells(`E${cfoRowEng}:G${cfoRowEng}`);
  const priceLabelEng = isRdn ? 'eff. RDN price' : 'grid price';
  sheet6.getCell(`E${cfoRowEng}`).value = lcoeValue < effectiveEnergyPrice ? `LCOE < ${priceLabelEng} (${roundNum(effectiveEnergyPrice, 0)} PLN/MWh)` : `LCOE > ${priceLabelEng}`;
  sheet6.getCell(`E${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  // Add borders to KPI section
  for (let r = kpiSectionRowEng + 1; r <= cfoRowEng; r++) {
    sheet6.getRow(r).getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    sheet6.getRow(r).getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
  }

  // --- SECTION 2 ENG: SENSITIVITY ANALYSIS - TORNADO CHART ---
  cfoRowEng += 2;
  const tornadoHeaderRowEng = cfoRowEng;
  sheet6.mergeCells(`B${cfoRowEng}:G${cfoRowEng}`);
  sheet6.getCell(`B${cfoRowEng}`).value = 'SENSITIVITY ANALYSIS - TORNADO CHART';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 12, color: { argb: 'FFD84315' } };
  sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFBE9E7' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'How key parameters affect NPV (in M PLN):';
  sheet6.getCell(`B${cfoRowEng}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };

  cfoRowEng += 2;
  // Tornado header row
  const tornadoColsEng = ['Variable', 'Range', 'Pessimistic', 'Base', 'Optimistic', 'Range'];
  tornadoColsEng.forEach((h, i) => {
    sheet6.getCell(cfoRowEng, 2 + i).value = h;
    sheet6.getCell(cfoRowEng, 2 + i).font = { bold: true, size: 10 };
    sheet6.getCell(cfoRowEng, 2 + i).alignment = { horizontal: 'center' };
    sheet6.getCell(cfoRowEng, 2 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  // English tornado data - reuse recalculated values from PL tornado (tornadoItems)
  const tornadoItemsEng = [
    { param: 'Grid price', variation: '±20%', pessNpv: npvEnergyPess / 1e6, optNpv: npvEnergyOpt / 1e6,
      pessFormula: `(${s5}M${lastDataRow} + ${s5}F10 / 1000)\n* 0.8\n- ${s5}F10 / 1000`,
      optFormula: `(${s5}M${lastDataRow} + ${s5}F10 / 1000)\n* 1.2\n- ${s5}F10 / 1000`,
      pessNote: `-- NPV CAPEX: grid price -20%\n-- (NPV+CAPEX)×0.8 - CAPEX`,
      optNote: `-- NPV CAPEX: grid price +20%` },
    { param: 'CAPEX (investment cost)', variation: '±20%', pessNpv: npvCapexPess / 1e6, optNpv: npvCapexOpt / 1e6,
      pessFormula: `${s5}M${lastDataRow}\n- ${s5}F10 * 0.2 / 1000`,
      optFormula: `${s5}M${lastDataRow}\n+ ${s5}F10 * 0.2 / 1000`,
      pessNote: `-- NPV CAPEX: investment +20%`,
      optNote: `-- NPV CAPEX: investment -20%` },
    { param: 'PV Yield (production)', variation: '±15%', pessNpv: npvYieldPess / 1e6, optNpv: npvYieldOpt / 1e6,
      pessFormula: `(${s5}M${lastDataRow} + ${s5}F10 / 1000)\n* 0.85\n- ${s5}F10 / 1000`,
      optFormula: `(${s5}M${lastDataRow} + ${s5}F10 / 1000)\n* 1.15\n- ${s5}F10 / 1000`,
      pessNote: `-- NPV CAPEX: PV yield -15%`,
      optNote: `-- NPV CAPEX: PV yield +15%` },
    { param: 'Discount rate', variation: '±2pp', pessNpv: npvDiscPess / 1e6, optNpv: npvDiscOpt / 1e6,
      pessFormula: `${s5}M${lastDataRow}\n* ${roundNum(npvDiscPess / npvValue, 4)}`,
      optFormula: `${s5}M${lastDataRow}\n* ${roundNum(npvDiscOpt / npvValue, 4)}`,
      pessNote: `-- NPV CAPEX: discount rate +2pp`,
      optNote: `-- NPV CAPEX: discount rate -2pp` }
  ];

  // Sort by impact
  tornadoItemsEng.forEach(t => { t.range = Math.abs(t.optNpv - t.pessNpv); });
  tornadoItemsEng.sort((a, b) => b.range - a.range);

  // Render English tornado rows
  tornadoItemsEng.forEach(t => {
    cfoRowEng++;
    sheet6.getCell(`B${cfoRowEng}`).value = t.param;
    sheet6.getCell(`C${cfoRowEng}`).value = t.variation;
    sheet6.getCell(`C${cfoRowEng}`).alignment = { horizontal: 'center' };

    // Pessimistic
    sheet6.getCell(`D${cfoRowEng}`).value = withFormulas
      ? { formula: t.pessFormula, result: roundNum(t.pessNpv, 2) }
      : roundNum(t.pessNpv, 2);
    if (withFormulas && t.pessNote) sheet6.getCell(`D${cfoRowEng}`).note = t.pessNote;
    sheet6.getCell(`D${cfoRowEng}`).numFmt = '# ##0.00';
    sheet6.getCell(`D${cfoRowEng}`).alignment = { horizontal: 'center' };
    sheet6.getCell(`D${cfoRowEng}`).font = { color: { argb: 'FFC62828' } };
    sheet6.getCell(`D${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFEBEE' } };

    // Base
    sheet6.getCell(`E${cfoRowEng}`).value = withFormulas
      ? { formula: `${s5}M${lastDataRow}`, result: roundNum(baseNpvMln, 2) }
      : roundNum(baseNpvMln, 2);
    sheet6.getCell(`E${cfoRowEng}`).numFmt = '# ##0.00';
    sheet6.getCell(`E${cfoRowEng}`).alignment = { horizontal: 'center' };
    sheet6.getCell(`E${cfoRowEng}`).font = { bold: true };
    sheet6.getCell(`E${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    // Optimistic
    sheet6.getCell(`F${cfoRowEng}`).value = withFormulas
      ? { formula: t.optFormula, result: roundNum(t.optNpv, 2) }
      : roundNum(t.optNpv, 2);
    if (withFormulas && t.optNote) sheet6.getCell(`F${cfoRowEng}`).note = t.optNote;
    sheet6.getCell(`F${cfoRowEng}`).numFmt = '# ##0.00';
    sheet6.getCell(`F${cfoRowEng}`).alignment = { horizontal: 'center' };
    sheet6.getCell(`F${cfoRowEng}`).font = { color: { argb: 'FF2E7D32' } };
    sheet6.getCell(`F${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

    // Range
    sheet6.getCell(`G${cfoRowEng}`).value = withFormulas
      ? { formula: `F${cfoRowEng}-D${cfoRowEng}`, result: roundNum(t.range, 2) }
      : roundNum(t.range, 2);
    sheet6.getCell(`G${cfoRowEng}`).numFmt = '# ##0.00';
    sheet6.getCell(`G${cfoRowEng}`).alignment = { horizontal: 'center' };
    sheet6.getCell(`G${cfoRowEng}`).font = { bold: true };
  });

  // Add borders to tornado rows ENG
  for (let r = tornadoHeaderRowEng + 1; r <= cfoRowEng; r++) {
    for (let c = 2; c <= 7; c++) {
      sheet6.getRow(r).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  }

  // --- SECTION 3 ENG: SENSITIVITY MATRIX - NPV vs Grid Price vs Yield ---
  cfoRowEng += 3;
  sheet6.mergeCells(`B${cfoRowEng}:I${cfoRowEng}`);
  sheet6.getCell(`B${cfoRowEng}`).value = 'SENSITIVITY MATRIX - NPV vs Grid Price vs Yield';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 12, color: { argb: 'FF7B1FA2' } };
  sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF3E5F5' } };

  const yieldVariationsEng = [-0.15, -0.10, -0.05, 0, 0.05, 0.10, 0.15];
  const priceVariationsEng = [-0.20, -0.10, 0, 0.10, 0.20];

  // Matrix headers
  cfoRowEng += 2;
  sheet6.getCell(`B${cfoRowEng}`).value = 'NPV [k PLN]';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 9 };
  sheet6.mergeCells(`C${cfoRowEng}:I${cfoRowEng}`);
  sheet6.getCell(`C${cfoRowEng}`).value = '← PV Yield →';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, size: 10 };
  sheet6.getCell(`C${cfoRowEng}`).alignment = { horizontal: 'center' };

  cfoRowEng++;
  const matrixHeaderRowEng = cfoRowEng;
  sheet6.getCell(`B${cfoRowEng}`).value = 'Grid price ↓';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 9 };
  sheet6.getCell(`B${cfoRowEng}`).alignment = { horizontal: 'right' };
  yieldVariationsEng.forEach((yv, i) => {
    sheet6.getCell(cfoRowEng, 3 + i).value = yv;
    sheet6.getCell(cfoRowEng, 3 + i).numFmt = '+0%;-0%;0%';
    sheet6.getCell(cfoRowEng, 3 + i).font = { bold: true, size: 9 };
    sheet6.getCell(cfoRowEng, 3 + i).alignment = { horizontal: 'center' };
    sheet6.getCell(cfoRowEng, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  // Matrix data - NPV in k PLN — FULL RECALCULATION with formulas
  priceVariationsEng.forEach(pv => {
    cfoRowEng++;
    sheet6.getCell(`B${cfoRowEng}`).value = pv;
    sheet6.getCell(`B${cfoRowEng}`).numFmt = '+0%;-0%;0%';
    sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 9 };
    sheet6.getCell(`B${cfoRowEng}`).alignment = { horizontal: 'right' };
    sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    yieldVariationsEng.forEach((yv, i) => {
      let adjNpv;
      try {
        adjNpv = calculateCapexNPV({
          ...capexNpvBaseForMatrix,
          self_consumed_annual_kwh: selfConsumptionByYield[yv],
          total_energy_price_per_kwh: effectiveEnergyPrice / 1000 * (1 + pv)
        }) / 1000;
      } catch (npvErr) {
        const sm = (1 + pv) * (1 + yv);
        adjNpv = (baseNpvTys + (investment / 1000)) * sm - (investment / 1000);
      }
      if (!isFinite(adjNpv)) adjNpv = 0;

      const cell = sheet6.getCell(cfoRowEng, 3 + i);
      if (withFormulas) {
        const colLetter = _col(3 + i);
        const yieldRef = `${colLetter}$${matrixHeaderRowEng}`;
        const priceRef = `$B${cfoRowEng}`;
        const bRange = `${s5}$B$${dataStartRow}:$B$${lastDataRow}`;
        const cRange = `${s5}$C$${dataStartRow}:$C$${lastDataRow}`;
        const kRange = `${s5}$K$${dataStartRow}:$K$${lastDataRow}`;
        const iRange = `${s5}$I$${dataStartRow}:$I$${lastDataRow}`;
        let formula;
        if (isRdn) {
          const A = "'Dane bazowe TCSL (Rok 1)'!";
          formula = `SUMPRODUCT(\n  (${A}$F$18 * ${cRange}\n   * (1 + ${yieldRef}) * (1 + ${priceRef})\n   * POWER(1 + ${s5}$F$5, ${bRange} - 1)\n   + ${A}$F$21 * (1 + ${yieldRef})\n   * POWER(1 + ${s5}$F$5, ${bRange} - 1))\n  / 1000 - ${kRange},\n  1 / POWER(1 + ${s5}$F$4, ${bRange}))\n- ${s5}$F$10`;
        } else {
          formula = `SUMPRODUCT(\n  (${iRange} * ${s5}$F$12\n   * (1 + ${yieldRef}) * (1 + ${priceRef})\n   * POWER(1 + ${s5}$F$5, ${bRange} - 1))\n  / 1000 - ${kRange},\n  1 / POWER(1 + ${s5}$F$4, ${bRange}))\n- ${s5}$F$10`;
        }
        cell.value = { formula, result: roundNum(adjNpv, 0) };
        cell.note = `-- NPV CAPEX at yield ${yieldRef} & price ${priceRef}`;
      } else {
        cell.value = roundNum(adjNpv, 0);
      }
      cell.numFmt = '# ##0';
      cell.alignment = { horizontal: 'center' };

      // Color coding
      if (adjNpv > baseNpvTys * 1.1) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
        cell.font = { color: { argb: 'FF2E7D32' }, bold: true };
      } else if (adjNpv > baseNpvTys * 0.9) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFFDE' } };
      } else if (adjNpv > 0) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFECB3' } };
      } else {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFCDD2' } };
        cell.font = { color: { argb: 'FFC62828' }, bold: true };
      }

      cell.border = {
        top: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        left: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        right: { style: 'thin', color: { argb: 'FFE0E0E0' } }
      };
    });
  });

  // --- SECTION 4 ENG: ESG - ENVIRONMENTAL IMPACT ---
  cfoRowEng += 3;
  sheet6.mergeCells(`B${cfoRowEng}:H${cfoRowEng}`);
  sheet6.getCell(`B${cfoRowEng}`).value = `ESG - ENVIRONMENTAL IMPACT (${analysisPeriod} years)`;
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 12, color: { argb: 'FF00695C' } };
  sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0F2F1' } };

  const esgAutoFormulaEng = `${s5}F11`;
  const esgCo2AnnualFormulaEng = `${s5}F11*0.7`;
  const esgCo2TotalFormulaEng = `${s5}F11*0.7*${s5}F9*(1-${s5}F7*${s5}F9/2)`;
  const esgCarsFormulaEng = `${s5}F11*0.7/4.6`;
  const esgTreesFormulaEng = `${s5}F11*0.7/0.022`;
  const esgFlightsFormulaEng = `${s5}F11*0.7/0.255`;

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'PV Self-consumption [MWh/year]';
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: esgAutoFormulaEng, result: roundNum(baseAutoconsumptionMwh, 0) }
    : roundNum(baseAutoconsumptionMwh, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF00695C' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'Green energy instead of grid';
  sheet6.getCell(`D${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'Grid emission factor [t CO₂/MWh]';
  sheet6.getCell(`C${cfoRowEng}`).value = 0.7;
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '0.0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF00695C' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'Average for Poland';
  sheet6.getCell(`D${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '🌍 Annual CO₂ reduction [tons]';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 11 };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: esgCo2AnnualFormulaEng, result: roundNum(annualCO2Tons, 0) }
    : roundNum(annualCO2Tons, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  sheet6.getCell(`D${cfoRowEng}`).value = '= Self-consumption × 0.7 t/MWh';
  sheet6.getCell(`D${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  const esgCo2TotalRowEng = cfoRowEng;  // Store for decision summary formulas
  sheet6.getCell(`B${cfoRowEng}`).value = `🌍 CO₂ reduction (${analysisPeriod} years) [tons]`;
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 11 };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: esgCo2TotalFormulaEng, result: roundNum(totalCO2Tons, 0) }
    : roundNum(totalCO2Tons, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  sheet6.getCell(`D${cfoRowEng}`).value = 'Total project impact';
  sheet6.getCell(`D${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '🚗 Car equivalent (yearly)';
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: esgCarsFormulaEng, result: roundNum(annualCO2Tons / 4.6, 0) }
    : roundNum(annualCO2Tons / 4.6, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF00695C' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'Annual emissions of this many cars';
  sheet6.getCell(`D${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '🌳 Tree equivalent';
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: esgTreesFormulaEng, result: roundNum(annualCO2Tons / 0.022, 0) }
    : roundNum(annualCO2Tons / 0.022, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF00695C' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'Trees absorbing CO₂';
  sheet6.getCell(`D${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '✈️ Flight equivalent WAW-LON';
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: esgFlightsFormulaEng, result: roundNum(annualCO2Tons / 0.255, 0) }
    : roundNum(annualCO2Tons / 0.255, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF00695C' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'Economy class flights';
  sheet6.getCell(`D${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  // --- SECTION 5 ENG: BREAK-EVEN ANALYSIS ---
  const breakEvenPriceEng = lcoeValue;
  const safetyMarginPctEng = (effectiveEnergyPrice - lcoeValue) / effectiveEnergyPrice;

  const bePriceFormulaEng = `${s5}F12`;
  const beLcoeFormulaEng = kpiLcoeFormulaEng;
  const beMarginFormulaEng = `(${s5}F12-${kpiLcoeFormulaEng})/${s5}F12`;

  cfoRowEng += 2;
  sheet6.mergeCells(`B${cfoRowEng}:H${cfoRowEng}`);
  sheet6.getCell(`B${cfoRowEng}`).value = 'BREAK-EVEN ANALYSIS';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 12, color: { argb: 'FFE65100' } };
  sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'At what energy price does the investment stop being profitable?';
  sheet6.getCell(`B${cfoRowEng}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };

  cfoRowEng++;
  const bePriceRowEng = cfoRowEng;
  sheet6.getCell(`B${cfoRowEng}`).value = isRdn ? 'Effective RDN price (TCSL/MWh)' : 'Current grid energy price';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`C${cfoRowEng}`).value = isRdn
    ? roundNum(effectiveEnergyPrice, 0)
    : (withFormulas ? { formula: bePriceFormulaEng, result: roundNum(totalEnergyPrice, 0) } : roundNum(totalEnergyPrice, 0));
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'PLN/MWh';

  cfoRowEng++;
  const beLcoeRowEng = cfoRowEng;
  sheet6.getCell(`B${cfoRowEng}`).value = 'LCOE of PV installation';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: beLcoeFormulaEng, result: roundNum(lcoeValue, 0) }
    : roundNum(lcoeValue, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'PLN/MWh';

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '⚠️ BREAK-EVEN: Min. grid price';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 11 };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: `C${beLcoeRowEng}`, result: roundNum(breakEvenPriceEng, 0) }
    : roundNum(breakEvenPriceEng, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FFE65100' }, size: 12 };
  sheet6.getCell(`C${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'PLN/MWh';

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '🛡️ Safety margin';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 11 };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: `(C${bePriceRowEng}-C${beLcoeRowEng})/C${bePriceRowEng}`, result: safetyMarginPctEng > 0 ? safetyMarginPctEng : 0 }
    : (safetyMarginPctEng > 0 ? safetyMarginPctEng : 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '0%';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: safetyMarginPctEng > 0.3 ? { argb: 'FF2E7D32' } : { argb: 'FFE65100' }, size: 12 };
  sheet6.getCell(`C${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: safetyMarginPctEng > 0.3 ? 'FFE8F5E9' : 'FFFFF3E0' } };
  sheet6.getCell(`D${cfoRowEng}`).value = '%';

  cfoRowEng++;
  if (safetyMarginPctEng <= 0) {
    sheet6.getCell(`B${cfoRowEng}`).value = `If energy price drops below ${roundNum(lcoeValue, 0)} PLN/MWh, the investment is not profitable.`;
    sheet6.getCell(`B${cfoRowEng}`).font = { italic: true, size: 10, color: { argb: 'FFE65100' } };
  }

  // --- SECTION 6 ENG: SCENARIO ANALYSIS ---
  cfoRowEng += 2;
  sheet6.mergeCells(`B${cfoRowEng}:H${cfoRowEng}`);
  sheet6.getCell(`B${cfoRowEng}`).value = 'SCENARIO ANALYSIS';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 12, color: { argb: 'FF5E35B1' } };
  sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEDE7F6' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'NPV projection under different assumptions:';
  sheet6.getCell(`B${cfoRowEng}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };

  // Scenario table header
  cfoRowEng += 2;
  const scenarioHeadersEng = ['Scenario', 'Grid price', 'PV Yield', 'NPV [k PLN]', 'Probability', 'Weighted'];
  scenarioHeadersEng.forEach((h, i) => {
    sheet6.getCell(cfoRowEng, 2 + i).value = h;
    sheet6.getCell(cfoRowEng, 2 + i).font = { bold: true, size: 10 };
    sheet6.getCell(cfoRowEng, 2 + i).alignment = { horizontal: 'center' };
    sheet6.getCell(cfoRowEng, 2 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  // Scenario data
  const scenariosEng = [
    { name: '⛔ Pessimistic', priceChg: -0.15, yieldChg: -0.10, prob: 0.15, color: 'FFFFCDD2', textColor: 'FFC62828' },
    { name: '🔵 Base', priceChg: 0, yieldChg: 0, prob: 0.50, color: 'FFE3F2FD', textColor: 'FF1565C0' },
    { name: '🟢 Optimistic', priceChg: 0.15, yieldChg: 0.05, prob: 0.25, color: 'FFE8F5E9', textColor: 'FF2E7D32' },
    { name: '🔥 Energy boom', priceChg: 0.30, yieldChg: 0, prob: 0.10, color: 'FFFFF3E0', textColor: 'FFE65100' }
  ];

  let weightedNpvSumEng = 0;
  const scenarioStartRowEng = cfoRowEng + 1;
  scenariosEng.forEach((s, idx) => {
    cfoRowEng++;
    const scenarioNpv = (baseNpvTys + (investment / 1000)) * (1 + s.priceChg) * (1 + s.yieldChg) - (investment / 1000);
    const weightedNpv = scenarioNpv * s.prob;
    weightedNpvSumEng += weightedNpv;

    const priceMultiplier = (1 + s.priceChg).toFixed(2);
    const yieldMultiplier = (1 + s.yieldChg).toFixed(2);
    const scenarioNpvFormulaEng = `(${s5}M${lastDataRow}*1000+${s5}F10)*${priceMultiplier}*${yieldMultiplier}-${s5}F10`;

    sheet6.getCell(`B${cfoRowEng}`).value = s.name;
    sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, color: { argb: s.textColor } };
    sheet6.getCell(`C${cfoRowEng}`).value = `${s.priceChg >= 0 ? '+' : ''}${(s.priceChg * 100).toFixed(0)}%`;
    sheet6.getCell(`C${cfoRowEng}`).alignment = { horizontal: 'center' };
    sheet6.getCell(`D${cfoRowEng}`).value = `${s.yieldChg >= 0 ? '+' : ''}${(s.yieldChg * 100).toFixed(0)}%`;
    sheet6.getCell(`D${cfoRowEng}`).alignment = { horizontal: 'center' };

    // NPV for scenario with formula
    sheet6.getCell(`E${cfoRowEng}`).value = withFormulas
      ? { formula: scenarioNpvFormulaEng, result: roundNum(scenarioNpv, 0) }
      : roundNum(scenarioNpv, 0);
    sheet6.getCell(`E${cfoRowEng}`).numFmt = '# ##0';
    sheet6.getCell(`E${cfoRowEng}`).font = { bold: true, color: { argb: s.textColor } };
    sheet6.getCell(`E${cfoRowEng}`).alignment = { horizontal: 'center' };

    sheet6.getCell(`F${cfoRowEng}`).value = s.prob;
    sheet6.getCell(`F${cfoRowEng}`).numFmt = '0%';
    sheet6.getCell(`F${cfoRowEng}`).alignment = { horizontal: 'center' };

    // Weighted NPV = NPV * probability
    sheet6.getCell(`G${cfoRowEng}`).value = withFormulas
      ? { formula: `E${cfoRowEng}*F${cfoRowEng}`, result: roundNum(weightedNpv, 0) }
      : roundNum(weightedNpv, 0);
    sheet6.getCell(`G${cfoRowEng}`).numFmt = '# ##0';
    sheet6.getCell(`G${cfoRowEng}`).alignment = { horizontal: 'center' };

    // Row background
    for (let c = 2; c <= 7; c++) {
      sheet6.getRow(cfoRowEng).getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: s.color } };
      sheet6.getRow(cfoRowEng).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });

  // Weighted NPV total
  const scenarioEndRowEng = cfoRowEng;
  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '⚖️ EXPECTED NPV VALUE';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 11 };
  sheet6.getCell(`E${cfoRowEng}`).value = 'Weighted sum of scenarios';
  sheet6.getCell(`E${cfoRowEng}`).font = { italic: true, size: 9 };
  sheet6.getCell(`G${cfoRowEng}`).value = withFormulas
    ? { formula: `SUM(G${scenarioStartRowEng}:G${scenarioEndRowEng})`, result: roundNum(weightedNpvSumEng, 0) }
    : roundNum(weightedNpvSumEng, 0);
  sheet6.getCell(`G${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`G${cfoRowEng}`).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  sheet6.getCell(`G${cfoRowEng}`).alignment = { horizontal: 'center' };
  sheet6.getCell(`H${cfoRowEng}`).value = 'k PLN';
  for (let c = 2; c <= 8; c++) {
    sheet6.getRow(cfoRowEng).getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
  }

  // --- SECTION 7 ENG: ENERGY PRICE INFLATION SENSITIVITY ---
  cfoRowEng += 3;
  sheet6.mergeCells(`B${cfoRowEng}:H${cfoRowEng}`);
  sheet6.getCell(`B${cfoRowEng}`).value = 'ENERGY PRICE INFLATION SENSITIVITY';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 12, color: { argb: 'FF00838F' } };
  sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0F7FA' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'How NPV changes with different energy price inflation:';
  sheet6.getCell(`B${cfoRowEng}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };

  cfoRowEng += 2;
  const inflationRatesEng = [0, 0.02, 0.03, 0.05, 0.07, 0.10];
  sheet6.getCell(`B${cfoRowEng}`).value = 'Annual energy price inflation';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  inflationRatesEng.forEach((ir, i) => {
    sheet6.getCell(cfoRowEng, 3 + i).value = `${(ir * 100).toFixed(0)}%`;
    sheet6.getCell(cfoRowEng, 3 + i).font = { bold: true };
    sheet6.getCell(cfoRowEng, 3 + i).alignment = { horizontal: 'center' };
    sheet6.getCell(cfoRowEng, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'NPV [k PLN]';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  inflationRatesEng.forEach((ir, i) => {
    // Higher energy price inflation = higher future savings = higher NPV
    const inflationMultiplier = 1 + (ir - inflationRate) * analysisPeriod * 0.4;
    const adjNpv = baseNpvTys * inflationMultiplier;

    const inflMultiplierVal = inflationMultiplier.toFixed(3);
    const inflNpvFormulaEng = `${s5}M${lastDataRow}*1000*${inflMultiplierVal}`;

    const cell = sheet6.getCell(cfoRowEng, 3 + i);
    cell.value = withFormulas
      ? { formula: inflNpvFormulaEng, result: roundNum(adjNpv, 0) }
      : roundNum(adjNpv, 0);
    cell.numFmt = '# ##0';
    cell.font = { bold: true };
    cell.alignment = { horizontal: 'center' };

    // Highlight base case (3% = current inflation)
    if (ir === inflationRate || (ir === 0.03 && inflationRate > 0.02 && inflationRate < 0.04)) {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
      cell.font = { bold: true, color: { argb: 'FF1565C0' } };
    } else if (adjNpv > baseNpvTys * 1.1) {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
      cell.font = { bold: true, color: { argb: 'FF2E7D32' } };
    }
  });

  // DECISION SUMMARY - CAPEX vs STATUS QUO
  cfoRowEng += 3;
  sheet6.mergeCells(`B${cfoRowEng}:H${cfoRowEng}`);
  sheet6.getCell(`B${cfoRowEng}`).value = 'DECISION SUMMARY - CAPEX vs STATUS QUO';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

  cfoRowEng += 2;
  const decisionHeadersEng = ['Criterion', 'CAPEX Investment', 'Status Quo', 'Winner'];
  decisionHeadersEng.forEach((h, i) => {
    sheet6.getCell(cfoRowEng, 2 + i).value = h;
    sheet6.getCell(cfoRowEng, 2 + i).font = { bold: true };
    sheet6.getCell(cfoRowEng, 2 + i).alignment = { horizontal: 'center' };
    sheet6.getCell(cfoRowEng, 2 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  const gridCost30YearsEng = isRdn
    ? rdnGridCostYear1Tys * analysisPeriod
    : baseAutoconsumptionMwh * totalEnergyPrice * analysisPeriod / 1000;

  const decisionRowsEng = [
    { criterion: 'Investment outlay', capex: `${roundNum(investment / 1000, 0)} k PLN`, statusQuo: '0 PLN', winner: 'Status Quo', useFormula: true, formulaType: 'investment' },
    { criterion: `Energy cost ${analysisPeriod} years`, capex: '0 k', statusQuo: `${roundNum(gridCost30YearsEng, 0)} k`, winner: 'CAPEX', useFormula: true, formulaType: 'energyCost' },
    { criterion: `Savings ${analysisPeriod} years`, capex: `${roundNum(totalSavings / 1000, 0)} k PLN`, statusQuo: '0 PLN', winner: 'CAPEX', useFormula: true, formulaType: 'savings' },
    { criterion: 'NPV (present value)', capex: `${roundNum(npvValue / 1000, 0)} k PLN`, statusQuo: '0 PLN', winner: npvValue > 0 ? 'CAPEX' : 'Status Quo', useFormula: true, formulaType: 'npv' },
    { criterion: 'Price risk', capex: 'Partial hedge', statusQuo: '100% exposure', winner: 'CAPEX', useFormula: false },
    { criterion: 'Asset ownership', capex: 'YES', statusQuo: 'NO', winner: 'CAPEX', useFormula: false },
    { criterion: 'Green energy', capex: 'YES', statusQuo: 'NO', winner: 'CAPEX', useFormula: false },
    { criterion: `CO₂ reduction (${analysisPeriod} years)`, capex: `${roundNum(totalCO2Tons, 0)} tons`, statusQuo: '0 tons', winner: 'CAPEX', useFormula: true, formulaType: 'co2' }
  ];

  const capexDecisionFirstRowEng = cfoRowEng + 1;
  let capexWinsEng = 0;
  decisionRowsEng.forEach(row => {
    cfoRowEng++;
    sheet6.getCell(`B${cfoRowEng}`).value = row.criterion;
    sheet6.getCell(`B${cfoRowEng}`).font = { color: { argb: 'FF424242' } };

    // C column (CAPEX value) — formulas matching reference ROUND pattern
    if (withFormulas && row.useFormula) {
      if (row.formulaType === 'investment') {
        sheet6.getCell(`C${cfoRowEng}`).value = { formula: `ROUND(${s5}F10,0)\n&" k PLN"`, result: row.capex };
      } else if (row.formulaType === 'savings') {
        sheet6.getCell(`C${cfoRowEng}`).value = {
          formula: `ROUND(\n  SUM(${s5}L${dataStartRow}:${s5}L${lastDataRow}),\n  0)\n&" k PLN"`,
          result: row.capex
        };
      } else if (row.formulaType === 'npv') {
        sheet6.getCell(`C${cfoRowEng}`).value = {
          formula: `ROUND(\n  ${s5}M${lastDataRow}*1000,\n  0)\n&" k PLN"`,
          result: row.capex
        };
      } else if (row.formulaType === 'co2') {
        sheet6.getCell(`C${cfoRowEng}`).value = {
          formula: `ROUND(\n  SUM(${s5}I${dataStartRow}:${s5}I${lastDataRow})*0.7,\n  0)\n&" tons"`,
          result: row.capex
        };
      } else {
        sheet6.getCell(`C${cfoRowEng}`).value = row.capex;
      }
    } else {
      sheet6.getCell(`C${cfoRowEng}`).value = row.capex;
    }
    sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF1565C0' } };
    sheet6.getCell(`C${cfoRowEng}`).alignment = { horizontal: 'center' };

    // D column (Status Quo value) — formulas when applicable
    if (withFormulas && row.useFormula && row.formulaType === 'energyCost') {
      sheet6.getCell(`D${cfoRowEng}`).value = {
        formula: `ROUND(\n  ${s5}F12*${s5}F9,\n  0)\n&" k"`,
        result: row.statusQuo
      };
    } else {
      sheet6.getCell(`D${cfoRowEng}`).value = row.statusQuo;
    }
    sheet6.getCell(`D${cfoRowEng}`).font = { color: { argb: 'FFC62828' } };
    sheet6.getCell(`D${cfoRowEng}`).alignment = { horizontal: 'center' };

    // E column (Winner) — formulas when applicable
    if (withFormulas && row.useFormula) {
      if (row.formulaType === 'investment') {
        sheet6.getCell(`E${cfoRowEng}`).value = { formula: `IF(${s5}F10>0,\n  "Status Quo","Tie")`, result: row.winner };
      } else if (row.formulaType === 'energyCost') {
        sheet6.getCell(`E${cfoRowEng}`).value = {
          formula: `IF(\n  SUM(${s5}F${dataStartRow}:${s5}F${lastDataRow})>0,\n  "CAPEX","Status Quo")`,
          result: row.winner
        };
      } else if (row.formulaType === 'savings') {
        sheet6.getCell(`E${cfoRowEng}`).value = {
          formula: `IF(\n  SUM(${s5}L${dataStartRow}:${s5}L${lastDataRow})>0,\n  "CAPEX","Status Quo")`,
          result: row.winner
        };
      } else if (row.formulaType === 'npv') {
        sheet6.getCell(`E${cfoRowEng}`).value = { formula: `IF(${s5}M${lastDataRow}>0,\n  "CAPEX","Status Quo")`, result: row.winner };
      } else if (row.formulaType === 'co2') {
        sheet6.getCell(`E${cfoRowEng}`).value = { formula: `IF($C$${esgCo2TotalRowEng}>0,\n  "CAPEX","Status Quo")`, result: row.winner };
      } else {
        sheet6.getCell(`E${cfoRowEng}`).value = row.winner;
      }
    } else {
      sheet6.getCell(`E${cfoRowEng}`).value = row.winner;
    }
    sheet6.getCell(`E${cfoRowEng}`).font = { bold: true, color: { argb: row.winner === 'CAPEX' ? 'FF2E7D32' : 'FFE65100' } };
    sheet6.getCell(`E${cfoRowEng}`).alignment = { horizontal: 'center' };

    if (row.winner === 'CAPEX') capexWinsEng++;

    for (let c = 2; c <= 5; c++) {
      sheet6.getRow(cfoRowEng).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });
  const capexDecisionLastRowEng = cfoRowEng;

  // Final recommendation — dynamic COUNTIF formula
  cfoRowEng += 2;
  const recommendationEng = capexWinsEng >= 5 ? 'CAPEX' : 'Status Quo';
  sheet6.mergeCells(`B${cfoRowEng}:E${cfoRowEng}`);
  if (withFormulas) {
    const eRangeEng = `E${capexDecisionFirstRowEng}:E${capexDecisionLastRowEng}`;
    const nCritEng = decisionRowsEng.length;
    sheet6.getCell(`B${cfoRowEng}`).value = {
      formula: `IF(\n  COUNTIF(${eRangeEng},"CAPEX")\n  > COUNTIF(${eRangeEng},"Status Quo"),\n  "✅ RECOMMENDATION: CAPEX Investment - wins in "\n  & COUNTIF(${eRangeEng},"CAPEX")\n  & " of ${nCritEng} criteria",\n  "⛔ RECOMMENDATION: Status Quo - wins in "\n  & COUNTIF(${eRangeEng},"Status Quo")\n  & " of ${nCritEng} criteria")`,
      result: `✅ RECOMMENDATION: CAPEX Investment - wins in ${capexWinsEng} of ${nCritEng} criteria`
    };
  } else {
    sheet6.getCell(`B${cfoRowEng}`).value = `✅ RECOMMENDATION: CAPEX Investment - wins in ${capexWinsEng} of ${decisionRowsEng.length} criteria`;
  }
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 12, color: { argb: recommendationEng === 'CAPEX' ? 'FF2E7D32' : 'FFC62828' } };
  sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: recommendationEng === 'CAPEX' ? 'FFE8F5E9' : 'FFFFEBEE' } };
  sheet6.getCell(`B${cfoRowEng}`).alignment = { horizontal: 'center' };

  cfoRowEng++;
  sheet6.mergeCells(`B${cfoRowEng}:E${cfoRowEng}`);
  if (withFormulas) {
    sheet6.getCell(`B${cfoRowEng}`).value = {
      formula: `"NPV = "\n&ROUND(${s5}M${lastDataRow}*1000,0)\n&" k PLN | IRR = "\n&ROUND(${kpiIrrFormulaEng}*100,0)\n&"% | Payback = "\n&FIXED(${kpiPaybackFormulaEng},1)\n&" years"`,
      result: `NPV = ${roundNum(npvValue / 1000, 0)} k PLN | IRR = ${roundNum(irrValue * 100, 1)}% | Payback = ${roundNum(simplePaybackValue, 1)} years`
    };
  } else {
    sheet6.getCell(`B${cfoRowEng}`).value = `NPV = ${roundNum(npvValue / 1000, 0)} k PLN | IRR = ${roundNum(irrValue * 100, 1)}% | Payback = ${roundNum(simplePaybackValue, 1)} years`;
  }
  sheet6.getCell(`B${cfoRowEng}`).font = { italic: true, size: 10, color: { argb: 'FF1565C0' } };
  sheet6.getCell(`B${cfoRowEng}`).alignment = { horizontal: 'center' };

  console.log('✅ English sheets added (CAPEX Summary, CAPEX Year by Year, CFO Analysis)');

  // ========== OPTIONAL: RDN vs TARYFA SHEET ==========
  // Only added when RDN metrics exist for the current variant
  const rdnResult = (typeof rdnMetrics !== 'undefined') && rdnMetrics[currentVariant];
  if (rdnResult) {
    try {
      const sheetRdn = workbook.addWorksheet('RDN vs Taryfa');
      const monthNamesRdn = ['Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
                              'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'];

      sheetRdn.columns = [
        { width: 2 },  // A: margin
        { width: 30 }, // B: Parameter
        { width: 22 }, // C: Taryfa stała
        { width: 22 }, // D: RDN dynamiczne
        { width: 22 }, // E: Delta
      ];

      // Title
      sheetRdn.getCell('B1').value = `RDN vs TARYFA - Porównanie Oszczędności - Scenariusz ${scenarioName}`;
      sheetRdn.getCell('B1').font = { bold: true, size: 14, color: { argb: 'FFE65100' } };
      sheetRdn.mergeCells('B1:E1');

      // Summary section
      let row = 3;
      const headerFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF424242' } };
      const headerFont = { bold: true, color: { argb: 'FFFFFFFF' }, size: 11 };
      const numFmt = '#,##0';

      sheetRdn.getCell(`B${row}`).value = 'Parametr';
      sheetRdn.getCell(`C${row}`).value = 'Taryfa Stała/ToU';
      sheetRdn.getCell(`D${row}`).value = 'RDN Dynamiczne';
      sheetRdn.getCell(`E${row}`).value = 'Delta';
      ['B','C','D','E'].forEach(col => {
        sheetRdn.getCell(`${col}${row}`).fill = headerFill;
        sheetRdn.getCell(`${col}${row}`).font = headerFont;
        sheetRdn.getCell(`${col}${row}`).alignment = { horizontal: 'center' };
      });

      row++;
      const summaryRows = [
        ['Roczne oszczędności [PLN]', rdnResult.fixed_annual_savings_pln, rdnResult.rdn_annual_savings_pln],
        ['Cena efektywna [PLN/MWh]', rdnResult.fixed_total_price_plnmwh, rdnResult.rdn_avg_effective_price_plnmwh],
        ['Autokonsumpcja [kWh]', rdnResult.annual_self_consumed_kwh, rdnResult.annual_self_consumed_kwh],
        ['Produkcja roczna [kWh]', rdnResult.annual_production_kwh, rdnResult.annual_production_kwh],
        ['Zużycie roczne [kWh]', rdnResult.annual_consumption_kwh, rdnResult.annual_consumption_kwh],
      ];

      summaryRows.forEach(([label, fixedVal, rdnVal]) => {
        sheetRdn.getCell(`B${row}`).value = label;
        sheetRdn.getCell(`B${row}`).font = { bold: true };
        sheetRdn.getCell(`C${row}`).value = Math.round(fixedVal);
        sheetRdn.getCell(`C${row}`).numFmt = numFmt;
        sheetRdn.getCell(`D${row}`).value = Math.round(rdnVal);
        sheetRdn.getCell(`D${row}`).numFmt = numFmt;
        sheetRdn.getCell(`E${row}`).value = Math.round(rdnVal - fixedVal);
        sheetRdn.getCell(`E${row}`).numFmt = '+#,##0;-#,##0;0';
        sheetRdn.getCell(`E${row}`).font = {
          color: { argb: (rdnVal - fixedVal) >= 0 ? 'FF2E7D32' : 'FFC62828' },
          bold: true
        };
        row++;
      });

      // Delta summary
      row++;
      sheetRdn.getCell(`B${row}`).value = 'Delta roczna';
      sheetRdn.getCell(`B${row}`).font = { bold: true, size: 12 };
      sheetRdn.getCell(`C${row}`).value = `${rdnResult.rdn_vs_fixed_delta_pln >= 0 ? '+' : ''}${Math.round(rdnResult.rdn_vs_fixed_delta_pln)} PLN (${rdnResult.rdn_vs_fixed_delta_pct.toFixed(1)}%)`;
      sheetRdn.getCell(`C${row}`).font = {
        bold: true, size: 12,
        color: { argb: rdnResult.rdn_vs_fixed_delta_pln >= 0 ? 'FF2E7D32' : 'FFC62828' }
      };

      // Monthly breakdown
      row += 2;
      sheetRdn.getCell(`B${row}`).value = 'Miesiąc';
      sheetRdn.getCell(`C${row}`).value = 'Oszcz. Taryfa [PLN]';
      sheetRdn.getCell(`D${row}`).value = 'Oszcz. RDN [PLN]';
      sheetRdn.getCell(`E${row}`).value = 'Delta [PLN]';
      ['B','C','D','E'].forEach(col => {
        sheetRdn.getCell(`${col}${row}`).fill = headerFill;
        sheetRdn.getCell(`${col}${row}`).font = headerFont;
        sheetRdn.getCell(`${col}${row}`).alignment = { horizontal: 'center' };
      });

      row++;
      if (rdnResult.monthly_comparison) {
        rdnResult.monthly_comparison.forEach((m, i) => {
          const delta = m.rdn_savings_pln - m.fixed_savings_pln;
          sheetRdn.getCell(`B${row}`).value = monthNamesRdn[i] || `Miesiąc ${i+1}`;
          sheetRdn.getCell(`C${row}`).value = Math.round(m.fixed_savings_pln);
          sheetRdn.getCell(`C${row}`).numFmt = numFmt;
          sheetRdn.getCell(`D${row}`).value = Math.round(m.rdn_savings_pln);
          sheetRdn.getCell(`D${row}`).numFmt = numFmt;
          sheetRdn.getCell(`E${row}`).value = Math.round(delta);
          sheetRdn.getCell(`E${row}`).numFmt = '+#,##0;-#,##0;0';
          sheetRdn.getCell(`E${row}`).font = {
            color: { argb: delta >= 0 ? 'FF2E7D32' : 'FFC62828' },
            bold: true
          };
          // Alternating row colors
          if (i % 2 === 0) {
            ['B','C','D','E'].forEach(col => {
              sheetRdn.getCell(`${col}${row}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
            });
          }
          row++;
        });
      }

      // Price statistics
      row += 2;
      sheetRdn.getCell(`B${row}`).value = 'Statystyki cen RDN (w godzinach autokonsumpcji)';
      sheetRdn.getCell(`B${row}`).font = { bold: true, size: 11 };
      row++;
      const priceStats = rdnResult.rdn_price_stats || {};
      const statsData = [
        ['Średnia ważona', priceStats.weighted_avg || rdnResult.rdn_avg_effective_price_plnmwh],
        ['Minimum', priceStats.min],
        ['Maksimum', priceStats.max],
        ['Mediana', priceStats.median],
      ];
      statsData.forEach(([label, val]) => {
        sheetRdn.getCell(`B${row}`).value = label;
        sheetRdn.getCell(`C${row}`).value = val ? Math.round(val) : '-';
        if (val) sheetRdn.getCell(`C${row}`).numFmt = numFmt;
        sheetRdn.getCell(`D${row}`).value = 'PLN/MWh';
        row++;
      });

      console.log('✅ RDN vs Taryfa sheet added');
    } catch (rdnErr) {
      console.warn('⚠️ Failed to add RDN sheet:', rdnErr);
    }
  }

  // TCSL Audit sheet (only in RDN mode)
  if (isRdn && rdnBL && window.addTcslAuditSheet) {
    try {
      window.addTcslAuditSheet(workbook, rdnBL, {
        inflationRate,
        discountRate,
        pvDegYear1: pvDegradationYear1,
        pvDegYear2Plus: pvDegradationYears2Plus,
        analysisPeriod,
      }, logoImageId);
    } catch (auditErr) {
      console.warn('⚠️ Failed to add TCSL audit sheet:', auditErr);
    }
  }

  // Apply watermark (inline, self-contained - no cross-file dependency)
  try {
    _capexApplyWatermark(workbook, {
      visibleSheets: ['Podsumowanie CAPEX', 'CAPEX Summary'],
    });
  } catch (wmErr) {
    console.error('🔒 CAPEX Watermark FAILED:', wmErr.message, wmErr.stack);
  }

  // Generate filename
  const dateStr = new Date().toISOString().split('T')[0];
  const rdnPrefix = window._rdnExportMode ? 'CAPEX_RDN' : 'CAPEX';
  const filename = withFormulas
    ? `${rdnPrefix}_Analiza_${currentVariant}_${capacityKwp}kWp_${scenarioName}_${dateStr}_FORMULY.xlsx`
    : `${rdnPrefix}_Analiza_${currentVariant}_${capacityKwp}kWp_${scenarioName}_${dateStr}.xlsx`;

  // Generate Excel buffer
  const buffer = await workbook.xlsx.writeBuffer();

  // ========== NATIVE EXCEL CHARTS (Dynamic) ==========
  // Column references shifted +1 for margin column: A->B, K->L, L->M
  // Chart positions: NPV at col H (7), Oszczędności at col M (12)
  const chartConfigs = [
    // Polish sheet charts (sheet index 1 = "CAPEX Rok po Roku")
    {
      type: 'line',
      title: 'NPV Skumulowane [mln PLN]',
      sheetName: 'CAPEX Rok po Roku',
      sheetIndex: 1,
      categoryRange: `$B$17:$B$${lastDataRow}`,  // Column B (was A)
      valueRange: `$M$17:$M$${lastDataRow}`,      // Column M (was L)
      seriesName: 'NPV Skumulowane',
      position: { fromCol: 7, fromRow: 1, toCol: 11, toRow: 15 }  // Column H (7) to K (11)
    },
    {
      type: 'bar',
      title: 'Oszczędności Roczne [tys. PLN]',
      sheetName: 'CAPEX Rok po Roku',
      sheetIndex: 1,
      categoryRange: `$B$${dataStartRow}:$B$${lastDataRow}`,  // Column B (was A)
      valueRange: `$L$${dataStartRow}:$L$${lastDataRow}`,      // Column L (was K)
      seriesName: 'Oszczędności',
      position: { fromCol: 12, fromRow: 1, toCol: 16, toRow: 15 }  // Column M (12) to P (16)
    },
    // English sheet charts (sheet index 4 = "CAPEX Year by Year")
    {
      type: 'line',
      title: 'Cumulative NPV [M PLN]',
      sheetName: 'CAPEX Year by Year',
      sheetIndex: 4,
      categoryRange: `$B$17:$B$${lastDataRow}`,
      valueRange: `$M$17:$M$${lastDataRow}`,
      seriesName: 'Cumulative NPV',
      position: { fromCol: 7, fromRow: 1, toCol: 11, toRow: 15 }
    },
    {
      type: 'bar',
      title: 'Annual Savings [k PLN]',
      sheetName: 'CAPEX Year by Year',
      sheetIndex: 4,
      categoryRange: `$B$${dataStartRow}:$B$${lastDataRow}`,
      valueRange: `$L$${dataStartRow}:$L$${lastDataRow}`,
      seriesName: 'Savings',
      position: { fromCol: 12, fromRow: 1, toCol: 16, toRow: 15 }
    }
  ];

  let finalBlob;
  try {
    finalBlob = await injectNativeExcelCharts(buffer, chartConfigs, 1);
  } catch (e) {
    console.warn('⚠️ Charts failed:', e);
    finalBlob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  }

  // Download
  const url = URL.createObjectURL(finalBlob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);

  console.log('✅ CAPEX exported:', filename);
  } catch (exportErr) {
    console.error('❌ CAPEX Excel export failed:', exportErr);
    alert('Błąd eksportu CAPEX Excel: ' + exportErr.message);
  }
}

async function exportCapexToExcelWithFormulas() {
  await exportCapexToExcel(true);
}

// RDN wrapper: swap centralizedMetrics with centralizedMetricsRdn, export, restore
async function exportCapexRdnToExcel(withFormulas = false) {
  const rdnCalc = (window.centralizedMetricsRdn || {})[currentVariant];
  if (!rdnCalc || !rdnCalc.capex) {
    alert('Brak danych CAPEX (RDN) do eksportu. Najpierw wykonaj analizę TCSL.');
    return;
  }
  const backup = centralizedMetrics[currentVariant];
  centralizedMetrics[currentVariant] = rdnCalc;
  window._rdnExportMode = true;
  try {
    await exportCapexToExcel(withFormulas);
  } finally {
    centralizedMetrics[currentVariant] = backup;
    window._rdnExportMode = false;
  }
}

// Export CAPEX functions to window for HTML onclick handlers
window.exportCapexToExcel = exportCapexToExcel;
window.exportCapexToExcelWithFormulas = exportCapexToExcelWithFormulas;
window.exportCapexRdnToExcel = exportCapexRdnToExcel;

// Note: English sheets (CAPEX Summary, CAPEX Year by Year, CFO Analysis)
// are now automatically included in the main export function above.
