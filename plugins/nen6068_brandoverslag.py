# SPDX-License-Identifier: GPL-3.0-or-later
"""IngeTrazo — NEN 6068 Brandoverslag extension.

Initial integration skeleton. This panel deliberately does not calculate
fire spread yet: the NEN 6068 calculation engine will be implemented and
validated separately before results are presented as compliance evidence.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from core.i18n import tr


class BrandoverslagPanel(QWidget):
    """Read-only starting point for the NEN 6068 workflow."""

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app

        layout = QVBoxLayout(self)
        heading = QLabel(tr("NEN 6068 — Brandoverslag"))
        heading.setStyleSheet("font-weight: 600; font-size: 15px;")
        layout.addWidget(heading)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.model_summary = QLabel()
        self.model_summary.setWordWrap(True)
        layout.addWidget(self.model_summary)

        self.refresh_button = QPushButton(tr("Modelgegevens vernieuwen"))
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)

        self.scope = QLabel(
            tr("Eerste ontwikkelfase: koppeling met het IngeTrazo-model. "
               "De rekenkern, vlamgeometrie en stralingsberekening worden "
               "in afzonderlijke, toetsbare stappen toegevoegd.")
        )
        self.scope.setWordWrap(True)
        self.scope.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.scope)
        layout.addStretch(1)

        self.refresh()

    def refresh(self) -> None:
        """Read basic model counts without changing the document."""
        try:
            scene = self.app.scene
            loose_faces = len(scene.loose_mesh.faces)
            groups = list(scene.groups)
            self.status.setText(tr("Modelkoppeling actief."))
            self.model_summary.setText(
                tr("Losse geometrie: {faces} vlakken\n"
                   "Groepen: {groups}",
                   faces=loose_faces, groups=len(groups))
            )
        except Exception as exc:  # Keep a UI refresh failure non-fatal.
            self.status.setText(tr("Modelgegevens konden niet worden gelezen: {error}",
                                   error=str(exc)))
            self.model_summary.clear()


def setup(app) -> None:
    """Register the extension panel and its refresh lifecycle."""
    panel = BrandoverslagPanel(app)
    dock = app.add_panel(tr("NEN 6068 Brandoverslag"), panel)
    app.add_menu_action(
        tr("NEN 6068 Brandoverslag"),
        lambda: app.show_panel(dock),
        tip=tr("Open the NEN 6068 fire-spread extension panel."),
    )
    app.on_document_changed(panel.refresh)
