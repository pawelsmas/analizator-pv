#!/usr/bin/env node
/**
 * Simple JavaScript syntax checker
 * Validates all JS files in frontend services can be parsed
 */

const fs = require('fs');
const path = require('path');

const servicesDir = path.join(__dirname, '..', 'services');

let errors = 0;
let checked = 0;

function checkFile(filePath) {
  try {
    const content = fs.readFileSync(filePath, 'utf8');
    // Try to parse as JavaScript
    new Function(content);
    checked++;
    console.log(`✅ ${path.relative(servicesDir, filePath)}`);
  } catch (err) {
    errors++;
    console.log(`❌ ${path.relative(servicesDir, filePath)}`);
    console.log(`   Error: ${err.message.split('\n')[0]}`);
  }
}

function walkDir(dir) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const filePath = path.join(dir, file);
    const stat = fs.statSync(filePath);

    if (stat.isDirectory()) {
      // Skip node_modules and hidden directories
      if (!file.startsWith('.') && file !== 'node_modules') {
        walkDir(filePath);
      }
    } else if (file.endsWith('.js')) {
      checkFile(filePath);
    }
  }
}

console.log('🔍 Checking JavaScript syntax...\n');

// Check all frontend services
const frontendDirs = fs.readdirSync(servicesDir)
  .filter(d => d.startsWith('frontend-'))
  .map(d => path.join(servicesDir, d));

for (const dir of frontendDirs) {
  if (fs.existsSync(dir)) {
    walkDir(dir);
  }
}

console.log('\n' + '='.repeat(50));
console.log(`Checked: ${checked} files`);
console.log(`Errors:  ${errors} files`);
console.log('='.repeat(50));

process.exit(errors > 0 ? 1 : 0);
