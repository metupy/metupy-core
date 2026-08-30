"""metupy_core.exception
Metupy Exception Handler Module.

Provides custom HTML error pages with detailed traceback for development mode,
showing precise file location, line numbers, error context, and code preview.
Uses Metupy Design System — full theme support, syntax highlighting, responsive.
"""

import traceback
import html
import os
import sys
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════
# 🔴 CUSTOM EXCEPTION CLASSES — SINGLE SOURCE OF TRUTH
# ═══════════════════════════════════════════════════════════════════════

class MetupyError(Exception):
    """Base exception class for all Metupy errors."""
    pass


class ConfigError(MetupyError):
    """Raised when configuration is invalid or missing."""
    pass


class PageLoadError(MetupyError):
    """Raised when a page file fails to load or parse."""
    pass


class BuildError(MetupyError):
    """Raised during build process failures."""
    pass


class ThemeError(MetupyError):
    """Raised when theme loading or rendering fails."""
    pass


class ParserError(MetupyError):
    """Raised when content parsing fails (.py / .md / .rst)."""
    pass


class ConversionError(MetupyError):
    """Raised when format conversion fails."""
    pass


class ExportNameError(MetupyError):
    """Raised when page module exports wrong variable name."""
    pass


class ToolsError(MetupyError):
    """Base exception for all tools/cli related errors."""
    pass


# ═══════════════════════════════════════════════════════════════════════
# 🎨 HTML EXCEPTION RENDERER — METUPY DESIGN SYSTEM
# ═══════════════════════════════════════════════════════════════════════

