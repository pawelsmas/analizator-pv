// ============================================================================
// === CAPEX EXCEL EXPORT ===
// ============================================================================
// Version: v12 - Native Excel charts (dynamic - update with data)
// ============================================================================

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
 * Export CAPEX year-by-year analysis to Excel
 * Similar structure to EaaS export but for investor (CAPEX) perspective
 */
async function exportCapexToExcel(withFormulas = false) {
  console.log('📥 Exporting CAPEX analysis to Excel...', withFormulas ? '(WITH FORMULAS)' : '(values only)');

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
  const discountRate = centralizedCalc.common.discountRate || 0.07;
  const inflationRate = centralizedCalc.common.inflationRate || 0.025;
  const totalEnergyPrice = centralizedCalc.common.totalEnergyPrice || 800;
  const analysisPeriod = params.analysis_period || cashFlows.length;

  // Capacity and production data
  const capacityKwp = variant.capacity;
  const annualConsumptionKwh = getAnnualConsumptionKwh();
  const annualConsumptionMwh = annualConsumptionKwh / 1000;
  const baseAutoconsumptionMwh = centralizedCalc.common.selfConsumedMwh || (variant.self_consumed || 0) / 1000;

  // Degradation rates
  const pvDegradationYear1 = (systemSettings?.pvDegradationYear1 !== undefined ? systemSettings.pvDegradationYear1 : 2.0) / 100;
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
  sheet1.getCell('B1').value = 'ANALIZA CAPEX - Perspektywa Inwestora';
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

  // Add KPI rows with formulas or values
  // Note: Sheet2 has margin column A, so: B=Rok, L=Oszczędn., M=NPV Skum., F=Parameters
  if (withFormulas) {
    summaryRows.push(['NPV [mln PLN]:', { formula: "'CAPEX Rok po Roku'!M" + lastDataRow }]);
    summaryRows.push(['IRR [%]:', roundNum(centralizedCalc.capex.irr * 100, 1)]);
    summaryRows.push(['ROI [%]:', { formula: "(SUM('CAPEX Rok po Roku'!L" + dataStartRow + ":L" + lastDataRow + ")*1000-'CAPEX Rok po Roku'!F10*1000)/('CAPEX Rok po Roku'!F10*1000)*100" }]);
    summaryRows.push(['Prosty zwrot [lat]:', { formula: "'CAPEX Rok po Roku'!F10*1000/AVERAGE('CAPEX Rok po Roku'!L" + dataStartRow + ":L" + (dataStartRow + 4) + ")/1000" }]);
  } else {
    summaryRows.push(['NPV [mln PLN]:', roundNum(centralizedCalc.capex.npv / 1000000, 2)]);
    summaryRows.push(['IRR [%]:', roundNum(centralizedCalc.capex.irr * 100, 1)]);
    summaryRows.push(['ROI [%]:', roundNum(roi, 1)]);
    summaryRows.push(['Prosty zwrot [lat]:', roundNum(centralizedCalc.capex.simplePayback, 1)]);
  }
  summaryRows.push(['Zdyskontowany zwrot [lat]:', centralizedCalc.capex.discountedPayback ? roundNum(centralizedCalc.capex.discountedPayback, 1) : 'Powyżej okresu analizy']);
  summaryRows.push(['LCOE [PLN/MWh]:', roundNum(centralizedCalc.capex.lcoe, 0)]);

  summaryRows.forEach((row, idx) => {
    const excelRow = sheet1.getRow(idx + 5);
    excelRow.getCell(2).value = row[0];
    if (typeof row[1] === 'object' && row[1].formula) {
      excelRow.getCell(3).value = row[1];
    } else {
      excelRow.getCell(3).value = row[1];
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
  sheet2.getCell('B1').value = 'ANALIZA CAPEX ROK PO ROKU Z NPV';
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
    { row: 12, label: 'Cena sieci bazowa [PLN/MWh]:', value: roundNum(totalEnergyPrice, 2), numFmt: '# ##0.00' },
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
      valueCell.value = p.value;
      valueCell.alignment = { horizontal: 'left', indent: 1 };
      valueCell.font = { bold: true, color: { argb: 'FF1976D2' } };
      valueCell.border = { bottom: { style: 'thin', color: { argb: 'FFEEEEEE' } } };
      if (p.numFmt) {
        valueCell.numFmt = p.numFmt;
      }
    }
  });

  // Header row (row 16) - shifted +1 for margin column
  const headers = ['Rok', 'Deg PV [%]', 'Deg BESS [%]', 'Zużycie [MWh]', 'Koszt OSD [tys.]',
    'Auto PV [MWh]', 'Auto BESS [MWh]', 'Suma Auto [MWh]', 'Równow. OSD [tys.]',
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
    const inflFactor = Math.pow(1 + inflationRate, year);
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
      // Koszt OSD
      row.getCell(6).value = { formula: '$F$13*$F$12*POWER(1+$F$5,' + year + ')/1000', result: annualConsumptionMwh * totalEnergyPrice * inflFactor / 1000 };
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
      // Równow. OSD (savings from autoconsumption)
      row.getCell(10).value = { formula: 'I' + dataRow + '*$F$12*POWER(1+$F$5,' + year + ')/1000', result: cf.savings / 1000 };
      row.getCell(10).numFmt = numFmtStandard;
      row.getCell(10).alignment = { horizontal: 'right', indent: 1 };
      // OPEX - formula with inflation: base OPEX * (1+inflation)^year
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
      row.getCell(6).value = roundNum(annualConsumptionMwh * totalEnergyPrice * inflFactor / 1000, 2);
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

  // DPP Row Highlighting - highlight entire row where NPV becomes positive (Zdyskontowany zwrot)
  // Find the first year where cumulative NPV >= 0
  const dppYear = centralizedCalc.capex.discountedPayback;
  if (dppYear && dppYear <= analysisPeriod) {
    const dppRowNumber = 17 + Math.ceil(dppYear); // Row 17 is Year 0, so Year N is row 17+N
    const dppRow = sheet2.getRow(dppRowNumber);
    // Apply gold/amber highlight to entire DPP row (columns B-M, skip margin A)
    const dppFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF8E1' } }; // Light amber
    const dppBorder = {
      top: { style: 'medium', color: { argb: 'FFFFC107' } },
      bottom: { style: 'medium', color: { argb: 'FFFFC107' } }
    };
    for (let col = 2; col <= 13; col++) {  // Columns B-M (indices 2-13)
      const cell = dppRow.getCell(col);
      cell.fill = dppFill;
      cell.border = dppBorder;
    }
    // Add marker in column B to indicate DPP
    dppRow.getCell(2).font = { bold: true, color: { argb: 'FFFF8F00' } };
    console.log(`📍 DPP Row highlighted: Year ${Math.ceil(dppYear)} (row ${dppRowNumber})`);
  }

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

  // DPP formula: Find first year where cumulative NPV >= 0
  const dppFormula = 'SUMPRODUCT((M' + dataStartRow + ':M' + lastDataRow + '<0)*1)+1';

  // LCOE formula: shifted columns J->K, H->I, E->F, A->B
  const lcoeFormula = '($F$10*1000+SUMPRODUCT(K' + dataStartRow + ':K' + lastDataRow + '/POWER(1+$F$4,B' + dataStartRow + ':B' + lastDataRow + ')))/SUMPRODUCT(I' + dataStartRow + ':I' + lastDataRow + '/POWER(1+$F$4,B' + dataStartRow + ':B' + lastDataRow + '))';

  const kpiRows = [
    ['CAPEX (inwestycja):', withFormulas ? { formula: '$F$10' } : roundNum(investment / 1000, 2), 'tys. PLN', '= Nakład początkowy', '# ##0.00'],
    ['Suma oszczędności:', withFormulas ? { formula: 'SUM(L' + dataStartRow + ':L' + lastDataRow + ')' } : roundNum(cashFlows.reduce((s, cf) => s + cf.net_cash_flow, 0) / 1000, 2), 'tys. PLN', '= Suma kolumny L', '# ##0.00'],
    ['NPV:', withFormulas ? { formula: 'M' + lastDataRow } : roundNum(centralizedCalc.capex.npv / 1000000, 3), 'mln PLN', '= Wartość bieżąca netto', '# ##0.000'],
    ['IRR:', withFormulas ? { formula: irrFormula } : roundNum(centralizedCalc.capex.irr * 100, 2), '%', '= Wewnętrzna stopa zwrotu', '# ##0.00'],
    ['ROI:', withFormulas ? { formula: '(F' + (summaryStartRow + 2) + '-F' + (summaryStartRow + 1) + ')/F' + (summaryStartRow + 1) + '*100' } : roundNum(roi, 2), '%', '= (Oszczędności - CAPEX) / CAPEX', '# ##0.00'],
    ['Prosty zwrot (Payback):', withFormulas ? { formula: simplePaybackFormula } : roundNum(centralizedCalc.capex.simplePayback, 2), 'lat', '= CAPEX / średnie roczne oszczędności', '# ##0.00'],
    ['Zdyskontowany zwrot (DPP):', withFormulas ? { formula: dppFormula } : (centralizedCalc.capex.discountedPayback ? roundNum(centralizedCalc.capex.discountedPayback, 2) : '-'), 'lat', '= Rok gdy NPV ≥ 0', '# ##0.00'],
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

  // Note about formulas
  if (withFormulas) {
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
  sheet3.getCell(`D${cfoRow}`).value = 'Cena energii [PLN/MWh]';
  sheet3.getCell(`E${cfoRow}`).value = withFormulas
    ? { formula: `${s2}F12`, result: roundNum(totalEnergyPrice, 0) }
    : roundNum(totalEnergyPrice, 0);
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
  const kpiDppFormula = `SUMPRODUCT((${s2}M${dataStartRow}:${s2}M${lastDataRow}<0)*1)+1`;
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
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: kpiDppFormula, result: dppValue ? roundNum(dppValue, 1) : analysisPeriod + 1 }
    : (dppValue ? roundNum(dppValue, 1) : 'Powyżej okresu');
  sheet3.getCell(`C${cfoRow}`).numFmt = dppValue ? '0.0' : '@';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet3.getCell(`D${cfoRow}`).value = dppValue ? 'lat' : '';
  sheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  sheet3.getCell(`E${cfoRow}`).value = 'Rok gdy skumulowane NPV ≥ 0';
  sheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = '⚡ LCOE (koszt energii)';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: kpiLcoeFormula, result: roundNum(lcoeValue, 0) }
    : roundNum(lcoeValue, 0);
  sheet3.getCell(`C${cfoRow}`).numFmt = '# ##0';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: lcoeValue < totalEnergyPrice ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  sheet3.getCell(`D${cfoRow}`).value = 'PLN/MWh';
  sheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  sheet3.getCell(`E${cfoRow}`).value = lcoeValue < totalEnergyPrice ? `LCOE < cena sieci (${roundNum(totalEnergyPrice, 0)} PLN/MWh)` : `LCOE > cena sieci`;
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

  // Calculate sensitivity - simplified approach for NPV
  const baseNpvMln = npvValue / 1000000;

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

  // Tornado data with formulas - Cena energii z sieci (sorted by impact, highest first)
  // Row 1: Cena energii - ±20% -> -40%/+40% NPV impact
  cfoRow++;
  const tornadoRow1 = cfoRow;
  sheet3.getCell(`B${cfoRow}`).value = 'Cena energii z sieci';
  sheet3.getCell(`C${cfoRow}`).value = '±20%';
  sheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };
  // Pessimistic: NPV * 0.6 (price -20% = -40% savings impact)
  sheet3.getCell(`D${cfoRow}`).value = withFormulas
    ? { formula: `${s2}M${lastDataRow}*0.6`, result: roundNum(baseNpvMln * 0.6, 2) }
    : roundNum(baseNpvMln * 0.6, 2);
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
  // Optimistic: NPV * 1.4
  sheet3.getCell(`F${cfoRow}`).value = withFormulas
    ? { formula: `${s2}M${lastDataRow}*1.4`, result: roundNum(baseNpvMln * 1.4, 2) }
    : roundNum(baseNpvMln * 1.4, 2);
  sheet3.getCell(`F${cfoRow}`).numFmt = '# ##0.00';
  sheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`F${cfoRow}`).font = { color: { argb: 'FF2E7D32' } };
  sheet3.getCell(`F${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  // Range
  sheet3.getCell(`G${cfoRow}`).value = withFormulas
    ? { formula: `F${cfoRow}-D${cfoRow}`, result: roundNum(baseNpvMln * 0.8, 2) }
    : roundNum(baseNpvMln * 0.8, 2);
  sheet3.getCell(`G${cfoRow}`).numFmt = '# ##0.00';
  sheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`G${cfoRow}`).font = { bold: true };

  // Row 2: CAPEX - ±20%
  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = 'CAPEX (koszt inwestycji)';
  sheet3.getCell(`C${cfoRow}`).value = '±20%';
  sheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };
  // Pessimistic: NPV - CAPEX*0.2 (higher CAPEX)
  sheet3.getCell(`D${cfoRow}`).value = withFormulas
    ? { formula: `${s2}M${lastDataRow}-${s2}F10*0.2/1000`, result: roundNum(baseNpvMln - investment / 1000000 * 0.2, 2) }
    : roundNum(baseNpvMln - investment / 1000000 * 0.2, 2);
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
  // Optimistic: NPV + CAPEX*0.2 (lower CAPEX)
  sheet3.getCell(`F${cfoRow}`).value = withFormulas
    ? { formula: `${s2}M${lastDataRow}+${s2}F10*0.2/1000`, result: roundNum(baseNpvMln + investment / 1000000 * 0.2, 2) }
    : roundNum(baseNpvMln + investment / 1000000 * 0.2, 2);
  sheet3.getCell(`F${cfoRow}`).numFmt = '# ##0.00';
  sheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`F${cfoRow}`).font = { color: { argb: 'FF2E7D32' } };
  sheet3.getCell(`F${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  // Range
  sheet3.getCell(`G${cfoRow}`).value = withFormulas
    ? { formula: `F${cfoRow}-D${cfoRow}`, result: roundNum(investment / 1000000 * 0.4, 2) }
    : roundNum(investment / 1000000 * 0.4, 2);
  sheet3.getCell(`G${cfoRow}`).numFmt = '# ##0.00';
  sheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`G${cfoRow}`).font = { bold: true };

  // Row 3: Yield PV - ±15%
  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = 'Yield PV (produkcja)';
  sheet3.getCell(`C${cfoRow}`).value = '±15%';
  sheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };
  // Pessimistic: NPV * 0.85
  sheet3.getCell(`D${cfoRow}`).value = withFormulas
    ? { formula: `${s2}M${lastDataRow}*0.85`, result: roundNum(baseNpvMln * 0.85, 2) }
    : roundNum(baseNpvMln * 0.85, 2);
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
  // Optimistic: NPV * 1.15
  sheet3.getCell(`F${cfoRow}`).value = withFormulas
    ? { formula: `${s2}M${lastDataRow}*1.15`, result: roundNum(baseNpvMln * 1.15, 2) }
    : roundNum(baseNpvMln * 1.15, 2);
  sheet3.getCell(`F${cfoRow}`).numFmt = '# ##0.00';
  sheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`F${cfoRow}`).font = { color: { argb: 'FF2E7D32' } };
  sheet3.getCell(`F${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  // Range
  sheet3.getCell(`G${cfoRow}`).value = withFormulas
    ? { formula: `F${cfoRow}-D${cfoRow}`, result: roundNum(baseNpvMln * 0.3, 2) }
    : roundNum(baseNpvMln * 0.3, 2);
  sheet3.getCell(`G${cfoRow}`).numFmt = '# ##0.00';
  sheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`G${cfoRow}`).font = { bold: true };

  // Row 4: Stopa dyskontowa - ±2pp
  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = 'Stopa dyskontowa';
  sheet3.getCell(`C${cfoRow}`).value = '±2pp';
  sheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };
  // Pessimistic: NPV * 0.85 (higher discount)
  sheet3.getCell(`D${cfoRow}`).value = withFormulas
    ? { formula: `${s2}M${lastDataRow}*0.85`, result: roundNum(baseNpvMln * 0.85, 2) }
    : roundNum(baseNpvMln * 0.85, 2);
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
  // Optimistic: NPV * 1.20 (lower discount)
  sheet3.getCell(`F${cfoRow}`).value = withFormulas
    ? { formula: `${s2}M${lastDataRow}*1.2`, result: roundNum(baseNpvMln * 1.2, 2) }
    : roundNum(baseNpvMln * 1.2, 2);
  sheet3.getCell(`F${cfoRow}`).numFmt = '# ##0.00';
  sheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`F${cfoRow}`).font = { color: { argb: 'FF2E7D32' } };
  sheet3.getCell(`F${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  // Range
  sheet3.getCell(`G${cfoRow}`).value = withFormulas
    ? { formula: `F${cfoRow}-D${cfoRow}`, result: roundNum(baseNpvMln * 0.35, 2) }
    : roundNum(baseNpvMln * 0.35, 2);
  sheet3.getCell(`G${cfoRow}`).numFmt = '# ##0.00';
  sheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };
  sheet3.getCell(`G${cfoRow}`).font = { bold: true };

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

  cfoRow += 2;
  const yieldVariations = [-0.15, -0.10, -0.05, 0, 0.05, 0.10, 0.15];
  const priceVariations = [-0.20, -0.10, 0, 0.10, 0.20];

  // Header row
  sheet3.getCell(`B${cfoRow}`).value = 'NPV [tys. PLN]';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
  sheet3.mergeCells(`C${cfoRow}:I${cfoRow}`);
  sheet3.getCell(`C${cfoRow}`).value = '← Yield PV →';
  sheet3.getCell(`C${cfoRow}`).font = { bold: true, size: 10 };
  sheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };

  cfoRow++;
  sheet3.getCell(`B${cfoRow}`).value = 'Cena sieci ↓';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
  sheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'right' };
  yieldVariations.forEach((yv, i) => {
    sheet3.getCell(cfoRow, 3 + i).value = `${yv >= 0 ? '+' : ''}${(yv * 100).toFixed(0)}%`;
    sheet3.getCell(cfoRow, 3 + i).font = { bold: true, size: 9 };
    sheet3.getCell(cfoRow, 3 + i).alignment = { horizontal: 'center' };
    sheet3.getCell(cfoRow, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  // Matrix data - NPV in tys. PLN
  // Formula: (NPV_mln*1000 + CAPEX_tys) * (1+priceVar) * (1+yieldVar) - CAPEX_tys
  // Where NPV_mln = 'CAPEX Rok po Roku'!L{lastDataRow}, CAPEX_tys = 'CAPEX Rok po Roku'!E10
  const baseNpvTys = npvValue / 1000;
  priceVariations.forEach(pv => {
    cfoRow++;
    sheet3.getCell(`B${cfoRow}`).value = `${pv >= 0 ? '+' : ''}${(pv * 100).toFixed(0)}%`;
    sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
    sheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'right' };
    sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    yieldVariations.forEach((yv, i) => {
      // NPV = -CAPEX + PV(savings), savings proportional to price and yield
      const savingsMultiplier = (1 + pv) * (1 + yv);
      const adjNpv = (baseNpvTys + (investment / 1000)) * savingsMultiplier - (investment / 1000);

      const cell = sheet3.getCell(cfoRow, 3 + i);

      // Formula: (NPV*1000 + CAPEX) * priceMultiplier * yieldMultiplier - CAPEX
      if (withFormulas) {
        const priceMultiplier = (1 + pv).toFixed(2);
        const yieldMultiplier = (1 + yv).toFixed(2);
        cell.value = {
          formula: `(${s2}M${lastDataRow}*1000+${s2}F10)*${priceMultiplier}*${yieldMultiplier}-${s2}F10`,
          result: roundNum(adjNpv, 0)
        };
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
  const safetyMarginPct = (totalEnergyPrice - lcoeValue) / totalEnergyPrice;

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
  sheet3.getCell(`B${cfoRow}`).value = 'Obecna cena energii z sieci';
  sheet3.getCell(`B${cfoRow}`).font = { bold: true };
  sheet3.getCell(`C${cfoRow}`).value = withFormulas
    ? { formula: bePriceFormula, result: roundNum(totalEnergyPrice, 0) }
    : roundNum(totalEnergyPrice, 0);
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
  const gridCost30Years = baseAutoconsumptionMwh * totalEnergyPrice * analysisPeriod / 1000; // tys. PLN (simplified)

  // Decision criteria
  const decisionRows = [
    { criterion: 'Nakład inwestycyjny', capex: `${roundNum(investment / 1000, 0)} tys. PLN`, statusQuo: '0 PLN', winner: 'Status Quo' },
    { criterion: `Koszt energii ${analysisPeriod} lat`, capex: '0 tys.', statusQuo: `${roundNum(gridCost30Years, 0)} tys.`, winner: 'CAPEX' },
    { criterion: `Oszczędności ${analysisPeriod} lat`, capex: `${roundNum(totalSavings / 1000, 0)} tys. PLN`, statusQuo: '0 PLN', winner: 'CAPEX' },
    { criterion: 'NPV (wartość bieżąca)', capex: `${roundNum(npvValue / 1000, 0)} tys. PLN`, statusQuo: '0 PLN', winner: npvValue > 0 ? 'CAPEX' : 'Status Quo' },
    { criterion: 'Ryzyko cenowe', capex: 'Częściowe zabezp.', statusQuo: '100% ekspozycji', winner: 'CAPEX' },
    { criterion: 'Własność aktywów', capex: 'TAK', statusQuo: 'NIE', winner: 'CAPEX' },
    { criterion: 'Zielona energia', capex: 'TAK', statusQuo: 'NIE', winner: 'CAPEX' },
    { criterion: `Redukcja CO₂ (${analysisPeriod} lat)`, capex: `${roundNum(totalCO2Tons, 0)} ton`, statusQuo: '0 ton', winner: 'CAPEX' }
  ];

  let capexWins = 0;
  decisionRows.forEach(row => {
    cfoRow++;
    sheet3.getCell(`B${cfoRow}`).value = row.criterion;
    sheet3.getCell(`B${cfoRow}`).font = { color: { argb: 'FF424242' } };
    sheet3.getCell(`C${cfoRow}`).value = row.capex;
    sheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
    sheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };
    sheet3.getCell(`D${cfoRow}`).value = row.statusQuo;
    sheet3.getCell(`D${cfoRow}`).font = { color: { argb: 'FFC62828' } };
    sheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };
    sheet3.getCell(`E${cfoRow}`).value = row.winner;
    sheet3.getCell(`E${cfoRow}`).font = { bold: true, color: { argb: row.winner === 'CAPEX' ? 'FF2E7D32' : 'FFE65100' } };
    sheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };

    if (row.winner === 'CAPEX') capexWins++;

    for (let c = 2; c <= 5; c++) {
      sheet3.getRow(cfoRow).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });

  // Final recommendation
  cfoRow += 2;
  const recommendation = capexWins >= 5 ? 'CAPEX' : 'Status Quo';
  sheet3.mergeCells(`B${cfoRow}:E${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = `✅ REKOMENDACJA: Inwestycja CAPEX - wygrywa w ${capexWins} z ${decisionRows.length} kryteriów`;
  sheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: recommendation === 'CAPEX' ? 'FF2E7D32' : 'FFC62828' } };
  sheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: recommendation === 'CAPEX' ? 'FFE8F5E9' : 'FFFFEBEE' } };
  sheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'center' };

  cfoRow++;
  sheet3.mergeCells(`B${cfoRow}:E${cfoRow}`);
  sheet3.getCell(`B${cfoRow}`).value = `NPV = ${roundNum(npvValue / 1000, 0)} tys. PLN | IRR = ${roundNum(irrValue * 100, 1)}% | Zwrot = ${roundNum(simplePaybackValue, 1)} lat`;
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
  sheet4.getCell('B1').value = 'CAPEX ANALYSIS - Investor Perspective';
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
    summaryRowsEng.push(['NPV [M PLN]:', { formula: "'CAPEX Year by Year'!M" + lastDataRow }]);
    summaryRowsEng.push(['IRR [%]:', roundNum(centralizedCalc.capex.irr * 100, 1)]);
    summaryRowsEng.push(['ROI [%]:', { formula: "(SUM('CAPEX Year by Year'!L" + dataStartRow + ":L" + lastDataRow + ")*1000-'CAPEX Year by Year'!F10*1000)/('CAPEX Year by Year'!F10*1000)*100" }]);
    summaryRowsEng.push(['Simple payback [years]:', { formula: "'CAPEX Year by Year'!F10*1000/AVERAGE('CAPEX Year by Year'!L" + dataStartRow + ":L" + (dataStartRow + 4) + ")/1000" }]);
  } else {
    summaryRowsEng.push(['NPV [M PLN]:', roundNum(centralizedCalc.capex.npv / 1000000, 2)]);
    summaryRowsEng.push(['IRR [%]:', roundNum(centralizedCalc.capex.irr * 100, 1)]);
    summaryRowsEng.push(['ROI [%]:', roundNum(roi, 1)]);
    summaryRowsEng.push(['Simple payback [years]:', roundNum(centralizedCalc.capex.simplePayback, 1)]);
  }
  summaryRowsEng.push(['Discounted payback [years]:', centralizedCalc.capex.discountedPayback ? roundNum(centralizedCalc.capex.discountedPayback, 1) : 'Beyond analysis period']);
  summaryRowsEng.push(['LCOE [PLN/MWh]:', roundNum(centralizedCalc.capex.lcoe, 0)]);

  summaryRowsEng.forEach((row, idx) => {
    const excelRow = sheet4.getRow(idx + 5);
    excelRow.getCell(2).value = row[0];
    if (typeof row[1] === 'object' && row[1].formula) {
      excelRow.getCell(3).value = row[1];
    } else {
      excelRow.getCell(3).value = row[1];
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
  sheet5.getCell('B1').value = 'CAPEX YEAR BY YEAR ANALYSIS WITH NPV';
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
    { row: 12, label: 'Base grid price [PLN/MWh]:', value: roundNum(totalEnergyPrice, 2), numFmt: '# ##0.00' },
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
  const headersEng = ['Year', 'PV Deg [%]', 'BESS Deg [%]', 'Consump. [MWh]', 'Grid Cost [k]',
    'Self PV [MWh]', 'Self BESS [MWh]', 'Total Self [MWh]', 'Grid Equiv. [k]',
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
    const inflFactor = Math.pow(1 + inflationRate, year);
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
      row.getCell(6).value = { formula: '$F$13*$F$12*POWER(1+$F$5,' + year + ')/1000', result: annualConsumptionMwh * totalEnergyPrice * inflFactor / 1000 };
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
      row.getCell(10).value = { formula: 'I' + dataRowEng + '*$F$12*POWER(1+$F$5,' + year + ')/1000', result: cf.savings / 1000 };
      row.getCell(10).numFmt = numFmtStandard;
      row.getCell(10).alignment = { horizontal: 'right', indent: 1 };
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
      row.getCell(6).value = roundNum(annualConsumptionMwh * totalEnergyPrice * inflFactor / 1000, 2);
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

  // DPP Row Highlighting
  const dppYearEng = centralizedCalc.capex.discountedPayback;
  if (dppYearEng && dppYearEng <= analysisPeriod) {
    const dppRowNumberEng = 17 + Math.ceil(dppYearEng);
    const dppRowObjEng = sheet5.getRow(dppRowNumberEng);
    const dppFillEng = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF8E1' } };
    const dppBorderEng = {
      top: { style: 'medium', color: { argb: 'FFFFC107' } },
      bottom: { style: 'medium', color: { argb: 'FFFFC107' } }
    };
    for (let col = 2; col <= 13; col++) {
      const cell = dppRowObjEng.getCell(col);
      cell.fill = dppFillEng;
      cell.border = dppBorderEng;
    }
    dppRowObjEng.getCell(2).font = { bold: true, color: { argb: 'FFFF8F00' } };
  }

  sheet5.views = [{ state: 'frozen', ySplit: 16, xSplit: 0, showGridLines: false, showRowColHeaders: false }];

  // Summary section below data
  const summaryStartRowEng = lastDataRow + 3;
  sheet5.getCell('C' + summaryStartRowEng).value = 'KPI SUMMARY';
  sheet5.getCell('C' + summaryStartRowEng).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  sheet5.mergeCells('C' + summaryStartRowEng + ':H' + summaryStartRowEng);
  sheet5.getCell('C' + summaryStartRowEng).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

  const irrFormulaEng = 'IRR(L17:L' + lastDataRow + ')*100';
  const simplePaybackFormulaEng = '$F$10/(AVERAGE(L' + dataStartRow + ':L' + Math.min(dataStartRow + 4, lastDataRow) + '))';
  const dppFormulaEng = 'SUMPRODUCT((M' + dataStartRow + ':M' + lastDataRow + '<0)*1)+1';
  const lcoeFormulaEng = '($F$10*1000+SUMPRODUCT(K' + dataStartRow + ':K' + lastDataRow + '/POWER(1+$F$4,B' + dataStartRow + ':B' + lastDataRow + ')))/SUMPRODUCT(I' + dataStartRow + ':I' + lastDataRow + '/POWER(1+$F$4,B' + dataStartRow + ':B' + lastDataRow + '))';

  const kpiRowsEng = [
    ['CAPEX (investment):', withFormulas ? { formula: '$F$10' } : roundNum(investment / 1000, 2), 'k PLN', '= Initial investment', '# ##0.00'],
    ['Total savings:', withFormulas ? { formula: 'SUM(L' + dataStartRow + ':L' + lastDataRow + ')' } : roundNum(cashFlows.reduce((s, cf) => s + cf.net_cash_flow, 0) / 1000, 2), 'k PLN', '= Sum of column L', '# ##0.00'],
    ['NPV:', withFormulas ? { formula: 'M' + lastDataRow } : roundNum(centralizedCalc.capex.npv / 1000000, 3), 'M PLN', '= Net Present Value', '# ##0.000'],
    ['IRR:', withFormulas ? { formula: irrFormulaEng } : roundNum(centralizedCalc.capex.irr * 100, 2), '%', '= Internal Rate of Return', '# ##0.00'],
    ['ROI:', withFormulas ? { formula: '(F' + (summaryStartRowEng + 2) + '-F' + (summaryStartRowEng + 1) + ')/F' + (summaryStartRowEng + 1) + '*100' } : roundNum(roi, 2), '%', '= (Savings - CAPEX) / CAPEX', '# ##0.00'],
    ['Simple Payback:', withFormulas ? { formula: simplePaybackFormulaEng } : roundNum(centralizedCalc.capex.simplePayback, 2), 'years', '= CAPEX / avg annual savings', '# ##0.00'],
    ['Discounted Payback (DPP):', withFormulas ? { formula: dppFormulaEng } : (centralizedCalc.capex.discountedPayback ? roundNum(centralizedCalc.capex.discountedPayback, 2) : '-'), 'years', '= Year when NPV ≥ 0', '# ##0.00'],
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
  sheet6.getCell('B1').value = 'CFO ANALYSIS - CAPEX Model (Investor)';
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
  sheet6.getCell(`D${cfoRowEng}`).value = 'Energy price [PLN/MWh]';
  sheet6.getCell(`E${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}F12`, result: roundNum(totalEnergyPrice, 0) }
    : roundNum(totalEnergyPrice, 0);
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
  const kpiDppFormulaEng = `SUMPRODUCT((${s5}M${dataStartRow}:${s5}M${lastDataRow}<0)*1)+1`;
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
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: kpiDppFormulaEng, result: dppValue ? roundNum(dppValue, 1) : analysisPeriod + 1 }
    : (dppValue ? roundNum(dppValue, 1) : 'Beyond period');
  sheet6.getCell(`C${cfoRowEng}`).numFmt = dppValue ? '0.0' : '@';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  sheet6.getCell(`D${cfoRowEng}`).value = dppValue ? 'years' : '';
  sheet6.mergeCells(`E${cfoRowEng}:G${cfoRowEng}`);
  sheet6.getCell(`E${cfoRowEng}`).value = 'Year when cumulative NPV ≥ 0';
  sheet6.getCell(`E${cfoRowEng}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = '⚡ LCOE (energy cost)';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: kpiLcoeFormulaEng, result: roundNum(lcoeValue, 0) }
    : roundNum(lcoeValue, 0);
  sheet6.getCell(`C${cfoRowEng}`).numFmt = '# ##0';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: lcoeValue < totalEnergyPrice ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  sheet6.getCell(`D${cfoRowEng}`).value = 'PLN/MWh';
  sheet6.mergeCells(`E${cfoRowEng}:G${cfoRowEng}`);
  sheet6.getCell(`E${cfoRowEng}`).value = lcoeValue < totalEnergyPrice ? `LCOE < grid price (${roundNum(totalEnergyPrice, 0)} PLN/MWh)` : `LCOE > grid price`;
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

  // Row 1: Grid price - ±20%
  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'Grid price';
  sheet6.getCell(`C${cfoRowEng}`).value = '±20%';
  sheet6.getCell(`C${cfoRowEng}`).alignment = { horizontal: 'center' };
  // Pessimistic: NPV * 0.6
  sheet6.getCell(`D${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}M${lastDataRow}*0.6`, result: roundNum(baseNpvMln * 0.6, 2) }
    : roundNum(baseNpvMln * 0.6, 2);
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
  // Optimistic: NPV * 1.4
  sheet6.getCell(`F${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}M${lastDataRow}*1.4`, result: roundNum(baseNpvMln * 1.4, 2) }
    : roundNum(baseNpvMln * 1.4, 2);
  sheet6.getCell(`F${cfoRowEng}`).numFmt = '# ##0.00';
  sheet6.getCell(`F${cfoRowEng}`).alignment = { horizontal: 'center' };
  sheet6.getCell(`F${cfoRowEng}`).font = { color: { argb: 'FF2E7D32' } };
  sheet6.getCell(`F${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  // Range
  sheet6.getCell(`G${cfoRowEng}`).value = withFormulas
    ? { formula: `F${cfoRowEng}-D${cfoRowEng}`, result: roundNum(baseNpvMln * 0.8, 2) }
    : roundNum(baseNpvMln * 0.8, 2);
  sheet6.getCell(`G${cfoRowEng}`).numFmt = '# ##0.00';
  sheet6.getCell(`G${cfoRowEng}`).alignment = { horizontal: 'center' };
  sheet6.getCell(`G${cfoRowEng}`).font = { bold: true };

  // Row 2: CAPEX - ±20%
  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'CAPEX (investment cost)';
  sheet6.getCell(`C${cfoRowEng}`).value = '±20%';
  sheet6.getCell(`C${cfoRowEng}`).alignment = { horizontal: 'center' };
  // Pessimistic: NPV - CAPEX*0.2 (higher CAPEX)
  sheet6.getCell(`D${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}M${lastDataRow}-${s5}F10*0.2/1000`, result: roundNum(baseNpvMln - investment / 1000000 * 0.2, 2) }
    : roundNum(baseNpvMln - investment / 1000000 * 0.2, 2);
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
  // Optimistic: NPV + CAPEX*0.2 (lower CAPEX)
  sheet6.getCell(`F${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}M${lastDataRow}+${s5}F10*0.2/1000`, result: roundNum(baseNpvMln + investment / 1000000 * 0.2, 2) }
    : roundNum(baseNpvMln + investment / 1000000 * 0.2, 2);
  sheet6.getCell(`F${cfoRowEng}`).numFmt = '# ##0.00';
  sheet6.getCell(`F${cfoRowEng}`).alignment = { horizontal: 'center' };
  sheet6.getCell(`F${cfoRowEng}`).font = { color: { argb: 'FF2E7D32' } };
  sheet6.getCell(`F${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  // Range
  sheet6.getCell(`G${cfoRowEng}`).value = withFormulas
    ? { formula: `F${cfoRowEng}-D${cfoRowEng}`, result: roundNum(investment / 1000000 * 0.4, 2) }
    : roundNum(investment / 1000000 * 0.4, 2);
  sheet6.getCell(`G${cfoRowEng}`).numFmt = '# ##0.00';
  sheet6.getCell(`G${cfoRowEng}`).alignment = { horizontal: 'center' };
  sheet6.getCell(`G${cfoRowEng}`).font = { bold: true };

  // Row 3: Yield PV - ±15%
  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'PV Yield (production)';
  sheet6.getCell(`C${cfoRowEng}`).value = '±15%';
  sheet6.getCell(`C${cfoRowEng}`).alignment = { horizontal: 'center' };
  // Pessimistic: NPV * 0.85
  sheet6.getCell(`D${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}M${lastDataRow}*0.85`, result: roundNum(baseNpvMln * 0.85, 2) }
    : roundNum(baseNpvMln * 0.85, 2);
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
  // Optimistic: NPV * 1.15
  sheet6.getCell(`F${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}M${lastDataRow}*1.15`, result: roundNum(baseNpvMln * 1.15, 2) }
    : roundNum(baseNpvMln * 1.15, 2);
  sheet6.getCell(`F${cfoRowEng}`).numFmt = '# ##0.00';
  sheet6.getCell(`F${cfoRowEng}`).alignment = { horizontal: 'center' };
  sheet6.getCell(`F${cfoRowEng}`).font = { color: { argb: 'FF2E7D32' } };
  sheet6.getCell(`F${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  // Range
  sheet6.getCell(`G${cfoRowEng}`).value = withFormulas
    ? { formula: `F${cfoRowEng}-D${cfoRowEng}`, result: roundNum(baseNpvMln * 0.3, 2) }
    : roundNum(baseNpvMln * 0.3, 2);
  sheet6.getCell(`G${cfoRowEng}`).numFmt = '# ##0.00';
  sheet6.getCell(`G${cfoRowEng}`).alignment = { horizontal: 'center' };
  sheet6.getCell(`G${cfoRowEng}`).font = { bold: true };

  // Row 4: Discount rate - ±2pp
  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'Discount rate';
  sheet6.getCell(`C${cfoRowEng}`).value = '±2pp';
  sheet6.getCell(`C${cfoRowEng}`).alignment = { horizontal: 'center' };
  // Pessimistic: NPV * 0.85 (higher discount)
  sheet6.getCell(`D${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}M${lastDataRow}*0.85`, result: roundNum(baseNpvMln * 0.85, 2) }
    : roundNum(baseNpvMln * 0.85, 2);
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
  // Optimistic: NPV * 1.20 (lower discount)
  sheet6.getCell(`F${cfoRowEng}`).value = withFormulas
    ? { formula: `${s5}M${lastDataRow}*1.2`, result: roundNum(baseNpvMln * 1.2, 2) }
    : roundNum(baseNpvMln * 1.2, 2);
  sheet6.getCell(`F${cfoRowEng}`).numFmt = '# ##0.00';
  sheet6.getCell(`F${cfoRowEng}`).alignment = { horizontal: 'center' };
  sheet6.getCell(`F${cfoRowEng}`).font = { color: { argb: 'FF2E7D32' } };
  sheet6.getCell(`F${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  // Range
  sheet6.getCell(`G${cfoRowEng}`).value = withFormulas
    ? { formula: `F${cfoRowEng}-D${cfoRowEng}`, result: roundNum(baseNpvMln * 0.35, 2) }
    : roundNum(baseNpvMln * 0.35, 2);
  sheet6.getCell(`G${cfoRowEng}`).numFmt = '# ##0.00';
  sheet6.getCell(`G${cfoRowEng}`).alignment = { horizontal: 'center' };
  sheet6.getCell(`G${cfoRowEng}`).font = { bold: true };

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

  cfoRowEng += 2;
  const yieldVariationsEng = [-0.15, -0.10, -0.05, 0, 0.05, 0.10, 0.15];
  const priceVariationsEng = [-0.20, -0.10, 0, 0.10, 0.20];

  // Header row
  sheet6.getCell(`B${cfoRowEng}`).value = 'NPV [k PLN]';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 9 };
  sheet6.mergeCells(`C${cfoRowEng}:I${cfoRowEng}`);
  sheet6.getCell(`C${cfoRowEng}`).value = '← PV Yield →';
  sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, size: 10 };
  sheet6.getCell(`C${cfoRowEng}`).alignment = { horizontal: 'center' };

  cfoRowEng++;
  sheet6.getCell(`B${cfoRowEng}`).value = 'Grid price ↓';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 9 };
  sheet6.getCell(`B${cfoRowEng}`).alignment = { horizontal: 'right' };
  yieldVariationsEng.forEach((yv, i) => {
    sheet6.getCell(cfoRowEng, 3 + i).value = `${yv >= 0 ? '+' : ''}${(yv * 100).toFixed(0)}%`;
    sheet6.getCell(cfoRowEng, 3 + i).font = { bold: true, size: 9 };
    sheet6.getCell(cfoRowEng, 3 + i).alignment = { horizontal: 'center' };
    sheet6.getCell(cfoRowEng, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  // Matrix data - NPV in k PLN
  priceVariationsEng.forEach(pv => {
    cfoRowEng++;
    sheet6.getCell(`B${cfoRowEng}`).value = `${pv >= 0 ? '+' : ''}${(pv * 100).toFixed(0)}%`;
    sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 9 };
    sheet6.getCell(`B${cfoRowEng}`).alignment = { horizontal: 'right' };
    sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    yieldVariationsEng.forEach((yv, i) => {
      const savingsMultiplier = (1 + pv) * (1 + yv);
      const adjNpv = (baseNpvTys + (investment / 1000)) * savingsMultiplier - (investment / 1000);

      const cell = sheet6.getCell(cfoRowEng, 3 + i);

      if (withFormulas) {
        const priceMultiplier = (1 + pv).toFixed(2);
        const yieldMultiplier = (1 + yv).toFixed(2);
        cell.value = {
          formula: `(${s5}M${lastDataRow}*1000+${s5}F10)*${priceMultiplier}*${yieldMultiplier}-${s5}F10`,
          result: roundNum(adjNpv, 0)
        };
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
  const safetyMarginPctEng = (totalEnergyPrice - lcoeValue) / totalEnergyPrice;

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
  sheet6.getCell(`B${cfoRowEng}`).value = 'Current grid energy price';
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true };
  sheet6.getCell(`C${cfoRowEng}`).value = withFormulas
    ? { formula: bePriceFormulaEng, result: roundNum(totalEnergyPrice, 0) }
    : roundNum(totalEnergyPrice, 0);
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

  const gridCost30YearsEng = baseAutoconsumptionMwh * totalEnergyPrice * analysisPeriod / 1000;

  const decisionRowsEng = [
    { criterion: 'Investment outlay', capex: `${roundNum(investment / 1000, 0)} k PLN`, statusQuo: '0 PLN', winner: 'Status Quo' },
    { criterion: `Energy cost ${analysisPeriod} years`, capex: '0 k', statusQuo: `${roundNum(gridCost30YearsEng, 0)} k`, winner: 'CAPEX' },
    { criterion: `Savings ${analysisPeriod} years`, capex: `${roundNum(totalSavings / 1000, 0)} k PLN`, statusQuo: '0 PLN', winner: 'CAPEX' },
    { criterion: 'NPV (present value)', capex: `${roundNum(npvValue / 1000, 0)} k PLN`, statusQuo: '0 PLN', winner: npvValue > 0 ? 'CAPEX' : 'Status Quo' },
    { criterion: 'Price risk', capex: 'Partial hedge', statusQuo: '100% exposure', winner: 'CAPEX' },
    { criterion: 'Asset ownership', capex: 'YES', statusQuo: 'NO', winner: 'CAPEX' },
    { criterion: 'Green energy', capex: 'YES', statusQuo: 'NO', winner: 'CAPEX' },
    { criterion: `CO₂ reduction (${analysisPeriod} years)`, capex: `${roundNum(totalCO2Tons, 0)} tons`, statusQuo: '0 tons', winner: 'CAPEX' }
  ];

  let capexWinsEng = 0;
  decisionRowsEng.forEach(row => {
    cfoRowEng++;
    sheet6.getCell(`B${cfoRowEng}`).value = row.criterion;
    sheet6.getCell(`B${cfoRowEng}`).font = { color: { argb: 'FF424242' } };
    sheet6.getCell(`C${cfoRowEng}`).value = row.capex;
    sheet6.getCell(`C${cfoRowEng}`).font = { bold: true, color: { argb: 'FF1565C0' } };
    sheet6.getCell(`C${cfoRowEng}`).alignment = { horizontal: 'center' };
    sheet6.getCell(`D${cfoRowEng}`).value = row.statusQuo;
    sheet6.getCell(`D${cfoRowEng}`).font = { color: { argb: 'FFC62828' } };
    sheet6.getCell(`D${cfoRowEng}`).alignment = { horizontal: 'center' };
    sheet6.getCell(`E${cfoRowEng}`).value = row.winner;
    sheet6.getCell(`E${cfoRowEng}`).font = { bold: true, color: { argb: row.winner === 'CAPEX' ? 'FF2E7D32' : 'FFE65100' } };
    sheet6.getCell(`E${cfoRowEng}`).alignment = { horizontal: 'center' };

    if (row.winner === 'CAPEX') capexWinsEng++;

    for (let c = 2; c <= 5; c++) {
      sheet6.getRow(cfoRowEng).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });

  cfoRowEng += 2;
  const recommendationEng = capexWinsEng >= 5 ? 'CAPEX' : 'Status Quo';
  sheet6.mergeCells(`B${cfoRowEng}:E${cfoRowEng}`);
  sheet6.getCell(`B${cfoRowEng}`).value = `✅ RECOMMENDATION: CAPEX Investment - wins in ${capexWinsEng} of ${decisionRowsEng.length} criteria`;
  sheet6.getCell(`B${cfoRowEng}`).font = { bold: true, size: 12, color: { argb: recommendationEng === 'CAPEX' ? 'FF2E7D32' : 'FFC62828' } };
  sheet6.getCell(`B${cfoRowEng}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: recommendationEng === 'CAPEX' ? 'FFE8F5E9' : 'FFFFEBEE' } };
  sheet6.getCell(`B${cfoRowEng}`).alignment = { horizontal: 'center' };

  cfoRowEng++;
  sheet6.mergeCells(`B${cfoRowEng}:E${cfoRowEng}`);
  sheet6.getCell(`B${cfoRowEng}`).value = `NPV = ${roundNum(npvValue / 1000, 0)} k PLN | IRR = ${roundNum(irrValue * 100, 1)}% | Payback = ${roundNum(simplePaybackValue, 1)} years`;
  sheet6.getCell(`B${cfoRowEng}`).font = { italic: true, size: 10, color: { argb: 'FF1565C0' } };
  sheet6.getCell(`B${cfoRowEng}`).alignment = { horizontal: 'center' };

  console.log('✅ English sheets added (CAPEX Summary, CAPEX Year by Year, CFO Analysis)');

  // Generate filename
  const dateStr = new Date().toISOString().split('T')[0];
  const filename = withFormulas
    ? `CAPEX_Analiza_${currentVariant}_${capacityKwp}kWp_${dateStr}_FORMULY.xlsx`
    : `CAPEX_Analiza_${currentVariant}_${capacityKwp}kWp_${dateStr}.xlsx`;

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
}

async function exportCapexToExcelWithFormulas() {
  await exportCapexToExcel(true);
}

// Export CAPEX functions to window for HTML onclick handlers
window.exportCapexToExcel = exportCapexToExcel;
window.exportCapexToExcelWithFormulas = exportCapexToExcelWithFormulas;

// Note: English sheets (CAPEX Summary, CAPEX Year by Year, CFO Analysis)
// are now automatically included in the main export function above.
