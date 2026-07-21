// This script runs before React hydration to prevent theme flash
export const themeScript = `
(function() {
  try {
    var systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    // Follow the Harvis shell theme (same-origin → shared localStorage.theme). Its
    // dark themes → 'dark', its light/paper themes → 'light'; fall back to this app's
    // own toggle when Harvis is on 'system' or unset.
    var harvis = localStorage.getItem('theme');
    var harvisDark = ['dark', 'midnight', 'harvis-dark', 'oled-dark', 'slate', 'oled', 'her'];
    var effectiveTheme;
    if (harvis && harvis !== 'system') {
      effectiveTheme = harvisDark.indexOf(harvis) >= 0 ? 'dark' : 'light';
    } else {
      var theme = JSON.parse(localStorage.getItem('theme-storage') || '{}').state?.theme || 'system';
      effectiveTheme = theme === 'system' ? (systemPrefersDark ? 'dark' : 'light') : theme;
    }
    
    document.documentElement.classList.remove('light', 'dark');
    document.documentElement.classList.add(effectiveTheme);
    document.documentElement.setAttribute('data-theme', effectiveTheme);
    // Palette variants: mirror the specific owui theme (warm/airy) so globals.css
    // can override the default blue palette; anything else uses the default.
    if (harvis === 'warm' || harvis === 'airy') {
      document.documentElement.setAttribute('data-nb-theme', harvis);
    } else {
      document.documentElement.removeAttribute('data-nb-theme');
    }
  } catch (e) {
    // Fallback to light theme
    document.documentElement.classList.add('light');
    document.documentElement.setAttribute('data-theme', 'light');
    document.documentElement.removeAttribute('data-nb-theme');
  }
})();
`