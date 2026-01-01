/**
 * Report URL Builder Module (v2.4.0)
 *
 * Builds report download URLs with query parameters.
 * Can be used standalone or imported as a module.
 */

(function(global) {
  'use strict';

  /**
   * Build report URL with query parameters
   * @param {string} runId - Run ID (UUID)
   * @param {string} format - Format (pdf, xlsx, zip)
   * @param {object} options - Report options
   * @param {string} [options.profile] - Report profile (client or engineering)
   * @param {string} [options.client_name] - Client name for branding
   * @param {string} [options.site_name] - Site name for branding
   * @param {string} [options.report_title] - Report title
   * @param {string} [options.notes] - Additional notes
   * @returns {string} Full URL with query parameters
   */
  function buildReportUrl(runId, format, options = {}) {
    if (!runId || typeof runId !== 'string') {
      throw new Error('runId is required and must be a string');
    }

    const validFormats = ['pdf', 'xlsx', 'zip'];
    if (!format || !validFormats.includes(format)) {
      throw new Error(`format must be one of: ${validFormats.join(', ')}`);
    }

    const baseUrl = `/api/bess-dispatch/runs/${runId}/report.${format}`;
    const params = new URLSearchParams();

    // Profile - only add if not default 'client'
    if (options.profile && options.profile !== 'client') {
      params.append('profile', options.profile);
    }

    // Branding fields
    if (options.client_name && typeof options.client_name === 'string') {
      const trimmed = options.client_name.trim();
      if (trimmed) {
        params.append('client_name', trimmed);
      }
    }

    if (options.site_name && typeof options.site_name === 'string') {
      const trimmed = options.site_name.trim();
      if (trimmed) {
        params.append('site_name', trimmed);
      }
    }

    if (options.report_title && typeof options.report_title === 'string') {
      const trimmed = options.report_title.trim();
      if (trimmed) {
        params.append('report_title', trimmed);
      }
    }

    if (options.notes && typeof options.notes === 'string') {
      const trimmed = options.notes.trim();
      if (trimmed) {
        params.append('notes', trimmed);
      }
    }

    const queryString = params.toString();
    return queryString ? `${baseUrl}?${queryString}` : baseUrl;
  }

  /**
   * Build portfolio report URL
   * @param {string[]} runIds - Array of run IDs
   * @returns {string} Portfolio report endpoint URL
   */
  function buildPortfolioReportUrl(runIds) {
    if (!Array.isArray(runIds) || runIds.length === 0) {
      throw new Error('runIds must be a non-empty array');
    }
    return '/api/bess-dispatch/portfolio/report.zip';
  }

  /**
   * Validate run ID format (UUID v4)
   * @param {string} runId - Run ID to validate
   * @returns {boolean} True if valid UUID format
   */
  function isValidRunId(runId) {
    if (!runId || typeof runId !== 'string') return false;
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    return uuidRegex.test(runId);
  }

  // Export for different module systems
  const exports = {
    buildReportUrl,
    buildPortfolioReportUrl,
    isValidRunId,
  };

  // CommonJS
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = exports;
  }

  // AMD
  if (typeof define === 'function' && define.amd) {
    define([], function() { return exports; });
  }

  // Browser global
  if (typeof global !== 'undefined') {
    global.ReportUrlBuilder = exports;
  }

})(typeof window !== 'undefined' ? window : global);
