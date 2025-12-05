# ui/styles.py
# Centralized style tokens used by the UI.
# Provides two themes: GLASSY_STYLE (light/off-white) and DARK_STYLE.
#
# Note: Keep the CSS Qt-friendly — avoid unsupported properties (e.g., box-shadow).
# Use border-radius, gradients, rgba colors and QGraphicsDropShadowEffect where needed.

# Off-white glassy/light theme (less white than before)
GLASSY_STYLE = r"""
/* Window background */
QWidget {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 rgba(245,247,250,1.0),
                                stop:1 rgba(238,241,244,1.0));
    color: #0f1720;
    font-family: "Segoe UI", Roboto, Arial, sans-serif;
    font-size: 13px;
}

/* Group boxes and panes */
QGroupBox {
    background: rgba(255,255,255,0.92);
    border-radius: 10px;
    padding: 8px;
    margin-top: 6px;
}

/* Tab widget pane slightly translucent */
QTabWidget::pane {
    background: rgba(250,250,252,0.88);
    border-radius: 12px;
    padding: 10px;
}

/* TabBar: make tabs distinct and thicker */
QTabBar::tab {
    background: rgba(245,246,247,0.96);
    color: #0f1720;
    border: 1px solid rgba(10,20,30,0.06);
    border-bottom: 0px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    padding: 10px 18px;
    margin-right: 6px;
    min-height: 40px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background: rgba(255,255,255,1.00);
    border-bottom: 1px solid rgba(0,0,0,0.06);
}
QTabBar::tab:!selected {
    margin-top: 4px; /* make selected tab visually raised */
}

/* Buttons: Adobe-like, colored and concise */
QPushButton {
    min-height: 32px;
    padding: 6px 12px;
    border-radius: 8px;
    color: #ffffff;
    font-weight: 600;
    border: none;
}
/* Primary (search) */
QPushButton#search_btn {
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #265df2);
}
/* Danger (delete) */
QPushButton.danger {
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #ef4444, stop:1 #d43b3b);
}
/* Success (save/keep) */
QPushButton.success {
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #0e9a74);
}
/* Neutral (move/save other actions) */
QPushButton.neutral {
    background: rgba(30,30,30,0.08);
    color:#0f1720;
    font-weight:600;
}

/* Icon-only tool buttons */
QToolButton.iconOnly {
    background: transparent;
    min-height: 32px;
    padding: 6px;
    border-radius: 8px;
}

/* Progress bar with curved corners */
QProgressBar {
    border: 0px solid rgba(0,0,0,0);
    border-radius: 10px;
    background: rgba(255,255,255,0.08);
    text-align: center;
    min-height: 16px;
}
QProgressBar::chunk {
    border-radius: 10px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #34d399, stop:1 #10b981);
}

/* Line edits (inputs) */
QLineEdit {
    background: rgba(255,255,255,0.96);
    border: 1px solid rgba(0,0,0,0.06);
    border-radius: 8px;
    padding: 8px;
}

/* Footer */
#footer_label {
    color: rgba(15,23,32,0.7);
    font-size: 12px;
}

/* Small tweaks for scroll areas inside tabs */
QScrollArea {
    background: transparent;
    border: none;
}
"""

# Dark theme (toggle target)
DARK_STYLE = r"""
QWidget {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 rgba(12,14,18,1.0),
                                stop:1 rgba(18,20,24,1.0));
    color: #e6eef5;
    font-family: "Segoe UI", Roboto, Arial, sans-serif;
    font-size: 13px;
}

/* Tabs */
QTabWidget::pane {
    background: rgba(8,10,14,0.6);
    border-radius: 8px;
    padding: 10px;
}
QTabBar::tab {
    background: rgba(20,22,28,0.8);
    color: #e6eef5;
    border: 1px solid rgba(255,255,255,0.02);
    border-bottom: 0px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 16px;
    margin-right: 6px;
    min-height: 36px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background: rgba(30,32,40,1.0);
}

/* Buttons */
QPushButton#search_btn {
    background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #1e40af);
    color: #fff;
}
QPushButton.danger { background: #ef4444; color: #fff; }
QPushButton.success { background: #10b981; color: #fff; }

/* Progress bar */
QProgressBar { border-radius: 10px; background: rgba(255,255,255,0.03); }
QProgressBar::chunk { border-radius: 10px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #60a5fa, stop:1 #3b82f6); }

QLineEdit {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.02);
    color: #e6eef5;
}
#footer_label { color: rgba(230,238,245,0.5); font-size:12px; }
"""
