# ui/styles.py
# Centralized style tokens used by the UI (updated per latest UI polish requests).
# - Less-bright off-white
# - Unified, minimal Adobe-like buttons (shorter, consistent)
# - Tab headers styled to be clearly separated and not full-bleed
# - Use a nicer monospaced / "unispace" font first-choice (JetBrains Mono / Fira Mono),
#   with sensible fallbacks.
#
# Note: Qt's stylesheet engine doesn't support all CSS properties; avoid unsupported ones.

FONT_FAMILY = '"JetBrains Mono", "Fira Mono", "IBM Plex Mono", "Menlo", "Consolas", "Monaco", monospace'

GLASSY_STYLE = rf"""
/* Base window and font */
QWidget {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 rgba(244,245,246,1.0),
                                stop:1 rgba(239,240,241,1.0));
    color: #0f1720;
    font-family: {FONT_FAMILY};
    font-size: 13px;
}}

/* Group boxes and panes: slightly translucent and uniform */
QGroupBox {{
    background: rgba(255,255,255,0.92);
    border-radius: 10px;
    padding: 8px;
    margin-top: 6px;
    border: 1px solid rgba(12,15,20,0.04);
}}

/* Tab widget pane */
QTabWidget::pane {{
    background: rgba(250,250,252,0.92);
    border-radius: 12px;
    padding: 10px;
    border: 1px solid rgba(12,15,20,0.04);
}}

/* Tab Bar - visually separated headers that span center area when needed,
   but not full-bleed. Tabs will not expand to occupy all space by default. */
QTabBar::tab {{
    background: rgba(247,248,249,0.96);
    color: #0f1720;
    border: 1px solid rgba(10,20,30,0.06);
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 12px;
    margin-right: 6px;
    min-width: 110px;   /* decreased minimum width so more tabs visible */
    max-width: 220px;   /* prevents overly long full-bleed tabs */
    min-height: 40px;
    font-weight: 650;
    qproperty-alignment: AlignCenter;
}}
QTabBar::tab:selected {{
    background: rgba(255,255,255,1.00);
    margin-top: 0px;
    border-bottom: 1px solid rgba(0,0,0,0.04);
}}
QTabBar::tab:!selected {{
    margin-top: 4px; /* slight visual separation */
}}
QTabBar::tab:hover {{
    background: rgba(255,255,255,0.98);
}}

/* Buttons: Adobe-like compact buttons with slight curve and consistent sizes.
   Use style classes for semantic colors: primary/search, danger, success, neutral.
*/
QPushButton {{
    min-height: 32px;
    padding: 6px 10px;
    border-radius: 8px;
    color: #fff;
    font-weight: 700;
    border: none;
}}
/* Primary (search) - compact square-ish icon button */
QPushButton#search_btn {{
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #386ef7, stop:1 #2b56d6);
    color: #ffffff;
}}
/* Danger (delete) */
QPushButton.danger {{
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #ef4444, stop:1 #d43b3b);
}}
/* Success (save/keep) */
QPushButton.success {{
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #12b886, stop:1 #0fa57a);
}}
/* Neutral (secondary) */
QPushButton.neutral {{
    background: rgba(15,23,32,0.06);
    color: #0f1720;
    font-weight: 700;
}}

/* Icon-only tool buttons */
QToolButton.iconOnly {{
    background: transparent;
    min-height: 32px;
    padding: 6px;
    border-radius: 8px;
}}

/* Progress bar with curved chunk and slightly glassy gradient */
QProgressBar {{
    border: 0px solid rgba(0,0,0,0);
    border-radius: 10px;
    background: rgba(255,255,255,0.06);
    text-align: center;
    min-height: 16px;
}}
QProgressBar::chunk {{
    border-radius: 10px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #60a5fa, stop:1 #34d399);
}}

/* Line edits (inputs) */
QLineEdit {{
    background: rgba(255,255,255,0.96);
    border: 1px solid rgba(0,0,0,0.06);
    border-radius: 8px;
    padding: 8px;
}}

/* Left panel (file browser) visual */
#left_panel {{
    background: rgba(255,255,255,0.94);
    border: 1px solid rgba(12,15,20,0.04);
    border-radius: 8px;
}}

/* Footer */
#footer_label {{
    color: rgba(15,23,32,0.65);
    font-size: 12px;
}}
/* Compact tweaks for scroll areas inside tabs */
QScrollArea {{
    background: transparent;
    border: none;
}}
"""

DARK_STYLE = rf"""
QWidget {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(12,14,18,1.0), stop:1 rgba(18,20,24,1.0));
    color: #e6eef5;
    font-family: {FONT_FAMILY};
    font-size: 13px;
}}
QTabWidget::pane {{ background: rgba(8,10,14,0.6); border-radius: 10px; padding: 8px; }}
QTabBar::tab {{ background: rgba(24,26,30,0.9); color:#e6eef5; border:1px solid rgba(255,255,255,0.02); padding:8px 12px; min-width:110px; max-width:220px; border-top-left-radius:8px; border-top-right-radius:8px; }}
QTabBar::tab:selected {{ background: rgba(34,36,42,1.0); }}
QPushButton#search_btn {{ background: qlineargradient(spread:pad, x1:0,y1:0,x2:1,y2:0, stop:0 #2563eb, stop:1 #1e40af); color:#fff; }}
QPushButton.danger {{ background: #ef4444; color:#fff; }}
QPushButton.success {{ background: #10b981; color:#fff; }}
QPushButton.neutral {{ background: rgba(255,255,255,0.03); color:#e6eef5; font-weight:700; }}
QProgressBar {{ border-radius:10px; background: rgba(255,255,255,0.03); }}
QProgressBar::chunk {{ border-radius:10px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #60a5fa, stop:1 #3b82f6); }}
QLineEdit {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.02); color:#e6eef5; }}
#left_panel {{ background: rgba(20,22,26,0.6); border:1px solid rgba(255,255,255,0.02); }}
#footer_label {{ color: rgba(230,238,245,0.6); font-size:12px; }}
"""
