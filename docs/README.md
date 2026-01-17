# MiladyOS Documentation

This is the Hugo Docsy documentation site for MiladyOS.

## Quick Start

### Prerequisites
- [Hugo extended](https://gohugo.io/installation/) (v0.110.0 or later)
- [Go](https://golang.org/doc/install) (v1.21 or later)
- [Git](https://git-scm.com/)

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
   hugo mod init github.com/theycallmeloki/MiladyOS/docs
   hugo mod get github.com/google/docsy@v0.8.0
   ```

3. **Install dependencies**
   ```bash
   hugo mod get
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