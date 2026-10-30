# SPDX-License-Identifier: GPL-3.0-or-later
"""IngeTrazo — NEN 6068 Brandoverslag extension.

Stage 1: read-only inventory of BIM-tagged groups, loose BIM faces and
Windowizer opening metadata. No NEN calculation is performed here.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr


WINDOWIZER_KEY = "windowizer"


def _walk_groups(groups):
    """Yield every group placement in the document, including nested parts."""
    for group in groups or ():
        yield group
        yield from _walk_groups(getattr(group, "children", None) or ())


def _windowizer_data(group):
    """Return the stored Windowizer outline record, if this is such a window."""
    ext = getattr(group, "ext", None) or {}
    data = ext.get(WINDOWIZER_KEY)
    if data is None:
        # Compatibility with the first Windowizer format.
        data = (getattr(group, "ifc", None) or {}).get(WINDOWIZER_KEY)
    if isinstance(data, dict) and isinstance(data.get("outline"), list):
        return data
    return None


def _outline_size(outline):
    """Width and height of the Windowizer's local X/Z outline, in metres."""
    try:
        points = [(float(p[0]), float(p[2])) for p in outline]
        if len(points) < 3:
            return None
        return (
            max(p[0] for p in points) - min(p[0] for p in points),
            max(p[1] for p in points) - min(p[1] for p in points),
        )
    except (TypeError, ValueError, IndexError):
        return None


def inspect_scene(scene):
    """Build a lightweight, read-only inventory; do not copy or mutate meshes."""
    rows = []
    tagged_groups = 0
    windowizer_count = 0

    for group in _walk_groups(getattr(scene, "groups", None)):
        tag = getattr(group, "ifc", None) or {}
        data = _windowizer_data(group)
        if tag:
            tagged_groups += 1
        if data is not None:
            windowizer_count += 1

        # Show tagged objects and Windowizer windows. Untagged helper parts
        # remain hidden unless they are themselves a Windowizer container.
        if not tag and data is None:
            continue

        parts = [group]
        # Count actual faces in this group tree without flattening/copying it.
        from core.group import iter_placements
        face_count = sum(len(placed.mesh.faces)
                         for placed, _matrix in iter_placements(group))
        note = ""
        if data is not None:
            size = _outline_size(data["outline"])
            if size is not None:
                note = tr("Windowizer-contour: {width:.3f} × {height:.3f} m",
                          width=size[0], height=size[1])
            else:
                note = tr("Windowizer-contour aanwezig; afmetingen niet leesbaar")
        rows.append({
            "name": getattr(group, "name", ""),
            "ifc": tag.get("class", tr("Geen IFC-classificatie")),
            "kind": tr("Groep"),
            "faces": face_count,
            "note": note,
        })

    # Loose faces carry BIM tags individually; report their object groups
    # without calculating quantities or attempting to infer building bounds.
    loose_by_id = {}
    loose_mesh = getattr(scene, "loose_mesh", None)
    for face in getattr(loose_mesh, "faces", ()) if loose_mesh else ():
        tag = (getattr(face, "attrs", None) or {}).get("ifc")
        if not isinstance(tag, dict):
            continue
        key = (tag.get("id"), tag.get("class", ""), tag.get("name", ""))
        loose_by_id[key] = loose_by_id.get(key, 0) + 1

    for (_obj_id, ifc_class, name), count in sorted(
            loose_by_id.items(), key=lambda item: (str(item[0][1]), str(item[0][2]))):
        rows.append({
            "name": name or tr("Naamloos BIM-object"),
            "ifc": ifc_class or tr("Onbekende IFC-klasse"),
            "kind": tr("Losse vlakken"),
            "faces": count,
            "note": tr("BIM-tag op losse geometrie"),
        })

    return {
        "rows": rows,
        "tagged_groups": tagged_groups,
        "loose_objects": len(loose_by_id),
        "windowizer_count": windowizer_count,
        "group_count": len(getattr(scene, "groups", ()) or ()),
        "loose_faces": len(getattr(loose_mesh, "faces", ()) or ()),
    }


class BrandoverslagPanel(QWidget):
    """Read-only starting point for the NEN 6068 model workflow."""

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

        self.inventory = QTableWidget(0, 5)
        self.inventory.setHorizontalHeaderLabels([
            tr("Naam"), tr("IFC-klasse"), tr("Type"), tr("Vlakken"), tr("Openingsgegevens")
        ])
        self.inventory.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.inventory.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.inventory.setSelectionMode(QAbstractItemView.SingleSelection)
        self.inventory.verticalHeader().setVisible(False)
        self.inventory.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        for column in (1, 2, 3, 4):
            self.inventory.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents)
        layout.addWidget(self.inventory, 1)

        self.refresh_button = QPushButton(tr("Modelgegevens vernieuwen"))
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)

        self.scope = QLabel(
            tr("Deze fase leest alleen bestaande modelgegevens. "
               "Gebouwen en brandcompartimenten worden niet automatisch afgeleid "
               "uit IFC-tags. Controleer daarom de objectclassificaties en "
               "openingsgegevens voordat een berekening wordt opgezet. "
               "Er worden nog geen NEN 6068-resultaten berekend.")
        )
        self.scope.setWordWrap(True)
        self.scope.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.scope)

        self.refresh()

    def refresh(self) -> None:
        """Refresh the read-only model inventory."""
        try:
            inventory = inspect_scene(self.app.scene)
            self.status.setText(tr("Modelkoppeling actief."))
            self.model_summary.setText(
                tr("Groepen: {groups} · BIM-geclassificeerde groepen: {tagged} · "
                   "Losse vlakken: {faces} · Losse BIM-objecten: {objects} · "
                   "Windowizer-ramen: {windows}",
                   groups=inventory["group_count"],
                   tagged=inventory["tagged_groups"],
                   faces=inventory["loose_faces"],
                   objects=inventory["loose_objects"],
                   windows=inventory["windowizer_count"])
            )

            self.inventory.setRowCount(len(inventory["rows"]))
            for row_index, row in enumerate(inventory["rows"]):
                values = (
                    row["name"], row["ifc"], row["kind"],
                    str(row["faces"]), row["note"],
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 3:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.inventory.setItem(row_index, column, item)
            self.inventory.resizeRowsToContents()
        except Exception as exc:  # Keep a UI refresh failure non-fatal.
            self.status.setText(tr("Modelgegevens konden niet worden gelezen: {error}",
                                   error=str(exc)))
            self.model_summary.clear()
            self.inventory.setRowCount(0)


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
