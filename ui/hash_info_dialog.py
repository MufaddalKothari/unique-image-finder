from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton
from PySide6.QtCore import Qt

class HashInfoDialog(QDialog):
    """
    Simple informational dialog that describes the hash types and controls.
    Opened by the ℹ️ button next to the hash selector.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Hashing Info")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        intro = QLabel("<b>How image hashing works</b>")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        content = QTextEdit()
        content.setReadOnly(True)
        content.setHtml("""
        <h3>Hash types</h3>
        <ul>
          <li><b>Average Hash (aHash)</b> — Very fast, computes average brightness in a small grid. Good for simple near-duplicates (resized/brightness changes).</li>
          <li><b>Perceptual Hash (pHash)</b> — Uses DCT; more robust to small edits and compression artifacts. Good default for perceptual similarity checks.</li>
          <li><b>Difference Hash (dHash)</b> — Encodes horizontal/vertical gradients; good for detecting small shifts/resizing.</li>
          <li><b>Wavelet Hash (wHash)</b> — Uses wavelet transform; robust to many operations and often gives better distances on complex changes.</li>
        </ul>
        <h3>Controls</h3>
        <ul>
          <li><b>Hash Size</b> — Controls the resolution of the hash (integer). Larger sizes produce longer hashes and finer-grained comparisons but take more time and memory. Typical presets: 4, 8, 16.</li>
          <li><b>Similarity Threshold</b> — Interpreted as allowed similarity percent. When using Hamming distance, map threshold percent to a maximum Hamming distance allowed. Lower thresholds are stricter (fewer matches).</li>
        </ul>
        <h3>Tuning tips</h3>
        <ol>
          <li>Start with pHash and size 8, similarity 90% for general-purpose dedupe.</li>
          <li>For near-exact duplicates (renames/copies), size 4 and similarity 98+ is very quick.</li>
          <li>To catch resized/cropped versions, try wHash or pHash with larger size (12 or 16) and lower similarity (80-90).</li>
          <li>Compute hashes once and cache them (the app supports an SQLite cache). Increasing hash size gives diminishing returns past a point but costs CPU/time.</li>
        </ol>
        <p style="font-size:small;color:gray">Note: Hashing algorithms are implemented by imagehash/Pillow when wired; this dialog explains conceptual behavior. Use the dropdowns to choose preset integer values.</p>
        """)
        layout.addWidget(content)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)