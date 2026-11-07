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
    find_nearby_buildings,
    building_selection_choices,
    top_level_buildings,
    inspect_scene,
    resolve_opening_reference,
    validate_selection,
    _opening_to_building_distance,
    analyse_building_floors,
    analyse_building_roof,
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



def _plane_mesh(z):
    mesh = Mesh()
    mesh.add_face([
        QVector3D(0, 0, z), QVector3D(1.2, 0, z),
        QVector3D(1.2, 1.0, z), QVector3D(0, 1.0, z),
    ])
    return mesh


def test_nearby_buildings_are_found_per_opening_with_15m_cutoff():
    scene = Scene()
    source = Group(name="Brongebouw")
    opening = Group(_plane_mesh(0), "Bronopening")
    opening.mesh.faces[0].attrs["mat"] = OPENING_MATERIAL
    source.adopt([opening])

    near = Group(_plane_mesh(14.9), "Gebouw binnen 15m")
    near.mesh.faces[0].attrs["mat"] = OPENING_MATERIAL
    boundary = Group(_plane_mesh(15.0), "Gebouw precies op 15m")
    far = Group(_plane_mesh(15.1), "Gebouw buiten 15m")
    scene.groups.extend([source, near, boundary, far])

    source_opening = find_openings_in_building(scene, source.uid)[0]
    matches = find_nearby_buildings(scene, source.uid, source_opening)

    assert [item["uid"] for item in matches] == [near.uid, boundary.uid]
    assert abs(matches[0]["distance"] - 14.9) < 1e-5
    assert len(matches[0]["openings"]) == 1
    assert abs(matches[1]["distance"] - 15.0) < 1e-5


def test_nearby_building_distance_includes_nested_group_transforms():
    scene = Scene()
    source = Group(name="Brongebouw")
    opening = Group(_plane_mesh(0), "Bronopening")
    opening.mesh.faces[0].attrs["mat"] = OPENING_MATERIAL
    source.adopt([opening])

    neighbour = Group(name="Ontvangend gebouw")
    nested = Group(_plane_mesh(0), "Geneste gevel")
    from PySide6.QtGui import QMatrix4x4
    placement = QMatrix4x4()
    placement.translate(QVector3D(0, 0, 12))
    nested.xform = placement
    neighbour.adopt([nested])
    scene.groups.extend([source, neighbour])

    source_opening = find_openings_in_building(scene, source.uid)[0]
    matches = find_nearby_buildings(scene, source.uid, source_opening)

    assert len(matches) == 1
    assert matches[0]["uid"] == neighbour.uid
    assert abs(matches[0]["distance"] - 12.0) < 1e-5


def test_only_top_level_groups_are_treated_as_buildings():
    scene = Scene()
    source = Group(name="Brongebouw")
    nested = Group(name="Onderdeel van brongebouw")
    source.adopt([nested])
    neighbour = Group(name="Ander gebouw")
    scene.groups.extend([source, neighbour])

    assert [group.uid for group in top_level_buildings(scene, source.uid)] == [
        neighbour.uid
    ]



def test_building_choices_only_include_top_level_groups():
    scene = Scene()
    building = Group(name="Gebouw")
    nested = Group(name="Onderdeel")
    building.adopt([nested])
    scene.groups.append(building)

    choices = building_selection_choices(scene)

    assert [uid for _label, uid in choices] == [building.uid]



def _opening_polygon(x0, y0, x1, y1, z=0):
    return {
        "vertices": [
            QVector3D(x0, y0, z), QVector3D(x1, y0, z),
            QVector3D(x1, y1, z), QVector3D(x0, y1, z),
        ]
    }


def test_building_distance_respects_concave_face_boundary():
    mesh = Mesh()
    mesh.add_face([
        QVector3D(0, 0, 0), QVector3D(3, 0, 0),
        QVector3D(3, 1, 0), QVector3D(1, 1, 0),
        QVector3D(1, 3, 0), QVector3D(0, 3, 0),
    ])
    building = Group(mesh, "Concave gebouw")

    # This opening lies in the missing upper-right corner of the L-shaped face.
    distance = _opening_to_building_distance(
        _opening_polygon(1.5, 1.5, 2.5, 2.5), building
    )

    assert abs(distance - 0.5) < 1e-5


