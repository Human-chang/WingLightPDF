# -*- coding: utf-8 -*-
"""
滾輪翻頁：頁面放大到超過視窗時，捲到頂或底會切換上一頁／下一頁；
第一頁頂端往上、最後一頁底端往下沒有頁可翻，捲軸要停在原地。
執行：python -m unittest discover -s tests -t .
"""

from __future__ import annotations
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.pdf_engine import PDFEngine  # noqa: E402
from ui.canvas_view import PDFCanvasView  # noqa: E402

PAGE_COUNT = 3


def _wheel(view: PDFCanvasView, delta_y: int) -> None:
    pos = QPointF(view.viewport().width() / 2, view.viewport().height() / 2)
    event = QWheelEvent(
        pos,
        view.viewport().mapToGlobal(pos),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    view.wheelEvent(event)


class CanvasWheelPageStepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])
        cls.tmp_dir = tempfile.mkdtemp(prefix="winglightpdf_test_")
        cls.pdf_path = os.path.join(cls.tmp_dir, "pages.pdf")
        doc = fitz.open()
        for _ in range(PAGE_COUNT):
            doc.new_page()
        doc.save(cls.pdf_path)
        doc.close()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def setUp(self) -> None:
        self.engine = PDFEngine()
        self.engine.open_file(self.pdf_path)
        self.view = PDFCanvasView(self.engine)
        self.view.resize(400, 300)
        self.view.zoom = 2.0  # 頁面比視窗高，才有垂直捲軸
        self.view.show()
        self.steps: list[int] = []
        self.view.request_page_step.connect(self.steps.append)

    def tearDown(self) -> None:
        self.view.close()
        self.view.deleteLater()
        self.engine.close()

    def _show_page(self, index: int) -> None:
        self.view.current_page_index = index
        self.view.render_current_page(preserve_scroll=False)
        self.app.processEvents()
        self.assertGreater(self.view.verticalScrollBar().maximum(), 0, "頁面要比視窗高才測得到")

    def test_last_page_bottom_wheel_down_stays(self) -> None:
        self._show_page(PAGE_COUNT - 1)
        vbar = self.view.verticalScrollBar()
        vbar.setValue(vbar.maximum())
        for _ in range(3):
            _wheel(self.view, -120)
            self.assertEqual(vbar.value(), vbar.maximum())
        self.assertEqual(self.steps, [])

    def test_first_page_top_wheel_up_stays(self) -> None:
        self._show_page(0)
        vbar = self.view.verticalScrollBar()
        vbar.setValue(vbar.minimum())
        for _ in range(3):
            _wheel(self.view, 120)
            self.assertEqual(vbar.value(), vbar.minimum())
        self.assertEqual(self.steps, [])

    def test_middle_page_bottom_wheel_down_goes_next(self) -> None:
        self._show_page(1)
        vbar = self.view.verticalScrollBar()
        vbar.setValue(vbar.maximum())
        _wheel(self.view, -120)
        self.assertEqual(self.steps, [1])
        self.assertEqual(vbar.value(), vbar.minimum())

    def test_middle_page_top_wheel_up_goes_previous(self) -> None:
        self._show_page(1)
        vbar = self.view.verticalScrollBar()
        vbar.setValue(vbar.minimum())
        _wheel(self.view, 120)
        self.assertEqual(self.steps, [-1])
        self.assertEqual(vbar.value(), vbar.maximum())


if __name__ == "__main__":
    unittest.main()
