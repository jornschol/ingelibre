# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for material-based opening discovery in the NEN 6068 extension."""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from plugins.nen6068_brandoverslag import (
    OPENING_MATERIAL,
    find_openings_in_building,
    inspect_scene,
    resolve_opening_reference,
    validate_selection,
)


def _face(material=OPENING_MATERIAL):
    mesh = Mesh()
    face = mesh.add_face([
        QVector3D(0, 0, 0), QVector3D(1.2, 0, 0),
        QVector3D(1.2, 0, 1.0), QVector3D(0, 0, 1.0),
    ])
    if material is not None:
        face.attrs["mat"] = material
    return mesh, face


def test_only_gevelopening_material_is_detected_as_opening():
    scene = Scene()
    building = Group(name="Brongebouw")
    marked_mesh, _ = _face("gevelopening")
    other_mesh, _ = _face("glas")
    marked = Group(marked_mesh, "Raam gemarkeerd")
    other = Group(other_mesh, "Ander glas")
    building.adopt([marked, other])
    scene.groups.append(building)

    openings = find_openings_in_building(scene, building.uid)

    assert len(openings) == 1
    assert openings[0]["name"] == "Raam gemarkeerd"
    assert openings[0]["ref"] == f"{marked.uid}:0"


def test_opening_geometry_uses_nested_mirrored_and_translated_placements():
    scene = Scene()
    building = Group(name="Brongebouw")
    opening_mesh, _ = _face()
    opening = Group(opening_mesh, "Gevelopening")
    mirror_and_move = QMatrix4x4()
    mirror_and_move.translate(QVector3D(5, 2, 0))
    mirror_and_move.scale(-1, 1, 1)
    opening.xform = mirror_and_move
    building.adopt([opening])
    scene.groups.append(building)

    found = find_openings_in_building(scene, building.uid)

    assert len(found) == 1
    vertices = found[0]["vertices"]
    xs = [p.x() for p in vertices]
    ys = [p.y() for p in vertices]
    assert abs(min(xs) - 3.8) < 1e-6
    assert abs(max(xs) - 5.0) < 1e-6
    assert all(abs(y - 2.0) < 1e-6 for y in ys)


def test_opening_reference_resolves_only_while_face_keeps_marking():
    scene = Scene()
    mesh, face = _face()
    opening = Group(mesh, "Raam")
    building = Group(name="Gebouw")
    building.adopt([opening])
    scene.groups.append(building)
    ref = f"{opening.uid}:0"

    resolved = resolve_opening_reference(scene, ref)
    assert resolved is not None
    assert resolved["face"] is face

    face.attrs["mat"] = "glas"
    assert resolve_opening_reference(scene, ref) is None


def test_inventory_counts_marked_openings_in_nested_groups():
    scene = Scene()
    building = Group(name="Gebouw")
    opening_mesh, _ = _face()
    opening = Group(opening_mesh, "Raam")
    building.adopt([opening])
    scene.groups.append(building)

    result = inspect_scene(scene)

    assert result["opening_count"] == 1
    assert any(row["name"] == "Gebouw" and "1 gevelopening" in row["note"]
               for row in result["rows"])
    assert any(row["name"] == "Raam" and "1 gevelopening" in row["note"]
               for row in result["rows"])



def test_source_building_is_used_as_fire_compartment_without_separate_selection():
    scene = Scene()
    source = Group(name="Brongebouw")
    receiving = Group(name="Ontvangend gebouw")
    source_facade = Group(name="Brongevel")
    receiving_facade = Group(name="Ontvangende gevel")
    source.adopt([source_facade])
    receiving.adopt([receiving_facade])
    scene.groups.extend([source, receiving])

    report = validate_selection(scene, {
        "source_building": source.uid,
        "receiving_building": receiving.uid,
        "source_facade": source_facade.uid,
        "receiving_facade": receiving_facade.uid,
        # A stale legacy value must not be required or override the alias.
        "fire_compartment": "deleted-old-compartment",
    })

    assert report["valid"]
    assert report["resolved"]["fire_compartment"] is source
    assert report["resolved"]["source_building"] is source
