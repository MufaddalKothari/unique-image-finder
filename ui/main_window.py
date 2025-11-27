# Main application UI

from PyQt5 import QtWidgets

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Unique Image Finder")

    def setup_ui(self):
        # Set up your UI components here
        pass

if __name__ == '__main__':
    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.setup_ui()
    window.show()
    app.exec_()
