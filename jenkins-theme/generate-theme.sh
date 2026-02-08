#!/bin/bash
# Generate Jenkins theme CSS with custom logo
# Usage: ./generate-theme.sh [logo.svg] [output.css]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGO_FILE="${1:-$SCRIPT_DIR/../logo.svg}"
OUTPUT_CSS="${2:-$SCRIPT_DIR/milady-theme.css}"

if [ ! -f "$LOGO_FILE" ]; then
    echo "Error: Logo file not found: $LOGO_FILE"
    exit 1
fi

echo "Generating Jenkins theme CSS..."
echo "Logo: $LOGO_FILE"
echo "Output: $OUTPUT_CSS"

# Base64 encode the SVG
LOGO_BASE64=$(base64 -w 0 "$LOGO_FILE")
LOGO_DATA_URI="data:image/svg+xml;base64,${LOGO_BASE64}"

# Generate the CSS
cat > "$OUTPUT_CSS" << CSSEOF
/*
 * MiladyOS Jenkins Theme
 * Auto-generated - do not edit directly
 * Regenerate with: ./generate-theme.sh
 */

/* === Classic Jenkins UI === */

/* Replace the logo image using content property */
.logo img,
#jenkins-head-icon,
.jenkins-head-icon {
    content: url("${LOGO_DATA_URI}") !important;
    width: 40px !important;
    height: 40px !important;
}

/* Hide the Jenkins name text */
#jenkins-name-icon,
.jenkins-name-icon {
    display: none !important;
}

/* Alternative: background-image approach for elements that don't support content */
.logo {
    background-image: url("${LOGO_DATA_URI}") !important;
    background-repeat: no-repeat !important;
    background-position: left center !important;
    background-size: 40px 40px !important;
}

/* === Modern Jenkins UI (2.400+) === */

/* Page header brand */
.page-header__brand-link img,
.page-header .logo img {
    content: url("${LOGO_DATA_URI}") !important;
    width: 32px !important;
    height: 32px !important;
}

/* Jenkins symbol/icon */
.jenkins-symbol-icon {
    display: none !important;
}

/* Header hyperlink with logo */
.page-header__brand-link {
    background-image: url("${LOGO_DATA_URI}") !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    background-size: contain !important;
}

/* SVG icons in header */
header svg.jenkins-head-icon,
.page-header svg {
    display: none !important;
}

/* === BlueOcean UI === */

.Header-logo svg,
.Header-logo img {
    display: none !important;
}

.Header-logo {
    background-image: url("${LOGO_DATA_URI}") !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    background-size: contain !important;
    min-width: 32px !important;
    min-height: 32px !important;
}

/* === Login Page === */

#loginIntroDefault img,
.login-page .logo img {
    content: url("${LOGO_DATA_URI}") !important;
    max-width: 200px !important;
    max-height: 200px !important;
}
CSSEOF

echo "Generated: $OUTPUT_CSS"
echo "CSS size: $(wc -c < "$OUTPUT_CSS") bytes"
