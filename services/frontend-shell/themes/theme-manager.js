/**
 * PV Optimizer - Theme Manager
 * Handles theme switching between Classic and iOS styles
 */

const ThemeManager = {
  THEMES: {
    CLASSIC: 'classic',
    IOS: 'ios'
  },

  STORAGE_KEY: 'pv-optimizer-theme',

  /**
   * Initialize theme manager
   */
  init() {
    // Load saved theme or default to classic
    const savedTheme = localStorage.getItem(this.STORAGE_KEY) || this.THEMES.CLASSIC;
    this.setTheme(savedTheme, false);

    // Listen for theme change requests from iframes
    window.addEventListener('message', (event) => {
      if (event.data && event.data.type === 'REQUEST_THEME') {
        this.broadcastTheme();
      }
      if (event.data && event.data.type === 'SET_THEME') {
        this.setTheme(event.data.theme);
      }
    });

    console.log(`🎨 Theme Manager initialized: ${savedTheme}`);
  },

  /**
   * Get current theme
   */
  getCurrentTheme() {
    return document.documentElement.getAttribute('data-theme') || this.THEMES.CLASSIC;
  },

  /**
   * Set theme
   * @param {string} theme - Theme name ('classic' or 'ios')
   * @param {boolean} save - Whether to save to localStorage
   */
  setTheme(theme, save = true) {
    if (!Object.values(this.THEMES).includes(theme)) {
      console.warn(`Unknown theme: ${theme}, falling back to classic`);
      theme = this.THEMES.CLASSIC;
    }

    // Apply to document
    document.documentElement.setAttribute('data-theme', theme);
    document.body.setAttribute('data-theme', theme);

    // Save preference
    if (save) {
      localStorage.setItem(this.STORAGE_KEY, theme);
    }

    // Broadcast to all iframes
    this.broadcastTheme();

    // Dispatch event for local listeners
    window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));

    console.log(`🎨 Theme changed to: ${theme}`);
  },

  /**
   * Toggle between themes
   */
  toggle() {
    const current = this.getCurrentTheme();
    const newTheme = current === this.THEMES.CLASSIC ? this.THEMES.IOS : this.THEMES.CLASSIC;
    this.setTheme(newTheme);
    return newTheme;
  },

  /**
   * Broadcast current theme to all iframes
   */
  broadcastTheme() {
    const theme = this.getCurrentTheme();
    const iframes = document.querySelectorAll('iframe');

    iframes.forEach(iframe => {
      try {
        iframe.contentWindow.postMessage({
          type: 'THEME_CHANGED',
          theme: theme
        }, '*');
      } catch (e) {
        // Cross-origin iframe, ignore
      }
    });
  },

  /**
   * Create theme toggle button HTML
   */
  createToggleButton() {
    const button = document.createElement('button');
    button.className = 'theme-toggle';
    button.innerHTML = `
      <span class="theme-icon-classic">🌙</span>
      <span class="theme-icon-ios">☀️</span>
      <span class="theme-label">
        <span class="label-classic">Tryb iOS</span>
        <span class="label-ios">Tryb Classic</span>
      </span>
    `;
    button.onclick = () => this.toggle();
    return button;
  },

  /**
   * Apply theme styles to an iframe
   * @param {HTMLIFrameElement} iframe
   */
  applyToIframe(iframe) {
    const theme = this.getCurrentTheme();
    try {
      const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
      iframeDoc.documentElement.setAttribute('data-theme', theme);
      iframeDoc.body.setAttribute('data-theme', theme);
    } catch (e) {
      // Cross-origin, use postMessage instead
      iframe.contentWindow.postMessage({
        type: 'THEME_CHANGED',
        theme: theme
      }, '*');
    }
  }
};

// For use in micro-frontends (iframes)
const ThemeReceiver = {
  /**
   * Initialize theme receiver in iframe
   */
  init() {
    // Request current theme from parent
    if (window.parent !== window) {
      window.parent.postMessage({ type: 'REQUEST_THEME' }, '*');
    }

    // Listen for theme changes
    window.addEventListener('message', (event) => {
      if (event.data && event.data.type === 'THEME_CHANGED') {
        this.applyTheme(event.data.theme);
      }
    });
  },

  /**
   * Apply theme to current document
   */
  applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.body.setAttribute('data-theme', theme);

    // Dispatch local event
    window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));

    console.log(`🎨 [Iframe] Theme applied: ${theme}`);
  },

  /**
   * Get current theme
   */
  getCurrentTheme() {
    return document.documentElement.getAttribute('data-theme') || 'classic';
  }
};

// Auto-export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { ThemeManager, ThemeReceiver };
}
