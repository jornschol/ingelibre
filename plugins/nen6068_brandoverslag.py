# SPDX-License-Identifier: GPL-3.0-or-later
"""IngeTrazo — NEN 6068 Brandoverslag extension.

Stage 1: read-only inventory. Stage 2: explicit role and opening association
using stable group identities. No NEN calculation is performed here.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
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


def find_group_by_uid(groups, uid):
    """Resolve a saved group identity against the current document tree."""
    if not uid:
        return None
    return next((group for group in _walk_groups(groups)
                 if getattr(group, "uid", None) == uid), None)


def group_selection_choices(groups):
    """Return explicit, stable-ID choices; IFC tags are descriptive only."""
    choices = []
    for group in _walk_groups(groups):
        uid = getattr(group, "uid", None)
        if not uid:
            continue
        ifc_class = ((getattr(group, "ifc", None) or {}).get("class") or "")
        label = getattr(group, "name", "") or tr("Naamloze groep")
        if ifc_class:
            label += f" [{ifc_class}]"
        label += f" · {uid[:6]}"
        choices.append((label, uid))
    return choices


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


def _world_points(points, matrix):
    """Map local QVector3D points to world coordinates without mutating them."""
    if matrix is None:
        return [type(p)(p) for p in points]
    return [matrix.map(p) for p in points]


def _newell_normal(points):
    """Return a unit normal from world-space polygon points; None if degenerate."""
    from PySide6.QtGui import QVector3D

    n = QVector3D()
    for i, point in enumerate(points):
        nxt = points[(i + 1) % len(points)]
        n += QVector3D(
            (point.y() - nxt.y()) * (point.z() + nxt.z()),
            (point.z() - nxt.z()) * (point.x() + nxt.x()),
            (point.x() - nxt.x()) * (point.y() + nxt.y()),
        )
    length = n.length()
    return n / length if length > 1e-9 else None


def _polygon_area(points):
    """Area of a planar world-space polygon, independent of placement scale."""
    if len(points) < 3:
        return 0.0
    # The length of the Newell vector is twice the polygon area.
    from PySide6.QtGui import QVector3D
    n = QVector3D()
    for i, point in enumerate(points):
        nxt = points[(i + 1) % len(points)]
        n += QVector3D(
            (point.y() - nxt.y()) * (point.z() + nxt.z()),
            (point.z() - nxt.z()) * (point.x() + nxt.x()),
            (point.x() - nxt.x()) * (point.y() + nxt.y()),
        )
    return 0.5 * n.length()


def group_world_faces(group):
    """Extract world-space face geometry from a group tree, preserving holes.

    This is a read-only geometric representation. It deliberately does not
    infer whether a face is a facade or whether a hole is a fire-relevant
    opening; those remain explicit modelling/assessment decisions.
    """
    from core.group import iter_placements

    result = []
    for placed, matrix in iter_placements(group):
        for index, face in enumerate(getattr(placed.mesh, "faces", ())):
            outer = _world_points([v.position for v in face.loop], matrix)
            holes = [
                _world_points([v.position for v in loop], matrix)
                for loop in face.hole_loops
            ]
            result.append({
                "group": getattr(placed, "name", ""),
                "face_index": index,
                "vertices": outer,
                "holes": holes,
                "normal": _newell_normal(outer),
                "area": _polygon_area(outer),
                "attrs": dict(getattr(face, "attrs", None) or {}),
            })
    return result


def windowizer_world_outline(group, data=None):
    """Return a Windowizer opening contour in world coordinates.

    Windowizer stores the contour in local X/Z coordinates and its placement
    on the child parts. The child's composed placement is authoritative after
    the window or a containing component has been moved or rotated.
    """
    data = data if data is not None else _windowizer_data(group)
    if data is None:
        return None

    from core.group import iter_placements
    from PySide6.QtGui import QMatrix4x4, QVector3D

    matrix = None
    placements = iter_placements(group)
    next(placements, None)  # container placement
    for _part, candidate in placements:
        matrix = candidate
        break

    if matrix is None:
        values = data.get("pose")
        if isinstance(values, list) and len(values) == 16:
            rows = [values[col * 4 + row]
                    for row in range(4) for col in range(4)]
            matrix = QMatrix4x4(*rows)
            parent = getattr(group, "xform", None)
            if parent is not None:
                matrix = parent * matrix

    try:
        local = [QVector3D(float(p[0]), float(p[1]), float(p[2]))
                 for p in data["outline"]]
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    if len(local) < 3:
        return None
    return _world_points(local, matrix)


def _outline_dimensions(points):
    """Measure opening width/height in its own plane, not world X/Z."""
    from PySide6.QtGui import QVector3D

    if len(points) < 3:
        return None
    normal = _newell_normal(points)
    if normal is None:
        return None
    x_axis = points[1] - points[0]
    if x_axis.length() < 1e-9:
        return None
    x_axis.normalize()
    z_axis = QVector3D.crossProduct(normal, x_axis)
    if z_axis.length() < 1e-9:
        return None
    z_axis.normalize()
    xs = [QVector3D.dotProduct(point, x_axis) for point in points]
    zs = [QVector3D.dotProduct(point, z_axis) for point in points]
    return max(xs) - min(xs), max(zs) - min(zs)


def inspect_scene(scene):
    """Build a lightweight, read-only inventory; do not copy or mutate meshes."""
    rows = []
    tagged_groups = 0
    windowizer_count = 0
    from core.group import iter_placements

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

        # Count actual faces in this group tree without flattening/copying it.
        face_count = sum(len(placed.mesh.faces)
                         for placed, _matrix in iter_placements(group))
        note = ""
        if data is not None:
            outline = windowizer_world_outline(group, data)
            if outline is not None:
                dimensions = _outline_dimensions(outline)
                normal = _newell_normal(outline)
                if normal is not None and dimensions is not None:
                    width, height = dimensions
                    note = tr("Wereldcontour: {width:.3f} × {height:.3f} m; "
                              "normaal ({nx:.2f}, {ny:.2f}, {nz:.2f})",
                              width=width, height=height,
                              nx=normal.x(), ny=normal.y(), nz=normal.z())
                else:
                    note = tr("Windowizer-contour aanwezig; vlakrichting niet bepaald")
            else:
                note = tr("Windowizer-contour aanwezig; plaatsing niet leesbaar")
        elif tag.get("class") == "IfcWall":
            faces = group_world_faces(group)
            vertical = sum(1 for face in faces
                           if face["normal"] is not None
                           and abs(face["normal"].z()) < 0.2)
            note = tr("Geometrie: {faces} vlakken, {vertical} verticale vlakken; "
                      "gevelidentificatie nog niet bevestigd",
                      faces=len(faces), vertical=vertical)
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
    """Inventory and explicit model-role association for the NEN 6068 workflow."""

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

        # Explicit object association. IFC tags help identify candidates but
        # never decide which object fulfils a NEN 6068 role.
        selection_heading = QLabel(tr("Modelonderdelen voor de berekening"))
        selection_heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(selection_heading)
        selection_form = QFormLayout()
        self._selection_combos = {}
        selection_roles = (
            ("source_building", tr("Brongebouw")),
            ("receiving_building", tr("Ontvangend gebouw")),
            ("source_facade", tr("Brongevel")),
            ("receiving_facade", tr("Ontvangende gevel")),
            ("fire_compartment", tr("Brandcompartiment")),
        )
        for key, label in selection_roles:
            combo = QComboBox()
            combo.addItem(tr("— niet geselecteerd —"), None)
            combo.currentIndexChanged.connect(self._save_selection)
            self._selection_combos[key] = combo
            selection_form.addRow(label, combo)
        layout.addLayout(selection_form)
        self.opening_lists = {}
        for key, label in (("source_openings", tr("Openingen brongevel")),
                           ("receiving_openings", tr("Openingen ontvangende gevel"))):
            opening_list = QListWidget()
            opening_list.setMaximumHeight(105)
            opening_list.itemChanged.connect(self._save_opening_selection)
            self.opening_lists[key] = opening_list
            selection_form.addRow(label, opening_list)
        self.selection_status = QLabel()
        self.selection_status.setWordWrap(True)
        layout.addWidget(self.selection_status)

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
            tr("De geometrie wordt niet gewijzigd. Gebouwen, gevels en het "
               "brandcompartiment worden handmatig aan een rol gekoppeld. "
               "Vink per gevel de bijbehorende Windowizer-openingen aan. "
               "IFC-tags zijn alleen herkenningshulp; er worden nog geen "
               "NEN 6068-resultaten berekend.")
        )
        self.scope.setWordWrap(True)
        self.scope.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.scope)

        self.refresh()

    def _refresh_selection_choices(self) -> None:
        """Rebuild role selectors while retaining saved stable group IDs."""
        state = self.app.document_data({}) or {}
        selected = state.get("selection", {})
        groups = list(_walk_groups(getattr(self.app.scene, "groups", None)))
        choices = group_selection_choices(groups)
        available = {uid for _label, uid in choices}
        for key, combo in self._selection_combos.items():
            combo.blockSignals(True)
            current_uid = selected.get(key)
            combo.clear()
            combo.addItem(tr("— niet geselecteerd —"), None)
            for label, uid in choices:
                combo.addItem(label, uid)
            index = combo.findData(current_uid) if current_uid in available else 0
            combo.setCurrentIndex(max(index, 0))
            combo.blockSignals(False)
        opening_choices = []
        for group in groups:
            if _windowizer_data(group) is None or not getattr(group, "uid", None):
                continue
            name = getattr(group, "name", "") or tr("Naamloos raam")
            opening_choices.append((f"{name} · {group.uid[:6]}", group.uid))
        for key, opening_list in self.opening_lists.items():
            opening_list.blockSignals(True)
            opening_list.clear()
            checked = set(selected.get(key, []))
            for label, uid in opening_choices:
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, uid)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if uid in checked else Qt.Unchecked)
                opening_list.addItem(item)
            opening_list.blockSignals(False)
        chosen = sum(1 for key in self._selection_combos
                     if selected.get(key) in available)
        opening_count = sum(
            1 for key in self.opening_lists
            for uid in selected.get(key, []) if uid in {u for _label, u in opening_choices}
        )
        self.selection_status.setText(
            tr("{chosen} van de {total} rollen gekoppeld; {openings} openingen "
               "aan gevels toegewezen. Controleer de objectkeuze: IFC-tags "
               "worden niet als automatische roltoewijzing gebruikt.",
               chosen=chosen, total=len(self._selection_combos),
               openings=opening_count)
        )

    def _save_selection(self, _index=None) -> None:
        """Persist role assignments by stable group UID, never by row/name."""
        state = self.app.document_data({}) or {}
        selection = state.get("selection", {})
        selection.update({
            key: combo.currentData()
            for key, combo in self._selection_combos.items()
        })
        state["selection"] = selection
        self.app.set_document_data(state)

    def _save_opening_selection(self, _item=None) -> None:
        """Persist checked Windowizer opening UIDs for each selected facade."""
        state = self.app.document_data({}) or {}
        selection = state.get("selection", {})
        for key, opening_list in self.opening_lists.items():
            selection[key] = [
                opening_list.item(i).data(Qt.UserRole)
                for i in range(opening_list.count())
                if opening_list.item(i).checkState() == Qt.Checked
            ]
        state["selection"] = selection
        self.app.set_document_data(state)

    def refresh(self) -> None:
        """Refresh the read-only inventory and explicit object selectors."""
        try:
            inventory = inspect_scene(self.app.scene)
            self._refresh_selection_choices()
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