def test_building_distance_respects_hole_in_face():
    mesh = Mesh()
    mesh.add_face(
        [
            QVector3D(0, 0, 0), QVector3D(4, 0, 0),
            QVector3D(4, 4, 0), QVector3D(0, 4, 0),
        ],
        hole_loops=[[
            QVector3D(1, 1, 0), QVector3D(3, 1, 0),
            QVector3D(3, 3, 0), QVector3D(1, 3, 0),
        ]],
    )
    building = Group(mesh, "Gebouw met vide")

    # The opening lies entirely in the hole; it must not be treated as face area.
    distance = _opening_to_building_distance(
        _opening_polygon(1.5, 1.5, 2.5, 2.5), building
    )

    assert abs(distance - 0.5) < 1e-5


def test_building_floor_detection_finds_ground_face_in_building_mesh_and_floor_group():
    building = Group(name="Woning")
    ground = _plane_mesh(0.0)
    building.mesh = ground
    first_floor = Group(_plane_mesh(2.0), "floor")
    building.adopt([first_floor])

    result = analyse_building_floors(building)

    assert result["ground_floor_valid"]
    assert result["ground_floor_face_count"] == 1
    assert abs(result["ground_floor_area"] - 1.2) < 1e-6
    assert result["first_floor_face_count"] == 1
    assert abs(result["first_floor_area"] - 1.2) < 1e-6
    assert result["first_floor_heights"] == [2.0]


def test_building_floor_detection_finds_ground_face_in_nested_group():
    building = Group(name="Woning")
    ground_group = Group(_plane_mesh(0.0), "Begane grond")
    building.adopt([ground_group])

    result = analyse_building_floors(building)

    assert result["ground_floor_valid"]
    assert result["ground_floor_face_count"] == 1
    assert abs(result["ground_floor_area"] - 1.2) < 1e-6


def _oriented_plane_mesh(points):
    mesh = Mesh()
    mesh.add_face([QVector3D(*point) for point in points])
    return mesh


def test_roof_detection_includes_horizontal_and_sloping_upward_faces():
    building = Group(name="Woning")
    roof_horizontal = Group(_oriented_plane_mesh([
        (0, 0, 3), (2, 0, 3), (2, 2, 3), (0, 2, 3),
    ]), "Plat dak")
    roof_sloped = Group(_oriented_plane_mesh([
        (3, 0, 2), (5, 0, 3), (5, 2, 3), (3, 2, 2),
    ]), "Hellend dak")
    wall = Group(_oriented_plane_mesh([
        (6, 0, 0), (6, 2, 0), (6, 2, 3), (6, 0, 3),
    ]), "Gevel")
    downward = Group(_oriented_plane_mesh([
        (8, 0, 3), (8, 2, 3), (10, 2, 3), (10, 0, 3),
    ]), "Onderzijde")
    building.adopt([roof_horizontal, roof_sloped, wall, downward])

    result = analyse_building_roof(building)

    assert result["roof_face_count"] == 2
    assert {item["group"].name for item in result["roof_faces"]} == {
        "Plat dak", "Hellend dak"
    }
    assert all(item["normal"][2] > 0 for item in result["roof_faces"])


def test_roof_detection_uses_world_space_orientation_for_nested_faces():
    building = Group(name="Woning")
    roof = Group(_oriented_plane_mesh([
        (0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0),
    ]), "Dakvlak")
    transform = QMatrix4x4()
    transform.rotate(30, QVector3D(1, 0, 0))
    roof.xform = transform
    building.adopt([roof])

    result = analyse_building_roof(building)

    assert result["roof_face_count"] == 1
    assert result["roof_faces"][0]["normal"][2] > 0


def test_building_floor_detection_reports_ambiguous_ground_faces():
    building = Group(name="Woning")
    building.mesh = _plane_mesh(0.0)
    extra_ground = Group(_plane_mesh(0.0), "Extra vlak")
    building.adopt([extra_ground])

    result = analyse_building_floors(building)

    assert not result["ground_floor_valid"]
    assert result["ground_floor_face_count"] == 2
