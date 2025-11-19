GLASSY_STYLE = """
QWidget {
    background: #ffffff;
    color: #232323;
    font-family: 'Segoe UI', 'Arial', sans-serif;
}

/* Buttons: rounded, semi-transparent "glass" look */
QPushButton {
    border-radius: 18px;
    padding: 7px 18px;
    background: rgba(255, 255, 255, 0.85);
    border: 1px solid rgba(180, 180, 180, 0.18);
    font-weight: 600;
}

/* Hover */
QPushButton:hover {
    background: rgba(245, 245, 250, 0.95);
}

/* Inputs */
QLineEdit, QComboBox, QSlider {
    border-radius: 10px;
    background: rgba(245, 245, 250, 0.9);
    border: 1px solid rgba(180, 180, 180, 0.12);
    padding: 6px 10px;
}

/* Group boxes */
QGroupBox {
    border: 1.2px solid #f4f6fa;
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.88);
    font-weight: bold;
    margin-top: 12px;
    padding: 10px;
}

/* Labels */
QLabel {
    font-size: 14px;
}

/* Scroll area */
QScrollArea {
    background: transparent;
    border: none;
}
"""