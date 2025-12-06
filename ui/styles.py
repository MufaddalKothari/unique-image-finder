# ui/styles.py
# Centralized style tokens used by the UI (regenerated).
# - Glassy light and dark themes
# - Ubuntu Mono primary font (with fallbacks)
# - Curved modern scrollbars
# - Styled cached-dir controls with distinct colors
# - Styled left-panel toggle buttons (curved)
#
# Note: Keep Qt stylesheet-compatible properties only.

FONT_FAMILY = '"Ubuntu Mono", "JetBrains Mono", "Fira Mono", "IBM Plex Mono", "Menlo", "Consolas", monospace'

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

/* Group boxes and panes */
QGroupBox {{
    background: rgba(255,255,255,0.94);
    border-radius: 10px;
    padding: 8px;
    margin-top: 6px;
    border: 1px solid rgba(12,15,20,0.04);
}}

/* Left panel */
#left_panel {{
    background: rgba(255,255,255,0.96);
    border: 1px solid rgba(12,15,20,0.04);
    border-radius: 10px;
    padding: 8px;
}}

/* Left-toggle and collapse buttons (modern curved) */
QToolButton#left_toggle_btn, QToolButton#collapse_btn {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(255,255,255,0.96), stop:1 rgba(247,249,251,0.96));
    border: 1px solid rgba(12,15,20,0.06);
    border-radius: 10px;
    padding: 6px 8px;
    min-width: 28px;
    min-height: 28px;
}}
QToolButton#left_toggle_btn:hover, QToolButton#collapse_btn:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(255,255,255,1.0), stop:1 rgba(250,250,252,1.0));
}}

/* Tab widget pane */
QTabWidget::pane {{
    background: rgba(250,250,252,0.92);
    border-radius: 12px;
    padding: 10px;
    border: 1px solid rgba(12,15,20,0.04);
}}

/* Tab Bar */
QTabBar::tab {{
    background: rgba(247,248,249,0.96);
    color: #0f1720;
    border: 1px solid rgba(10,20,30,0.06);
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 12px;
    margin-right: 6px;
    min-width: 90px;
    max-width: 220px;
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
    margin-top: 4px;
}}
QTabBar::tab:hover {{
    background: rgba(255,255,255,0.98);
}}

/* Buttons */
QPushButton {{
    min-height: 30px;
    padding: 6px 12px;
    border-radius: 8px;
    color: #fff;
    font-weight: 700;
    border: none;
}}
QPushButton#search_btn {{
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #386ef7, stop:1 #2b56d6);
    color: #fff;
    min-width: 80px;
}}

/* Semantic */
QPushButton.danger {{ background: qlineargradient(spread:pad, x1:0,y1:0,x2:1,y2:0, stop:0 #ef4444, stop:1 #d43b3b); }}
QPushButton.success {{ background: qlineargradient(spread:pad, x1:0,y1:0,x2:1,y2:0, stop:0 #12b886, stop:1 #0fa57a); }}
QPushButton.neutral {{ background: rgba(15,23,32,0.06); color:#0f1720; font-weight:700; }}

/* Tool buttons (compare fields / theme / info) */
QToolButton#field_selector_btn, QToolButton#theme_toggle_btn, QToolButton#info_btn {{
    background: rgba(255,255,255,0.88);
    border-radius: 8px;
    padding: 6px 10px;
    border: 1px solid rgba(12,15,20,0.04);
    font-weight: 700;
    min-height: 30px;
}}
QToolButton#field_selector_btn:hover, QToolButton#theme_toggle_btn:hover, QToolButton#info_btn:hover {{
    background: rgba(255,255,255,0.96);
}}

/* Progress bar */
QProgressBar {{
    border: 0;
    border-radius: 10px;
    background: rgba(255,255,255,0.06);
    min-height: 14px;
}}
QProgressBar::chunk {{
    border-radius: 10px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #60a5fa, stop:1 #34d399);
}}

/* Line edits */
QLineEdit {{
    background: rgba(255,255,255,0.96);
    border: 1px solid rgba(0,0,0,0.06);
    border-radius: 8px;
    padding: 8px;
}}

/* Modern curved scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 6px 0 6px 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(0,0,0,0.15);
    min-height: 20px;
    border-radius: 6px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(0,0,0,0.22);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 0 6px 0 6px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(0,0,0,0.15);
    min-width: 20px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(0,0,0,0.22);
}}

/* Cached directories controls - colored glassy buttons */
QPushButton#cached_btn {{
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #06b6d4, stop:1 #0ea5b7);
    color: #ffffff;
    border-radius: 8px;
}}
QPushButton#cache_add_btn {{
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669);
    color: #fff;
    border-radius: 8px;
}}
QPushButton#cache_refresh_btn {{
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #f59e0b, stop:1 #d97706);
    color: #fff;
    border-radius: 8px;
}}
QPushButton#cache_rehash_btn {{
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #60a5fa, stop:1 #3b82f6);
    color: #fff;
    border-radius: 8px;
}}
QPushButton#cache_open_btn {{
    background: rgba(15,23,42,0.06);
    color: #0f1720;
    border-radius: 8px;
}}

/* Footer */
#footer_label {{
    color: rgba(15,23,32,0.65);
    font-size: 12px;
}}
"""

DARK_STYLE = rf"""
QWidget {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(12,14,18,1.0), stop:1 rgba(18,20,24,1.0));
    color: #e6eef5;
    font-family: {FONT_FAMILY};
    font-size: 13px;
}}
#left_panel {{ background: rgba(20,22,26,0.6); border:1px solid rgba(255,255,255,0.02); border-radius:10px; padding:8px; }}
QTabWidget::pane {{ background: rgba(8,10,14,0.6); border-radius: 12px; padding: 10px; }}
QTabBar::tab {{ background: rgba(24,26,30,0.9); color:#e6eef5; padding:8px 12px; min-width:90px; max-width:220px; border-top-left-radius:8px; border-top-right-radius:8px; }}
QTabBar::tab:selected {{ background: rgba(34,36,42,1.0); }}
QPushButton#search_btn {{ background: qlineargradient(spread:pad, x1:0,y1:0,x2:1,y2:0, stop:0 #2563eb, stop:1 #1e40af); color:#fff; }}
QToolButton#field_selector_btn, QToolButton#theme_toggle_btn, QToolButton#info_btn {{ background: rgba(30,32,36,0.6); border-radius:8px; padding:6px 10px; color:#e6eef5; }}
QToolButton#left_toggle_btn, QToolButton#collapse_btn {{ background: rgba(30,32,36,0.6); border-radius:10px; padding:6px 8px; color:#e6eef5; }}
QPushButton#cached_btn {{ background: qlineargradient(spread:pad, x1:0,y1:0,x2:1,y2:0, stop:0 #0891b2, stop:1 #0ea5b7); color:#fff; border-radius:8px; }}
QPushButton#cache_add_btn {{ background: qlineargradient(spread:pad, x1:0,y1:0,x2:1,y2:0, stop:0 #059669, stop:1 #10b981); color:#fff; border-radius:8px; }}
QPushButton#cache_refresh_btn {{ background: #b45309; color:#fff; border-radius:8px; }}
QPushButton#cache_rehash_btn {{ background: #2563eb; color:#fff; border-radius:8px; }}
QPushButton#cache_open_btn {{ background: rgba(255,255,255,0.03); color:#e6eef5; border-radius:8px; }}
#footer_label {{ color: rgba(230,238,245,0.6); font-size:12px; }}
"""