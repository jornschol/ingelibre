# SPDX-License-Identifier: GPL-3.0-or-later
"""IngeTrazo — NEN 6068 Brandoverslag extension.

Opening discovery is based on the named face material "gevelopening".
Windowizer is deliberately not used. This stage inventories and associates
geometry only; it does not perform a NEN 6068 calculation.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QHeaderView, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.i18n import tr

OPENING_MATERIAL = "gevelopening"


def _walk_groups(groups):
    for group in groups or ():
        yield group
        yield from _walk_groups(getattr(group, "children", None) or ())


def find_group_by_uid(groups, uid):
    if not uid:
        return None
    return next((g for g in _walk_groups(groups)
                 if getattr(g, "uid", None) == uid), None)


def group_selection_choices(groups):
    choices = []
    for group in _walk_groups(groups):
        uid = getattr(group, "uid", None)
        if not uid:
            continue
        ifc_class = ((getattr(group, "ifc", None) or {}).get("class") or "")
        label = getattr(group, "name", "") or tr("Naamloze groep")
        if ifc_class:
            label += f" [{ifc_class}]"
        choices.append((f"{label} · {uid[:6]}", uid))
    return choices


def loose_facade_selection_choices(scene):
    grouped = {}
    loose_mesh = getattr(scene, "loose_mesh", None)
    for face in getattr(loose_mesh, "faces", ()) if loose_mesh else ():
        tag = (getattr(face, "attrs", None) or {}).get("ifc")
        if not isinstance(tag, dict) or tag.get("class") != "IfcWall":
            continue
        obj_id = tag.get("id")
        if not isinstance(obj_id, (int, str)) or str(obj_id) == "":
            continue
        entry = grouped.setdefault(str(obj_id), {
            "name": tag.get("name") or tr("Naamloze IFC-wand"), "faces": 0})
        entry["faces"] += 1
    return [
        (f'{v["name"]} [IfcWall] · {v["faces"]} vlakken · IFC {key}',
         f"faces:{key}")
        for key, v in sorted(grouped.items())
    ]


def facade_selection_choices(scene):
    groups = list(_walk_groups(getattr(scene, "groups", None)))
    return group_selection_choices(groups) + loose_facade_selection_choices(scene)


def resolve_facade_selection(scene, reference):
    if isinstance(reference, str) and reference.startswith("faces:"):
        obj_id = reference.split(":", 1)[1]
        faces = []
        loose = getattr(scene, "loose_mesh", None)
        for face in getattr(loose, "faces", ()) if loose else ():
            tag = (getattr(face, "attrs", None) or {}).get("ifc")
            if (isinstance(tag, dict) and tag.get("class") == "IfcWall"
                    and str(tag.get("id")) == obj_id):
                faces.append(face)
        return {"kind": "faces", "id": obj_id, "faces": faces} if faces else None
    group = find_group_by_uid(getattr(scene, "groups", None), reference)
    return {"kind": "group", "group": group} if group is not None else None


def _opening_ref(group, face_index):
    """Document-persistent reference for a marked face in a placed group."""
    return f"{group.uid}:{face_index}"


def _parse_opening_ref(reference):
    try:
        uid, index = reference.rsplit(":", 1)
        return uid, int(index)
    except (AttributeError, ValueError):
        return None, None


def _opening_faces_in_group_tree(root):
    """Find marked faces under root and return their world-space geometry.

    Face identity is group UID + face index. The placement matrix comes from
    iter_placements, so nested transforms and mirrored instances are included.
    """
    from core.group import iter_placements

    result = []
    for placed, matrix in iter_placements(root):
        for index, face in enumerate(getattr(placed.mesh, "faces", ())):
            attrs = getattr(face, "attrs", None) or {}
            if attrs.get("mat") != OPENING_MATERIAL:
                continue
            points = [v.position for v in face.loop]
            world = [matrix.map(p) for p in points] if matrix is not None else [
                type(p)(p) for p in points]
            if len(world) < 3:
                continue
            result.append({
                "ref": _opening_ref(placed, index),
                "name": getattr(placed, "name", "") or tr("Gevelopening"),
                "vertices": world,
                "attrs": dict(attrs),
            })
    return result


def find_openings_in_building(scene, building_uid):
    building = find_group_by_uid(getattr(scene, "groups", None), building_uid)
    return _opening_faces_in_group_tree(building) if building is not None else []


def resolve_opening_reference(scene, reference):
    uid, index = _parse_opening_ref(reference)
    group = find_group_by_uid(getattr(scene, "groups", None), uid)
    if group is None or index is None:
        return None
    faces = getattr(getattr(group, "mesh", None), "faces", ())
    if index < 0 or index >= len(faces):
        return None
    face = faces[index]
    if (getattr(face, "attrs", None) or {}).get("mat") != OPENING_MATERIAL:
        return None
    return {"group": group, "face": face, "face_index": index}



def _point_tuple(point):
    return (float(point.x()), float(point.y()), float(point.z()))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _add_scaled(a, b, scale):
    return tuple(x + scale * y for x, y in zip(a, b))


def _distance_squared(a, b):
    return _dot(_sub(a, b), _sub(a, b))


def _point_triangle_distance_squared(point, a, b, c):
    """Squared distance from a point to a triangle (Ericson region tests)."""
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(point, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return _distance_squared(point, a)
    bp = _sub(point, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return _distance_squared(point, b)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3)
        return _distance_squared(point, _add_scaled(a, ab, v))
    cp = _sub(point, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return _distance_squared(point, c)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6)
        return _distance_squared(point, _add_scaled(a, ac, w))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        edge = _sub(c, b)
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return _distance_squared(point, _add_scaled(b, edge, w))
    denom = 1.0 / (va + vb + vc)
    v, w = vb * denom, vc * denom
    closest = _add_scaled(_add_scaled(a, ab, v), ac, w)
    return _distance_squared(point, closest)


def _segment_segment_distance_squared(p1, q1, p2, q2):
    """Squared minimum distance between two finite 3D line segments."""
    d1, d2, r = _sub(q1, p1), _sub(q2, p2), _sub(p1, p2)
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    epsilon = 1e-12
    if a <= epsilon and e <= epsilon:
        return _distance_squared(p1, p2)
    if a <= epsilon:
        s, t = 0.0, max(0.0, min(1.0, f / e))
    else:
        c = _dot(d1, r)
        if e <= epsilon:
            t, s = 0.0, max(0.0, min(1.0, -c / a))
        else:
            b = _dot(d1, d2)
            denom = a * e - b * b
            s = max(0.0, min(1.0, (b * f - c * e) / denom)) if abs(denom) > epsilon else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t, s = 0.0, max(0.0, min(1.0, -c / a))
            elif t > 1.0:
                t, s = 1.0, max(0.0, min(1.0, (b - c) / a))
    c1, c2 = _add_scaled(p1, d1, s), _add_scaled(p2, d2, t)
    return _distance_squared(c1, c2)


def _segment_intersects_triangle(p, q, a, b, c):
    """Möller–Trumbore segment/triangle intersection test."""
    direction = _sub(q, p)
    edge1, edge2 = _sub(b, a), _sub(c, a)
    h = (
        direction[1] * edge2[2] - direction[2] * edge2[1],
        direction[2] * edge2[0] - direction[0] * edge2[2],
        direction[0] * edge2[1] - direction[1] * edge2[0],
    )
    det = _dot(edge1, h)
    if abs(det) < 1e-10:
        return False
    inv_det = 1.0 / det
    offset = _sub(p, a)
    u = inv_det * _dot(offset, h)
    if u < -1e-9 or u > 1.0 + 1e-9:
        return False
    cross = (
        offset[1] * edge1[2] - offset[2] * edge1[1],
        offset[2] * edge1[0] - offset[0] * edge1[2],
        offset[0] * edge1[1] - offset[1] * edge1[0],
    )
    v = inv_det * _dot(direction, cross)
    if v < -1e-9 or u + v > 1.0 + 1e-9:
        return False
    t = inv_det * _dot(edge2, cross)
    return -1e-9 <= t <= 1.0 + 1e-9


def _triangle_distance_squared(first, second):
    a, b, c = first
    d, e, f = second
    if any(_segment_intersects_triangle(p, q, d, e, f)
           for p, q in ((a, b), (b, c), (c, a))):
        return 0.0
    if any(_segment_intersects_triangle(p, q, a, b, c)
           for p, q in ((d, e), (e, f), (f, d))):
        return 0.0
    distances = [
        *(_point_triangle_distance_squared(p, d, e, f) for p in first),
        *(_point_triangle_distance_squared(p, a, b, c) for p in second),
    ]
    for p, q in ((a, b), (b, c), (c, a)):
        for r, t in ((d, e), (e, f), (f, d)):
            distances.append(_segment_segment_distance_squared(p, q, r, t))
    return min(distances)


def _triangulate_points(points):
    """Fan-triangulate a planar polygon; opening faces are expected to be simple."""
    points = [_point_tuple(p) if hasattr(p, "x") else tuple(p) for p in points]
    return [(points[0], points[i], points[i + 1])
            for i in range(1, len(points) - 1)] if len(points) >= 3 else []


def _world_mesh_triangles(group):
    from core.group import iter_placements

    triangles = []
    for placed, matrix in iter_placements(group):
        for face in getattr(placed.mesh, "faces", ()):
            points = [v.position for v in face.loop]
            if matrix is not None:
                points = [matrix.map(point) for point in points]
            triangles.extend(_triangulate_points(points))
    return triangles


def _opening_to_building_distance(opening, building):
    """Minimum surface distance from an opening polygon to a building mesh."""
    opening_triangles = _triangulate_points(opening.get("vertices", ()))
    building_triangles = _world_mesh_triangles(building)
    if not opening_triangles or not building_triangles:
        return None
    best = float("inf")
    for source_triangle in opening_triangles:
        for building_triangle in building_triangles:
            best = min(best, _triangle_distance_squared(
                source_triangle, building_triangle))
            if best <= 1e-12:
                return 0.0
    return best ** 0.5


def top_level_buildings(scene, source_building_uid=None):
    """Return other top-level scene groups as candidate neighbouring buildings."""
    return [
        group for group in (getattr(scene, "groups", None) or ())
        if getattr(group, "uid", None)
        and group.uid != source_building_uid
    ]


def find_nearby_buildings(scene, source_building_uid, opening,
                          max_distance=15.0):
    """Find every other top-level group within max_distance of one opening.

    Distances are between the opening polygon and the actual placed building
    surfaces, including nested group/component transforms.
    """
    matches = []
    for building in top_level_buildings(scene, source_building_uid):
        distance = _opening_to_building_distance(opening, building)
        if distance is not None and distance <= max_distance + 1e-9:
            matches.append({
                "uid": building.uid,
                "name": getattr(building, "name", "") or tr("Naamloos gebouw"),
                "distance": distance,
                "openings": _opening_faces_in_group_tree(building),
            })
    return sorted(matches, key=lambda item: item["distance"])

def inspect_scene(scene):
    rows = []
    tagged_groups = 0
    opening_count = 0
    for group in _walk_groups(getattr(scene, "groups", None)):
        tag = getattr(group, "ifc", None) or {}
        if tag:
            tagged_groups += 1
        # The inventory row shows the total for this group tree, including
        # nested placements. The scene-wide count below still counts each
        # group's own mesh once as _walk_groups visits every group separately.
        own_faces = getattr(getattr(group, "mesh", None), "faces", ())
        face_count = len(own_faces)
        own_openings = sum(
            1 for face in own_faces
            if (getattr(face, "attrs", None) or {}).get("mat") == OPENING_MATERIAL
        )
        group_openings = len(_opening_faces_in_group_tree(group))
        # Keep a parent row when it contains openings in nested groups too.
        if not tag and not group_openings:
            continue
        opening_count += own_openings
        rows.append({
            "name": getattr(group, "name", ""),
            "ifc": tag.get("class", tr("Geen IFC-classificatie")),
            "kind": tr("Groep"),
            "faces": face_count,
            "note": tr("{count} gevelopening(en) totaal", count=group_openings)
                    if group_openings else "",
        })

    loose_mesh = getattr(scene, "loose_mesh", None)
    loose_openings = sum(
        1 for face in getattr(loose_mesh, "faces", ()) if loose_mesh
        if (getattr(face, "attrs", None) or {}).get("mat") == OPENING_MATERIAL
    )
    opening_count += loose_openings
    if loose_openings:
        rows.append({
            "name": tr("Losse geometrie"), "ifc": "",
            "kind": tr("Losse vlakken"), "faces": loose_openings,
            "note": tr("{count} gevelopening(en)", count=loose_openings),
        })
    return {
        "rows": rows, "tagged_groups": tagged_groups,
        "opening_count": opening_count,
        "group_count": len(getattr(scene, "groups", ()) or ()),
        "loose_faces": len(getattr(loose_mesh, "faces", ()) or ()),
    }


def building_selection_choices(scene):
    """Only top-level scene groups represent buildings in this workflow."""
    return group_selection_choices(getattr(scene, "groups", None))


def analyse_source_building(scene, source_building_uid, max_distance=15.0):
    """Return every marked source opening and its nearby top-level buildings."""
    openings = find_openings_in_building(scene, source_building_uid)
    return [{
        "opening": opening,
        "nearby_buildings": find_nearby_buildings(
            scene, source_building_uid, opening, max_distance=max_distance
        ),
    } for opening in openings]


def validate_selection(scene, selection):
    selection = selection if isinstance(selection, dict) else {}
    source_uid = selection.get("source_building")
    source = next((group for group in (getattr(scene, "groups", None) or ())
                   if getattr(group, "uid", None) == source_uid), None)
    errors, warnings, resolved = [], [], {}
    if source is None:
        errors.append("Geen geldig brongebouw geselecteerd.")
        analysis = []
    else:
        resolved["source_building"] = source
        # Temporary modelling assumption: the complete source building is
        # the fire compartment. Keep this alias for future calculation code.
        resolved["fire_compartment"] = source
        analysis = analyse_source_building(scene, source_uid)

    if source is not None and not analysis:
        warnings.append(
            f"Geen vlakken met materiaal '{OPENING_MATERIAL}' gevonden in het brongebouw."
        )

    nearby_count = sum(len(item["nearby_buildings"]) for item in analysis)
    if analysis and not nearby_count:
        warnings.append(
            "Geen andere top-level gebouwen binnen 15 meter van de bronopeningen gevonden."
        )

    return {
        "errors": errors,
        "warnings": warnings,
        "valid": not errors,
        "resolved": resolved,
        "source_openings": [item["opening"] for item in analysis],
        "opening_analysis": analysis,
        "nearby_building_count": nearby_count,
    }


class BrandoverslagPanel(QWidget):
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

        selection_form = QFormLayout()
        self.source_building = QComboBox()
        self.source_building.addItem(tr("— selecteer brongebouw —"), None)
        self.source_building.currentIndexChanged.connect(self._save_selection)
        selection_form.addRow(tr("Brongebouw / brandcompartiment"), self.source_building)
        layout.addLayout(selection_form)

        self.source_openings = QListWidget()
        self.source_openings.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(QLabel(tr("Bronopeningen en nabijgelegen gebouwen")))
        layout.addWidget(self.source_openings, 1)

        self.selection_status = QLabel()
        self.selection_status.setWordWrap(True)
        layout.addWidget(self.selection_status)
        self.validation_status = QLabel()
        self.validation_status.setWordWrap(True)
        layout.addWidget(self.validation_status)

        self.inventory = QTableWidget(0, 5)
        self.inventory.setHorizontalHeaderLabels([
            tr("Naam"), tr("IFC-klasse"), tr("Type"), tr("Vlakken"), tr("Openingsgegevens")
        ])
        self.inventory.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.inventory.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.inventory.setSelectionMode(QAbstractItemView.SingleSelection)
        self.inventory.verticalHeader().setVisible(False)
        self.inventory.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3, 4):
            self.inventory.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        layout.addWidget(self.inventory, 1)

        self.refresh_button = QPushButton(tr("Modelgegevens vernieuwen"))
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)
        self.scope = QLabel(
            tr("Selecteer één top-level groep als brongebouw. Geneste groepen en "
               "componenten horen bij dat gebouw. Vlakken met materiaal "
               "'gevelopening' worden per opening onderzocht op andere top-level "
               "gebouwen binnen 15 meter. Dit is alleen geometrische detectie; "
               "er worden nog geen NEN 6068-berekeningen of vlamvisualisaties gemaakt.")
        )
        self.scope.setWordWrap(True)
        self.scope.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.scope)
        self.refresh()

    def _refresh_selection_choices(self):
        state = self.app.document_data({}) or {}
        selected = state.get("selection", {})
        self.source_building.blockSignals(True)
        self.source_building.clear()
        self.source_building.addItem(tr("— selecteer brongebouw —"), None)
        for label, uid in building_selection_choices(self.app.scene):
            self.source_building.addItem(label, uid)
        index = self.source_building.findData(selected.get("source_building"))
        self.source_building.setCurrentIndex(index if index >= 0 else 0)
        self.source_building.blockSignals(False)

        report = validate_selection(self.app.scene, selected)
        self.source_openings.clear()
        for item in report["opening_analysis"]:
            opening = item["opening"]
            nearby = item["nearby_buildings"]
            if not nearby:
                summary = tr("Geen ander gebouw binnen 15 m")
            else:
                summary = "; ".join(
                    tr("{name}: {distance:.2f} m · {openings} gemarkeerde opening(en)",
                       name=building["name"], distance=building["distance"],
                       openings=len(building["openings"]))
                    for building in nearby
                )
            row = QListWidgetItem(f'{opening["name"]} — {summary}')
            row.setToolTip(opening["ref"])
            self.source_openings.addItem(row)

        self.selection_status.setText(
            tr("{openings} bronopeningen onderzocht · {nearby} gebouw/opening-nabijheidsrelaties gevonden.",
               openings=len(report["source_openings"]),
               nearby=report["nearby_building_count"])
        )
        self._update_validation(selected)

    def _update_validation(self, selection=None):
        selection = selection if selection is not None else (
            self.app.document_data({}) or {}).get("selection", {})
        report = validate_selection(self.app.scene, selection)
        messages = (["Fouten:"] + ["• " + x for x in report["errors"]]
                    if report["errors"] else ["Brongebouwselectie is geldig."])
        if report["warnings"]:
            messages += ["Aandachtspunten:"] + ["• " + x for x in report["warnings"]]
        self.validation_status.setText("\n".join(messages))

    def _save_selection(self, _index=None):
        state = self.app.document_data({}) or {}
        selection = state.get("selection", {})
        selection["source_building"] = self.source_building.currentData()
        state["selection"] = selection
        self.app.set_document_data(state)
        self._refresh_selection_choices()

    def refresh(self):
        try:
            inventory = inspect_scene(self.app.scene)
            self._refresh_selection_choices()
            self.status.setText(tr("Modelkoppeling actief."))
            self.model_summary.setText(
                tr("Top-level gebouwen: {groups} · BIM-geclassificeerde groepen: {tagged} · "
                   "Losse vlakken: {faces} · Gemarkeerde gevelopeningen: {openings}",
                   groups=len(getattr(self.app.scene, "groups", ()) or ()),
                   tagged=inventory["tagged_groups"],
                   faces=inventory["loose_faces"], openings=inventory["opening_count"])
            )
            self.inventory.setRowCount(len(inventory["rows"]))
            for row_index, row in enumerate(inventory["rows"]):
                for column, value in enumerate((
                    row["name"], row["ifc"], row["kind"],
                    str(row["faces"]), row["note"],
                )):
                    item = QTableWidgetItem(value)
                    if column == 3:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.inventory.setItem(row_index, column, item)
            self.inventory.resizeRowsToContents()
        except Exception as exc:
            self.status.setText(tr("Modelgegevens konden niet worden gelezen: {error}",
                                   error=str(exc)))
            self.model_summary.clear()
            self.inventory.setRowCount(0)


def setup(app) -> None:
    panel = BrandoverslagPanel(app)
    dock = app.add_panel(tr("NEN 6068 Brandoverslag"), panel)
    app.add_menu_action(
        tr("NEN 6068 Brandoverslag"), lambda: app.show_panel(dock),
        tip=tr("Open the NEN 6068 fire-spread extension panel."),
    )
    app.on_document_changed(panel.refresh)
