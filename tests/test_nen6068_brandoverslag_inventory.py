# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only scene inventory used by the NEN 6068 extension."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from plugins.nen6068_brandoverslag import inspect_scene


def _triangle():
    mesh = Mesh()
    mesh.add_face([
        QVector3D(0, 0, 0),
        QVector3D(1, 0, 0),
        QVector3D(0, 0, 1),
    ])
    return mesh


def test_inventory_finds_nested_bim_groups_and_windowizer_metadata():
    scene = Scene()
    building = Group(_triangle(), "Building")
    building.ifc = {"class": "IfcBuilding", "name": "Building"}

    window = Group(name="Window-001")
    window.ifc = {"class": "IfcWindow", "name": "Window-001"}
    window.ext = {
        "windowizer": {
            "outline": [
                [0.0, 0.0, 0.0],
                [1.2, 0.0, 0.0],
                [1.2, 0.0, 1.0],
                [0.0, 0.0, 1.0],
            ],
            "pose": [],
        }
    }
    window.adopt([Group(_triangle(), "Frame")])
    building.adopt([window])
    scene.groups.append(building)

    result = inspect_scene(scene)
    by_name = {row["name"]: row for row in result["rows"]}

    assert by_name["Building"]["ifc"] == "IfcBuilding"
    assert by_name["Building"]["faces"] == 2
    assert by_name["Window-001"]["ifc"] == "IfcWindow"
    assert by_name["Window-001"]["note"] == "Windowizer-contour: 1.200 × 1.000 m"
    assert result["tagged_groups"] == 2
    assert result["windowizer_count"] == 1


def test_inventory_reports_loose_bim_faces_without_mutating_scene():
    scene = Scene()
    source_face = _triangle().faces[0]
    face = scene.loose_mesh.add_face(source_face.vertices)
    face.attrs["ifc"] = {"id": 7, "class": "IfcWall", "name": "Gevel"}

    before = scene.version
    result = inspect_scene(scene)

    assert result["loose_objects"] == 1
    row = next(row for row in result["rows"] if row["kind"] == "Losse vlakken")
    assert row["name"] == "Gevel"
    assert row["ifc"] == "IfcWall"
    assert row["faces"] == 1
    assert scene.version == before


def test_outline_size_rejects_invalid_or_degenerate_records():
    from plugins.nen6068_brandoverslag import _outline_size

    assert _outline_size([[0, 0, 0], [1, 0, 0]]) is None
    assert _outline_size([["bad", 0, 0], [1, 0, 1], [0, 0, 1]]) is None



def test_group_world_faces_applies_nested_placements_and_preserves_holes():
    from PySide6.QtGui import QMatrix4x4, QVector3D
    from core.group import Group
    from plugins.nen6068_brandoverslag import group_world_faces

    mesh = _triangle()
    group = Group(mesh, "Facade")
    placement = QMatrix4x4()
    placement.translate(QVector3D(4.0, 2.0, 1.0))
    group.xform = placement

    faces = group_world_faces(group)
    assert len(faces) == 1
    assert [tuple(round(v, 3) for v in
                  (faces[0]["vertices"][0].x(),
                   faces[0]["vertices"][0].y(),
                   faces[0]["vertices"][0].z()))] == [(4.0, 2.0, 1.0)]
    assert faces[0]["normal"] is not None
    assert abs(faces[0]["area"] - 0.5) < 1e-6
    assert faces[0]["holes"] == []


def test_windowizer_world_outline_uses_composed_child_and_parent_pose():
    from PySide6.QtGui import QMatrix4x4, QVector3D
    from core.group import Group
    from plugins.nen6068_brandoverslag import windowizer_world_outline

    window = Group(name="Window-001")
    part = Group(name="Frame")
    child_pose = QMatrix4x4()
    child_pose.translate(QVector3D(2.0, 3.0, 4.0))
    part.xform = child_pose
    window.adopt([part])

    parent_move = QMatrix4x4()
    parent_move.translate(QVector3D(10.0, 0.0, 0.0))
    window.xform = parent_move

    data = {"outline": [
        [0.0, 0.0, 0.0], [1.2, 0.0, 0.0],
        [1.2, 0.0, 1.0], [0.0, 0.0, 1.0],
    ]}
    outline = windowizer_world_outline(window, data)
    assert outline is not None
    assert (outline[0] - QVector3D(12.0, 3.0, 4.0)).length() < 1e-6
    assert (outline[2] - QVector3D(13.2, 3.0, 5.0)).length() < 1e-6



