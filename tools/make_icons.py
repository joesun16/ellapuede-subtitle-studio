import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QImage,QPainter
from PySide6.QtCore import Qt
from PIL import Image

def main():
    app=QApplication.instance() or QApplication([])
    assets=Path(__file__).resolve().parent.parent/'assets'
    image=QImage(1024,1024,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);QSvgRenderer(str(assets/'brand.svg')).render(painter);painter.end()
    image.save(str(assets/'app-icon.png'))
    im=Image.open(assets/'app-icon.png')
    im.save(assets/'app-icon.ico',sizes=[(n,n) for n in [16,24,32,48,64,128,256]])
    im.save(assets/'app-icon.icns')
if __name__=='__main__':main()
