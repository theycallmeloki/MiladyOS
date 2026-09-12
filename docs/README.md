# MiladyOS Website & Documentation

The homepage welcomes ISO users; `/docs/` keeps the Hugo Docsy documentation.
The homepage uses a standalone template and local CSS/JS, without loading the
Docsy theme, remote fonts, or microphone effects. Documentation retains its
existing theme and search.

## Quick Start

### Prerequisites
- [Hugo extended](https://gohugo.io/installation/) (v0.146.0 or later)
- [Go](https://golang.org/doc/install) (v1.21 or later)
- [Git](https://git-scm.com/)
- Node.js and npm (for the locked PostCSS dependencies)

### Installation

1. **Install Hugo Extended**
   ```bash
   # macOS
   brew install hugo

   # Ubuntu/Debian - install to local bin
   wget https://github.com/gohugoio/hugo/releases/download/v0.150.1/hugo_extended_0.150.1_linux-amd64.tar.gz
   tar -xzf hugo_extended_0.150.1_linux-amd64.tar.gz
   mkdir -p ~/bin
   mv hugo ~/bin/
   echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
   source ~/.bashrc

   # Windows
   # Download from https://github.com/gohugoio/hugo/releases
   ```

2. **Initialize Hugo modules**
   ```bash
   cd docs
   hugo mod get
   ```

3. **Install dependencies**
   ```bash
   npm ci
   ```

### Running Locally

```bash
cd docs
hugo server --buildDrafts --buildFuture
```

The site will be available at http://localhost:1313

### Building for Production

```bash
hugo --gc --minify
```

The built site will be in the `public/` directory.

## Project Structure

```
docs/
├── hugo.toml              # Hugo configuration
├── go.mod                 # Hugo modules configuration
├── content/en/            # Documentation content
│   ├── _index.html        # Homepage
│   └── docs/              # Main documentation sections
│       ├── getting-started/
│       ├── architecture/
│       ├── autodidact/
│       ├── infrastructure/
│       ├── display-control/
│       ├── security/
│       ├── apis/
│       └── operations/
└── evolution/             # Historical files
```

## Contributing

1. Create new content in `content/en/docs/`
2. Use Markdown with Hugo front matter
3. Test locally with `hugo server`
4. Submit pull request

## Welcome page

- `layouts/index.html`: homepage structure and copy.
- `assets/css/welcome.css`: responsive landing-page styles.
- `assets/js/welcome.js`: optional checksum clipboard enhancement.
- `data/iso.toml`: verified public release URL, filename, version, size, date,
  checksum, and payload/desktop availability note.
- `content/en/docs/iso/_index.md`: installation and first-boot guide.
- `static/images/miladyos-wallpaper.jpg`: existing ISO wallpaper, copied from
  `ISO/desktop/wallpaper.jpg`. Keep these aligned when the brand asset changes.

### Connecting a new ISO

1. Wait for the JIT workflow to finish; inspect the draft release and test the
   artifact. The workflow's draft release is not publicly downloadable yet.
2. After the release is published, update **all** fields in `data/iso.toml`
   from that release, including the exact asset SHA-256 and payload status.
   Do not point to `releases/latest`: CLI releases share the repository.
3. Update the desktop availability copy in `layouts/index.html` when the public
   ISO contains Sway. The current page deliberately distinguishes the older
   public download from the newer source preview.
4. Build Hugo and check download, release notes, checksum, guide anchors, and
   the existing docs navigation on desktop and mobile. Release data is rendered
   at build time, so the homepage needs no GitHub API call at runtime.

The configuration-volume website builder is a future feature. The landing page
links to today's local cidata instructions and does not collect files or secrets.

## Documentation appearance

The Docsy pages use the welcome page's dark green palette with a system sans-serif
font for prose and monospace for code. Theme variables live in
`assets/scss/_variables_project.scss`; reading layout, navigation, tables,
callouts, mobile, and print styles live in `assets/scss/_styles_project.scss`.
The `partials/toc.html` override adds an “On this page” label. Keep content edits
separate from these visual overrides.

The head hook provides the shared favicon and theme color. The body-end hook
intentionally adds no ambient animation or floating voice controls to the
reading surface. Docsy's search, mobile navigation, and code-copy behavior remain.