def render_exception_page(e: Exception) -> str:
    """Generate beautiful Metupy-style error page with full debug info."""
    
    # Extract full traceback
    try:
        if e.__traceback__:
            tb_list = traceback.format_exception(type(e), e, e.__traceback__)
            tb_str = "".join(tb_list)
        else:
            tb_str = traceback.format_exc()
    except Exception:
        tb_str = str(e)

    error_type = type(e).__name__
    error_message = str(e)

    # Extract precise error location
    error_file = "Unknown"
    error_line = 0
    error_func = "<module>"
    error_code_line = ""
    frame_snippets = []

    try:
        tb = e.__traceback__
        if tb:
            summary = traceback.extract_tb(tb)
            if summary:
                # Last frame = where exception occurred
                last_frame = summary[-1]
                error_file = last_frame.filename
                error_line = last_frame.lineno
                error_func = last_frame.name or "<module>"
                error_code_line = (last_frame.line or "").strip()
                
                # Collect all frames for stack trace
                for idx, frame in enumerate(summary):
                    frame_snippets.append({
                        "index": idx,
                        "file": frame.filename,
                        "line": frame.lineno,
                        "func": frame.name or "<module>",
                        "code": (frame.line or "").strip(),
                        "is_last": idx == len(summary) - 1
                    })
    except Exception:
        pass

    # Generate frames HTML
    frames_html = ""
    for frm in frame_snippets:
        active_class = "active" if frm["is_last"] else ""
        vendor_class = "vendor" if "metupy/" in frm["file"].lower() else ""
        frames_html += f'''
        <div class="metu-frame-card {active_class} {vendor_class}" data-frame="{frm['index']}">
            <span class="frame-num">Frame #{len(frame_snippets) - frm['index']}</span>
            <span class="frame-file">{html.escape(frm['file'])}</span>
            <span class="frame-func">in <code>{html.escape(frm['func'])}</code></span>
        </div>
        '''

    # Generate code lines with syntax highlighting
    code_lines_html = ""
    if error_code_line:
        code_lines_html = f'''
        <div class="code-line err-line">
            <span class="num">{error_line}</span>
            <span class="code">{_syntax_highlight(error_code_line)}</span>
            <span class="err-badge"><i class='bx bx-error'></i> {error_type}</span>
        </div>
        '''

    # Build context info
    context_html = f"""
    <div class="metu-info-card">
        <h3>Build Context</h3>
        <table class="metu-kv-table">
            <tbody>
                <tr><th>Error Type</th><td><code>{error_type}</code></td></tr>
                <tr><th>File</th><td><code>{html.escape(error_file)}</code></td></tr>
                <tr><th>Line</th><td><code>{error_line}</code></td></tr>
                <tr><th>Function</th><td><code>{html.escape(error_func)}</code></td></tr>
                <tr><th>Metupy Version</th><td><code>2.4.0</code></td></tr>
                <tr><th>Python Version</th><td><code>{_get_python_version()}</code></td></tr>
            </tbody>
        </table>
    </div>
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{error_type}: {html.escape(error_message)} | Metupy SSG Debugger</title>
  
  <!-- Boxicons & Fonts -->
  <link href="https://unpkg.com/boxicons@2.1.4/css/boxicons.min.css" rel="stylesheet">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
  
  <style>
    /* ==========================================
       METUPY DESIGN SYSTEM & EXCEPTION STYLES
    ========================================== */
    :root {{
      --metu-yellow: #F0C135;
      --metu-blue: #3B6F96;
      --metu-blue-dark: #223241;
      --metu-red: #ef4444;
      --metu-red-soft: #fca5a5;
      --metu-yellow-shadow: rgba(240, 193, 53, 0.3);
      --metu-blue-shadow: rgba(59, 111, 150, 0.3);
      --metu-red-shadow: rgba(239, 68, 68, 0.2);

      --metu-bg-primary: #ffffff;
      --metu-bg-header: rgba(255, 255, 255, 0.85);
      --metu-bg-input: #f1f5f9;
      --metu-bg-modal: #ffffff;
      --metu-text-primary: #1e293b;
      --metu-text-muted: #64748b;
      --metu-border-color: #e2e8f0;
    }}

    [data-theme="dark"] {{
      --metu-bg-primary: #0f172a;
      --metu-bg-header: rgba(15, 23, 42, 0.85);
      --metu-bg-input: #1e293b;
      --metu-bg-modal: #1e293b;
      --metu-text-primary: #f8fafc;
      --metu-text-muted: #94a3b8;
      --metu-border-color: #334155;
    }}

    * {{
      box-sizing: border-box;
      font-family: 'Poppins', sans-serif;
      margin: 0;
      padding: 0;
    }}

    body {{
      background-color: var(--metu-bg-input);
      color: var(--metu-text-primary);
      min-height: 100vh;
      transition: background-color 0.3s ease, color 0.3s ease;
      margin-top: 4rem;
    }}

    /* === HEADER === */
    header {{
      width: 100%;
      height: 4rem;
      position: fixed;
      top: 0;
      left: 0;
      z-index: 9999;
      background-color: var(--metu-bg-header);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--metu-border-color);
    }}

    .metu-header-container {{
      max-width: 1520px;
      height: 100%;
      margin: 0 auto;
      padding: 0 1.5rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    .metu-brand a {{
      gap: 0.5rem;
      font-size: 1.25rem;
      font-weight: 600;
      color: var(--metu-blue);
      display: inline-flex;
      align-items: center;
      text-decoration: none;
    }}

    .metu-brand img {{
      width: 32px;
      height: 32px;
    }}

    .metu-icon-btn {{
      background: transparent;
      border: 1px solid var(--metu-border-color);
      border-radius: 0.5rem;
      padding: 0.45rem;
      cursor: pointer;
      color: var(--metu-text-primary);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.2rem;
      transition: background-color 0.2s ease, color 0.2s ease;
    }}

    .metu-icon-btn:hover {{
      background-color: var(--metu-bg-input);
      color: var(--metu-yellow);
    }}

    /* === HERO SECTION === */
    .metu-err-hero {{
      background: linear-gradient(135deg, #1e1e2d 0%, #151521 100%);
      color: #ffffff;
      padding: 2rem 0;
      border-bottom: 3px solid var(--metu-red);
      width: 100%;
    }}

    .metu-err-hero-container {{
      max-width: 1520px;
      width: 100%;
      margin: 0 auto;
      padding: 0 2rem;
      box-sizing: border-box;
    }}

    .metu-err-tag {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      background: var(--metu-red-shadow);
      color: var(--metu-red-soft);
      padding: 0.3rem 0.75rem;
      border-radius: 4px;
      margin-bottom: 0.5rem;
    }}

    .metu-err-title {{
      font-size: 2.25rem;
      font-weight: 700;
      font-family: 'Fira Code', monospace;
      color: #f87171;
      margin-bottom: 0.35rem;
    }}

    .metu-err-subtitle {{
      font-size: 1.1rem;
      color: #9ca3af;
      line-height: 1.6;
    }}

    .metu-err-subtitle code {{
      color: #ffffff;
      background: rgba(255, 255, 255, 0.1);
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
      font-family: 'Fira Code', monospace;
    }}

    /* === DASHBOARD === */
    .metu-err-dashboard {{
      max-width: 1520px;
      width: 100%;
      margin: 1.5rem auto;
      padding: 0 2rem;
      box-sizing: border-box;
    }}

    /* === TABS === */
    .metu-err-tabs {{
      display: flex;
      gap: 0.5rem;
      margin-bottom: 1.25rem;
      flex-wrap: wrap;
    }}

    .metu-err-tab {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.65rem 1.35rem;
      border: 1px solid var(--metu-border-color);
      background: var(--metu-bg-primary);
      color: var(--metu-text-muted);
      border-radius: 0.5rem;
      font-weight: 600;
      font-size: 0.95rem;
      cursor: pointer;
      transition: all 0.2s ease;
    }}

    .metu-err-tab.active, 
    .metu-err-tab:hover {{
      background: var(--metu-blue);
      color: #ffffff;
      border-color: var(--metu-blue);
    }}

    [data-theme="dark"] .metu-err-tab.active {{
      background: var(--metu-yellow);
      color: var(--metu-blue-dark);
      border-color: var(--metu-yellow);
    }}

    .metu-err-tab-content {{ display: none; }}
    .metu-err-tab-content.active {{ display: block; animation: fadeIn 0.2s ease; }}

    @keyframes fadeIn {{
      from {{ opacity: 0; transform: translateY(5px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    /* === STACK TRACE GRID === */
    .metu-err-grid {{
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 1.5rem;
      align-items: start;
    }}

    /* === FRAMES SIDEBAR === */
    .metu-frames-sidebar {{
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
    }}

    .metu-frame-card {{
      display: flex;
      flex-direction: column;
      padding: 0.85rem 1.15rem;
      background: var(--metu-bg-primary);
      border: 1px solid var(--metu-border-color);
      border-radius: 0.5rem;
      cursor: pointer;
      transition: all 0.2s ease;
    }}

    .metu-frame-card:hover {{
      border-color: var(--metu-blue);
    }}

    .metu-frame-card.active {{
      border-left: 4px solid var(--metu-red);
      background: var(--metu-bg-input);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
    }}

    .metu-frame-card .frame-num {{
      font-size: 0.75rem;
      text-transform: uppercase;
      font-weight: 700;
      color: var(--metu-text-muted);
    }}

    .metu-frame-card .frame-file {{
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--metu-text-primary);
      margin: 0.2rem 0;
      word-break: break-all;
    }}

    .metu-frame-card .frame-func {{
      font-size: 0.85rem;
      color: var(--metu-text-muted);
    }}

    .metu-frame-card.vendor {{ opacity: 0.6; }}

    /* === CODE VIEWER === */
    .metu-code-viewer {{
      background: #1e1e2d;
      border-radius: 0.6rem;
      overflow: hidden;
      box-shadow: 0 8px 20px rgba(0, 0, 0, 0.12);
      border: 1px solid #2b2b3d;
    }}

    .metu-code-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.75rem 1.25rem;
      background: #181824;
      border-bottom: 1px solid #2b2b3d;
      color: #a6accd;
      font-size: 0.9rem;
      flex-wrap: wrap;
      gap: 0.5rem;
    }}

    .metu-copy-btn {{
      background: rgba(255, 255, 255, 0.08);
      border: none;
      color: #ffffff;
      padding: 0.35rem 0.75rem;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.8rem;
      transition: background 0.2s ease;
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
    }}

    .metu-copy-btn:hover {{
      background: rgba(255, 255, 255, 0.18);
    }}

    .metu-code-body {{
      padding: 0.85rem 0;
      font-family: 'Fira Code', monospace;
      font-size: 0.95rem;
      color: #a6accd;
      line-height: 1.65;
    }}

    .code-line {{
      display: flex;
      align-items: center;
      padding: 0.25rem 1.25rem;
      flex-wrap: wrap;
    }}

    .code-line .num {{
      width: 3rem;
      color: #4b5563;
      user-select: none;
      flex-shrink: 0;
    }}

    .code-line .code {{ flex: 1; word-break: break-all; }}

    .code-line.err-line {{
      background: rgba(239, 68, 68, 0.15);
      border-left: 4px solid var(--metu-red);
    }}

    .code-line.err-line .num {{
      color: var(--metu-red);
      font-weight: 700;
    }}

    .err-badge {{
      margin-left: auto;
      font-size: 0.8rem;
      color: var(--metu-red-soft);
      background: var(--metu-red-shadow);
      padding: 0.2rem 0.6rem;
      border-radius: 4px;
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      margin-top: 0.25rem;
    }}

    /* === SYNTAX HIGHLIGHTING === */
    .code .k {{ color: #f472b6; font-weight: 600; }} /* keyword */
    .code .s {{ color: #86efac; }} /* string */
    .code .s2 {{ color: #86efac; }} /* string double */
    .code .c1 {{ color: #6b7280; font-style: italic; }} /* comment */
    .code .n {{ color: #93c5fd; }} /* name */

    /* === CARDS & TABLES === */
    .metu-info-card {{
      background: var(--metu-bg-primary);
      border: 1px solid var(--metu-border-color);
      border-radius: 0.6rem;
      padding: 1.75rem;
    }}

    .metu-info-card h3 {{
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--metu-text-primary);
      margin-bottom: 1rem;
    }}

    .metu-kv-table {{
      width: 100%;
      border-collapse: collapse;
    }}

    .metu-kv-table th, 
    .metu-kv-table td {{
      text-align: left;
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--metu-border-color);
      font-size: 0.95rem;
    }}

    .metu-kv-table th {{
      width: 220px;
      color: var(--metu-text-muted);
      font-weight: 600;
    }}

    .metu-kv-table code {{
      font-family: 'Fira Code', monospace;
      color: var(--metu-blue);
    }}

    [data-theme="dark"] .metu-kv-table code {{
      color: var(--metu-yellow);
    }}

    /* === FOOTER === */
    .metu-err-footer {{
      background-color: var(--metu-bg-primary);
      border-top: 1px solid var(--metu-border-color);
      padding: 1.25rem 0;
      margin-top: 2rem;
      border-radius: 0.6rem;
    }}

    .metu-footer-container {{
      max-width: 1520px;
      width: 100%;
      margin: 0 auto;
      padding: 0 2rem;
      box-sizing: border-box;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.9rem;
      color: var(--metu-text-muted);
      flex-wrap: wrap;
      gap: 0.5rem;
    }}

    .metu-footer-brand strong,
    .metu-footer-credits strong {{
      color: var(--metu-text-primary);
      font-weight: 600;
    }}

    .metu-footer-credits {{
      display: flex;
      align-items: center;
      gap: 0.35rem;
    }}

    .metu-footer-credits i {{ color: var(--metu-red); }}

    /* === RESPONSIVE === */
    @media screen and (max-width: 1024px) {{
      .metu-err-grid {{ grid-template-columns: 300px 1fr; }}
    }}

    @media screen and (max-width: 768px) {{
      body {{ margin-top: 3.5rem; }}
      header {{ height: 3.5rem; }}
      .metu-header-container {{ padding: 0 1rem; }}
      .metu-err-grid {{ grid-template-columns: 1fr; }}
      .metu-err-hero-container {{ padding: 0 1rem; }}
      .metu-err-title {{ font-size: 1.5rem; word-break: break-word; }}
      .metu-err-subtitle {{ font-size: 0.95rem; }}
      .metu-err-dashboard {{ margin: 1rem auto; padding: 0 1rem; }}
      .metu-err-tabs {{ overflow-x: auto; flex-wrap: nowrap; }}
      .metu-err-footer {{ padding: 1rem 0; }}
      .metu-footer-container {{ flex-direction: column; text-align: center; }}
      .metu-kv-table th {{ width: 120px; }}
    }}
  </style>
</head>
<body>
  <!-- HEADER -->
  <header>
    <div class="metu-header-container">
      <div class="metu-left-action">
        <div class="metu-brand">
          <a href="/">
            <span style="font-weight:800;">Metupy</span>
          </a>
        </div>
      </div>
      <div class="metu-right-action">
        <button class="metu-icon-btn" id="metu-theme-toggle" aria-label="Toggle Theme">
          <i class='bx bx-moon' id="metu-theme-icon"></i>
        </button>
      </div>
    </div>
  </header>

  <!-- HERO SECTION -->
  <div class="metu-err-hero">
    <div class="metu-err-hero-container">
      <div class="metu-err-tag">
        <span>SSG Build Error</span>
      </div>
      <h1 class="metu-err-title">{error_type}</h1>
      <p class="metu-err-subtitle">{html.escape(error_message)}</p>
    </div>
  </div>

  <!-- MAIN CONTENT -->
  <main class="metu-err-dashboard">
    
    <!-- TABS -->
    <div class="metu-err-tabs">
      <button class="metu-err-tab active" data-tab="tab-trace"><i class='bx bx-git-commit'></i> Stack Trace</button>
      <button class="metu-err-tab" data-tab="tab-context"><i class='bx bx-layer'></i> Build Context</button>
      <button class="metu-err-tab" data-tab="tab-traceback"><i class='bx bx-code-block'></i> Full Traceback</button>
    </div>

    <!-- TAB 1: STACK TRACE -->
    <div class="metu-err-tab-content active" id="tab-trace">
      <div class="metu-err-grid">
        
        <!-- FRAMES SIDEBAR -->
        <div class="metu-frames-sidebar">
          {frames_html}
        </div>

        <!-- CODE VIEWER -->
        <div class="metu-code-viewer">
          <div class="metu-code-header">
            <div class="file-path"><i class='bx bx-file'></i> <strong>{html.escape(error_file)}</strong> at line <strong>{error_line}</strong></div>
            <button class="metu-copy-btn" id="copy-path-btn"><i class='bx bx-copy'></i> Copy Path</button>
          </div>
          <div class="metu-code-body">
            {code_lines_html}
          </div>
        </div>

      </div>
    </div>

    <!-- TAB 2: BUILD CONTEXT -->
    <div class="metu-err-tab-content" id="tab-context">
      {context_html}
    </div>

    <!-- TAB 3: FULL TRACEBACK -->
    <div class="metu-err-tab-content" id="tab-traceback">
      <div class="metu-info-card">
        <h3>Full Traceback</h3>
        <pre style="background: #1e1e2d; color: #a6accd; padding: 1rem; border-radius: 0.5rem; overflow-x: auto; font-family: 'Fira Code', monospace; font-size: 0.9rem; line-height: 1.6; margin-top: 1rem;">{html.escape(tb_str)}</pre>
      </div>
    </div>

    <!-- FOOTER -->
    <footer class="metu-err-footer">
      <div class="metu-footer-container">
        <div class="metu-footer-brand">
          <span>Powered by <strong>Metupy SSG Engine</strong> v2.4.0</span>
        </div>
        <div class="metu-footer-credits">
          <span>Designed & Developed with <i class='bx bxs-heart'></i> by <strong>Metupy Team</strong></span>
        </div>
      </div>
    </footer>
  </main>

  <script>
    // Tab Switching
    document.querySelectorAll('.metu-err-tab').forEach(tab => {{
      tab.addEventListener('click', () => {{
        document.querySelectorAll('.metu-err-tab, .metu-err-tab-content').forEach(el => el.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(tab.dataset.tab).classList.add('active');
      }});
    }});

    // Theme Toggle
    const themeToggle = document.getElementById('metu-theme-toggle');
    const themeIcon = document.getElementById('metu-theme-icon');
    const savedTheme = localStorage.getItem('metu-theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    themeIcon.className = savedTheme === 'dark' ? 'bx bx-sun' : 'bx bx-moon';

    themeToggle.addEventListener('click', () => {{
      const current = document.documentElement.getAttribute('data-theme');
      const newTheme = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', newTheme);
      localStorage.setItem('metu-theme', newTheme);
      themeIcon.className = newTheme === 'dark' ? 'bx bx-sun' : 'bx bx-moon';
    }});

    // Copy Path
    document.getElementById('copy-path-btn').addEventListener('click', () => {{
      navigator.clipboard.writeText('{html.escape(error_file)}:{error_line}');
      const btn = document.getElementById('copy-path-btn');
      btn.innerHTML = '<i class="bx bx-check"></i> Copied!';
      setTimeout(() => {{ btn.innerHTML = '<i class="bx bx-copy"></i> Copy Path'; }}, 2000);
    }});

    // Frame selection
    document.querySelectorAll('.metu-frame-card').forEach(card => {{
      card.addEventListener('click', () => {{
        document.querySelectorAll('.metu-frame-card').forEach(el => el.classList.remove('active'));
        card.classList.add('active');
      }});
    }});
  </script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
# 🛡️ HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def _syntax_highlight(line: str) -> str:
    """Basic Python syntax highlighting for error line."""
    import re
    keywords = ['from', 'import', 'class', 'def', 'if', 'else', 'elif', 'return', 
                'for', 'while', 'try', 'except', 'with', 'as', 'pass', 'raise',
                'print', 'in', 'is', 'not', 'and', 'or', 'None', 'True', 'False']
    
    words = re.findall(r'(\w+|".*?"|\'.*?\'|#.*|\S+)', line)
    result = []
    
    for word in words:
        if word.startswith('#'):
            result.append(f'<span class="c1">{html.escape(word)}</span>')
        elif word.startswith(('"', "'")):
            result.append(f'<span class="s">{html.escape(word)}</span>')
        elif word in keywords:
            result.append(f'<span class="k">{html.escape(word)}</span>')
        else:
            result.append(html.escape(word))
    
    return ''.join(result)


def _get_python_version() -> str:
    """Get current Python version."""
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def handle_exception(exception: Exception, dev_mode: bool = True) -> str:
    """Unified exception handler — returns HTML error page in dev mode."""
    if dev_mode:
        return render_exception_page(exception)
    else:
        error_type = type(exception).__name__
        return f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family:system-ui;padding:3rem;text-align:center;background:#f8fafc;color:#1e293b;">
            <h1 style="color:#ef4444;">Something went wrong</h1>
            <p>An unexpected error occurred. Please try again later.</p>
            <p style="color:#64748b;font-size:0.9rem;">{error_type}</p>
        </body>
        </html>
        """


def catch_errors(func):
    """Decorator to catch exceptions and return HTML error page automatically."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return render_exception_page(e)
    return wrapper