def test_opening_dimensions_are_independent_of_world_orientation():
    from PySide6.QtGui import QMatrix4x4, QVector3D
    from plugins.nen6068_brandoverslag import _outline_dimensions

    local = [
        QVector3D(0.0, 0.0, 0.0), QVector3D(1.2, 0.0, 0.0),
        QVector3D(1.2, 0.0, 1.0), QVector3D(0.0, 0.0, 1.0),
    ]
    pose = QMatrix4x4()
    pose.rotate(90.0, QVector3D(0.0, 0.0, 1.0))
    pose.translate(QVector3D(2.0, 3.0, 0.0))
    world = [pose.map(point) for point in local]

    width, height = _outline_dimensions(world)
    assert abs(width - 1.2) < 1e-5
    assert abs(height - 1.0) < 1e-5



def test_group_role_choices_use_stable_uids_and_resolve_nested_groups():
    from plugins.nen6068_brandoverslag import (
        find_group_by_uid,
        group_selection_choices,
    )

    building = Group(name="Brongebouw")
    facade = Group(name="Brongevel")
    facade.ifc = {"class": "IfcWall", "name": "Brongevel"}
    building.adopt([facade])

    choices = group_selection_choices([building])
    choice_ids = {uid for _label, uid in choices}

    assert building.uid in choice_ids
    assert facade.uid in choice_ids
    assert any("IfcWall" in label for label, uid in choices
               if uid == facade.uid)
    assert find_group_by_uid([building], facade.uid) is facade
    assert find_group_by_uid([building], "not-a-real-uid") is None



def test_opening_selection_choices_only_include_windowizer_groups():
    from plugins.nen6068_brandoverslag import opening_selection_choices

    building = Group(name="Building")
    opening = Group(name="Window-01")
    opening.ext = {"windowizer": {"outline": [
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 1.0]
    ]}}
    ordinary_part = Group(name="Frame")
    building.adopt([opening, ordinary_part])

    choices = opening_selection_choices([building])

    assert [uid for _label, uid in choices] == [opening.uid]
    assert "Window-01" in choices[0][0]


def test_selection_validation_accepts_explicit_roles_and_valid_openings():
    from plugins.nen6068_brandoverslag import validate_selection

    scene = Scene()
    source = Group(name="Source")
    source_facade = Group(name="Source facade")
    compartment = Group(name="Compartment")
    source.adopt([source_facade, compartment])
    receiving = Group(name="Receiving")
    receiving_facade = Group(name="Receiving facade")
    receiving.adopt([receiving_facade])

    source_window = Group(name="Source window")
    receiving_window = Group(name="Receiving window")
    outline = [[0.0, 0.0, 0.0], [1.2, 0.0, 0.0],
               [1.2, 0.0, 1.0], [0.0, 0.0, 1.0]]
    source_window.ext = {"windowizer": {"outline": outline}}
    receiving_window.ext = {"windowizer": {"outline": outline}}
    scene.groups.extend([source, receiving, source_window, receiving_window])

    selection = {
        "source_building": source.uid,
        "receiving_building": receiving.uid,
        "source_facade": source_facade.uid,
        "receiving_facade": receiving_facade.uid,
        "fire_compartment": compartment.uid,
        "source_openings": [source_window.uid],
        "receiving_openings": [receiving_window.uid],
    }
    report = validate_selection(scene, selection)

    assert report["valid"] is True
    assert report["errors"] == []
    assert any("geometrisch bewezen" in warning
               for warning in report["warnings"])


