#!/usr/bin/env python3
"""Generate Woodpecker UI branding (custom.css + custom.js) from logo.svg.

Usage: branding.py <logo.svg> <custom.css out> <custom.js out>

The logo is embedded as a data URI so it works without serving extra assets
(the server only exposes the custom css/js at fixed paths). The header logo
is the nav link's inline <svg>; we hide it and show the logo via ::before.
Dark theme handled via the SPA's html[data-theme] attribute (line art inverts
cleanly). custom.js swaps the favicon (SPA-safe via MutationObserver).
"""
import base64
import sys

svg_path, css_out, js_out = sys.argv[1:4]
b64 = base64.b64encode(open(svg_path, "rb").read()).decode()
uri = f"data:image/svg+xml;base64,{b64}"

css = f"""/* MiladyOS branding — generated from logo.svg (custom.css).
   Served by woodpecker-server at /assets/custom.css (WOODPECKER_CUSTOM_CSS_FILE). */
a[href="/"] svg {{
  display: none;
}}
a[href="/"]::before {{
  content: "";
  display: inline-block;
  width: 32px;
  height: 32px;
  background-image: url("{uri}");
  background-size: contain;
  background-repeat: no-repeat;
  background-position: center;
}}
html[data-theme="dark"] a[href="/"]::before {{
  filter: invert(1);
}}
"""

js = f"""// MiladyOS branding — generated from logo.svg (custom.js).
// Served by woodpecker-server at /assets/custom.js (WOODPECKER_CUSTOM_JS_FILE).
(function () {{
  var uri = "{uri}";
  function setFav() {{
    document.querySelectorAll('link[rel="icon"], link[rel="alternate icon"]').forEach(function (i) {{
      i.href = uri;
      i.type = 'image/svg+xml';
    }});
  }}
  setFav();
  new MutationObserver(setFav).observe(document.head, {{ childList: true, subtree: true }});
}})();
"""

open(css_out, "w").write(css)
open(js_out, "w").write(js)
print(f"branding: {css_out} ({len(css)} bytes) {js_out} ({len(js)} bytes)")
