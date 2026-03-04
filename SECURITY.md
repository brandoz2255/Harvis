# Security Policy

## Known Vulnerabilities

### xlsx (sheetjs) - High Severity

**Status:** ⚠️ Known issue, no fix available from upstream

**Vulnerabilities:**
- GHSA-4r6h-8v6p-xvw6 - Prototype Pollution in sheetJS
- GHSA-5pgg-2g8v-p4x9 - SheetJS Regular Expression Denial of Service (ReDoS)

**Impact:** The `xlsx` package is used only for previewing Excel files in the `XlsxPreview` component. It does not process untrusted user input for file generation or server-side operations.

**Mitigation:**
- The package is only used client-side for rendering Excel file previews
- No server-side processing uses this library
- Files are processed in isolated browser context

**Planned Action:**
Migrate from `xlsx` to `exceljs` or remove XLSX preview functionality in a future release.

## Reporting Security Issues

If you discover a security vulnerability, please report it by opening an issue on the GitHub repository.

## Security Updates

This project uses automated dependency updates via npm audit. Critical and high severity vulnerabilities are addressed as soon as fixes are available from upstream maintainers.