def test_selection_validation_rejects_missing_roles_and_shared_openings():
    from plugins.nen6068_brandoverslag import validate_selection

    scene = Scene()
    building = Group(name="Building")
    facade = Group(name="Facade")
    compartment = Group(name="Compartment")
    building.adopt([facade, compartment])
    window = Group(name="Window")
    window.ext = {"windowizer": {"outline": [
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 1.0]
    ]}}
    scene.groups.extend([building, window])
    selection = {
        "source_building": building.uid,
        "receiving_building": building.uid,
        "source_facade": facade.uid,
        "receiving_facade": "missing-facade",
        "fire_compartment": compartment.uid,
        "source_openings": [window.uid],
        "receiving_openings": [window.uid],
    }

    report = validate_selection(scene, selection)
    assert report["valid"] is False
    assert any("hetzelfde object" in error for error in report["errors"])
    assert any("bestaat niet" in error for error in report["errors"])
    assert any("zowel aan de bron" in error for error in report["errors"])


def test_loose_ifc_wall_facades_have_stable_references_and_resolve():
    from plugins.nen6068_brandoverslag import (
        facade_selection_choices,
        resolve_facade_selection,
    )

    scene = Scene()
    source = scene.loose_mesh.add_face(_triangle().faces[0].vertices)
    source.attrs["ifc"] = {"id": 41, "class": "IfcWall", "name": "Westgevel"}
    # A second face belonging to the same IFC object must remain one choice.
    second = scene.loose_mesh.add_face(_triangle().faces[0].vertices)
    second.attrs["ifc"] = {"id": 41, "class": "IfcWall", "name": "Westgevel"}

    choices = facade_selection_choices(scene)
    assert len(choices) == 1
    assert choices[0][1] == "faces:41"
    resolved = resolve_facade_selection(scene, "faces:41")
    assert resolved is not None
    assert resolved["kind"] == "faces"
    assert len(resolved["faces"]) == 2
    assert resolve_facade_selection(scene, "faces:999") is None


def test_windowizer_opening_host_ifc_id_is_checked_against_selected_loose_facade():
    from plugins.nen6068_brandoverslag import validate_selection

    scene = Scene()
    source = Group(name="Source")
    compartment = Group(name="Compartment")
    source.adopt([compartment])
    receiving = Group(name="Receiving")
    scene.groups.extend([source, receiving])

    wall = scene.loose_mesh.add_face(_triangle().faces[0].vertices)
    wall.attrs["ifc"] = {"id": 41, "class": "IfcWall", "name": "Westgevel"}
    receiving_wall = scene.loose_mesh.add_face(_triangle().faces[0].vertices)
    receiving_wall.attrs["ifc"] = {"id": 42, "class": "IfcWall", "name": "Oostgevel"}

    source_window = Group(name="Source window")
    receiving_window = Group(name="Receiving window")
    outline = [[0.0, 0.0, 0.0], [1.2, 0.0, 0.0],
               [1.2, 0.0, 1.0], [0.0, 0.0, 1.0]]
    source_window.ext = {"windowizer": {"outline": outline}}
    receiving_window.ext = {"windowizer": {"outline": outline}}
    scene.groups.extend([source_window, receiving_window])
    scene.plugin_data["windowizer"] = {"openings": {
        source_window.uid: {"host": {"attrs": {
            "ifc": {"id": 41, "class": "IfcWall", "name": "Westgevel"}
        }}},
        receiving_window.uid: {"host": {"attrs": {
            "ifc": {"id": 42, "class": "IfcWall", "name": "Oostgevel"}
        }}},
    }}

    selection = {
        "source_building": source.uid,
        "receiving_building": receiving.uid,
        "source_facade": "faces:41",
        "receiving_facade": "faces:42",
        "fire_compartment": compartment.uid,
        "source_openings": [source_window.uid],
        "receiving_openings": [receiving_window.uid],
    }
    report = validate_selection(scene, selection)
    assert report["valid"] is True
    assert not any("komt niet overeen" in error for error in report["errors"])

    selection["source_facade"] = "faces:42"
    report = validate_selection(scene, selection)
    assert report["valid"] is False
    assert any("komt niet overeen" in error for error in report["errors"])
