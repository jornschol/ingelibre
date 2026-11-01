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


def validate_selection(scene, selection):
    selection = selection if isinstance(selection, dict) else {}
    groups = list(_walk_groups(getattr(scene, "groups", None)))
    by_uid = {g.uid: g for g in groups if getattr(g, "uid", None)}
    errors, warnings, resolved = [], [], {}
    for key, label in (
        ("source_building", "brongebouw"),
        ("receiving_building", "ontvangend gebouw"),
        ("fire_compartment", "brandcompartiment"),
    ):
        group = by_uid.get(selection.get(key))
        if group is None:
            errors.append(f"Geen geldig {label} geselecteerd.")
        else:
            resolved[key] = group

    for key, label in (("source_facade", "brongevel"),
                       ("receiving_facade", "ontvangende gevel")):
        ref = selection.get(key)
        facade = resolve_facade_selection(scene, ref) if ref else None
        if facade is None:
            errors.append(f"Geen geldige {label} geselecteerd.")
        else:
            resolved[key] = facade

    source = selection.get("source_building")
    receiving = selection.get("receiving_building")
    if source and source == receiving:
        errors.append("Brongebouw en ontvangend gebouw zijn hetzelfde object.")

    source_openings = find_openings_in_building(scene, source)
    if not source_openings:
        warnings.append(
            f"Geen vlakken met materiaal '{OPENING_MATERIAL}' gevonden in het brongebouw."
        )

    receiving_refs = selection.get("receiving_openings", []) or []
    if not isinstance(receiving_refs, list):
        errors.append("De selectie van ontvangende gevelopeningen is ongeldig.")
        receiving_refs = []
    if len(receiving_refs) != len(set(receiving_refs)):
        errors.append("Een ontvangende gevelopening is dubbel geselecteerd.")
    for ref in receiving_refs:
        resolved_face = resolve_opening_reference(scene, ref)
        if resolved_face is None:
            errors.append("Een geselecteerde ontvangende gevelopening bestaat niet meer of heeft niet langer het materiaal 'gevelopening'.")
            continue
        if receiving and not any(item["ref"] == ref
                                 for item in find_openings_in_building(scene, receiving)):
            warnings.append("Een geselecteerde ontvangende gevelopening valt niet aantoonbaar binnen het gekozen ontvangende gebouw.")

    if not receiving_refs:
        warnings.append("Selecteer één of meer ontvangende gevelopeningen.")
    warnings.append(
        "De materiaalmarkering identificeert modelvlakken, maar bewijst op zichzelf "
        "nog niet dat elk vlak een volgens NEN 6068 relevante opening is of binnen "
        "het gekozen brandcompartiment/gevelvlak ligt."
    )
    return {
        "errors": errors, "warnings": warnings, "valid": not errors,
        "resolved": resolved, "source_openings": source_openings,
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

        selection_heading = QLabel(tr("Modelonderdelen voor de berekening"))
        selection_heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(selection_heading)
        selection_form = QFormLayout()
        self._selection_combos = {}
        for key, label in (
            ("source_building", tr("Brongebouw")),
            ("receiving_building", tr("Ontvangend gebouw")),
            ("source_facade", tr("Brongevel")),
            ("receiving_facade", tr("Ontvangende gevel")),
            ("fire_compartment", tr("Brandcompartiment")),
        ):
            combo = QComboBox()
            combo.addItem(tr("— niet geselecteerd —"), None)
            combo.currentIndexChanged.connect(self._save_selection)
            self._selection_combos[key] = combo
            selection_form.addRow(label, combo)
        layout.addLayout(selection_form)

        self.source_openings = QListWidget()
        self.source_openings.setMaximumHeight(115)
        self.source_openings.setSelectionMode(QAbstractItemView.NoSelection)
        selection_form.addRow(tr("Automatisch gevonden bronopeningen"), self.source_openings)

        self.receiving_openings = QListWidget()
        self.receiving_openings.setMaximumHeight(145)
        self.receiving_openings.itemChanged.connect(self._save_receiving_selection)
        selection_form.addRow(tr("Te beoordelen ontvangende openingen"), self.receiving_openings)

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
            tr("Ken het materiaal 'gevelopening' toe aan elk rechthoekig vlak "
               "dat als opening moet worden herkend. Bronopeningen worden "
               "automatisch uit het brongebouw verzameld; ontvangende openingen "
               "selecteer je handmatig. Windowizer is niet nodig. Er worden nog "
               "geen NEN 6068-resultaten berekend.")
        )
        self.scope.setWordWrap(True)
        self.scope.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.scope)
        self.refresh()

    def _refresh_selection_choices(self):
        state = self.app.document_data({}) or {}
        selected = state.get("selection", {})
        groups = list(_walk_groups(getattr(self.app.scene, "groups", None)))
        choices = group_selection_choices(groups)
        facade_choices = facade_selection_choices(self.app.scene)
        for key, combo in self._selection_combos.items():
            combo.blockSignals(True)
            current = selected.get(key)
            combo.clear()
            combo.addItem(tr("— niet geselecteerd —"), None)
            role_choices = facade_choices if key in ("source_facade", "receiving_facade") else choices
            for label, uid in role_choices:
                combo.addItem(label, uid)
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

        report = validate_selection(self.app.scene, selected)
        self.source_openings.blockSignals(True)
        self.source_openings.clear()
        for opening in report["source_openings"]:
            item = QListWidgetItem(opening["name"])
            item.setToolTip(opening["ref"])
            self.source_openings.addItem(item)
        self.source_openings.blockSignals(False)

        receiving_building = selected.get("receiving_building")
        receiving_candidates = find_openings_in_building(self.app.scene, receiving_building)
        self.receiving_openings.blockSignals(True)
        self.receiving_openings.clear()
        checked = set(selected.get("receiving_openings", []) or [])
        for opening in receiving_candidates:
            item = QListWidgetItem(opening["name"])
            item.setData(Qt.ItemDataRole.UserRole, opening["ref"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if opening["ref"] in checked
                               else Qt.CheckState.Unchecked)
            self.receiving_openings.addItem(item)
        self.receiving_openings.blockSignals(False)

        chosen = sum(1 for key, combo in self._selection_combos.items()
                     if combo.currentData())
        self.selection_status.setText(
            tr("{chosen} van de {total} rollen gekoppeld · {source} bronopeningen "
               "gevonden · {receiving} ontvangende openingen beschikbaar.",
               chosen=chosen, total=len(self._selection_combos),
               source=len(report["source_openings"]),
               receiving=len(receiving_candidates))
        )
        self._update_validation(selected)

    def _update_validation(self, selection=None):
        selection = selection if selection is not None else (
            self.app.document_data({}) or {}).get("selection", {})
        report = validate_selection(self.app.scene, selection)
        messages = (["Fouten:"] + ["• " + x for x in report["errors"]]
                    if report["errors"] else ["Geen ontbrekende of tegenstrijdige rolkoppelingen."])
        if report["warnings"]:
            messages += ["Aandachtspunten:"] + ["• " + x for x in report["warnings"]]
        self.validation_status.setText("\n".join(messages))

    def _save_selection(self, _index=None):
        state = self.app.document_data({}) or {}
        selection = state.get("selection", {})
        selection.update({key: combo.currentData()
                          for key, combo in self._selection_combos.items()})
        # Drop receiving references no longer present in the chosen building.
        valid = {x["ref"] for x in find_openings_in_building(
            self.app.scene, selection.get("receiving_building"))}
        selection["receiving_openings"] = [
            ref for ref in selection.get("receiving_openings", []) if ref in valid]
        state["selection"] = selection
        self.app.set_document_data(state)
        self._refresh_selection_choices()

    def _save_receiving_selection(self, _item=None):
        state = self.app.document_data({}) or {}
        selection = state.get("selection", {})
        selection["receiving_openings"] = [
            self.receiving_openings.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.receiving_openings.count())
            if self.receiving_openings.item(i).checkState() == Qt.CheckState.Checked
        ]
        state["selection"] = selection
        self.app.set_document_data(state)
        self._update_validation(selection)

    def refresh(self):
        try:
            inventory = inspect_scene(self.app.scene)
            self._refresh_selection_choices()
            self.status.setText(tr("Modelkoppeling actief."))
            self.model_summary.setText(
                tr("Groepen: {groups} · BIM-geclassificeerde groepen: {tagged} · "
                   "Losse vlakken: {faces} · Gemarkeerde gevelopeningen: {openings}",
                   groups=inventory["group_count"], tagged=inventory["tagged_groups"],
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
