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
    QTableWidgetItem, QVBoxLayout, QWidget, QDoubleSpinBox,
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
    """Fan-triangulate a planar polygon, omitting degenerate triangles."""
    points = [_point_tuple(p) if hasattr(p, "x") else tuple(p) for p in points]
    if len(points) < 3:
        return []
    triangles = []
    for index in range(1, len(points) - 1):
        a, b, c = points[0], points[index], points[index + 1]
        ab, ac = _sub(b, a), _sub(c, a)
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        if _dot(cross, cross) > 1e-20:
            triangles.append((a, b, c))
    return triangles


def _triangulate_face(face, matrix=None):
    """Triangulate a face, preserving concave boundaries and inner holes."""
    from core.triangulate import triangulate

    outer = list(getattr(face, "vertices", ()))
    holes = list(getattr(face, "holes", ()))
    if matrix is not None:
        outer = [matrix.map(point) for point in outer]
        holes = [[matrix.map(point) for point in loop] for loop in holes]
    return [
        tuple(_point_tuple(point) for point in triangle)
        for triangle in triangulate(outer, holes)
    ]


def _world_mesh_triangles(group):
    from core.group import iter_placements

    triangles = []
    for placed, matrix in iter_placements(group):
        for face in getattr(placed.mesh, "faces", ()):
            triangles.extend(_triangulate_face(face, matrix))
    return triangles


def _opening_to_building_distance(opening, building, building_triangles=None):
    """Minimum surface distance from an opening polygon to a building mesh."""
    opening_triangles = _triangulate_points(opening.get("vertices", ()))
    if building_triangles is None:
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
                          max_distance=15.0, building_triangles_cache=None):
    """Find every other top-level group within max_distance of one opening.

    Distances are between the opening polygon and the actual placed building
    surfaces, including nested group/component transforms. A caller analysing
    several openings can share a per-building triangle cache.
    """
    matches = []
    for building in top_level_buildings(scene, source_building_uid):
        triangles = None
        if building_triangles_cache is not None:
            if building.uid not in building_triangles_cache:
                building_triangles_cache[building.uid] = _world_mesh_triangles(building)
            triangles = building_triangles_cache[building.uid]
        distance = _opening_to_building_distance(opening, building, triangles)
        if distance is not None and distance <= max_distance + 1e-9:
            matches.append({
                "uid": building.uid,
                "name": getattr(building, "name", "") or tr("Naamloos gebouw"),
                "distance": distance,
                "openings": _opening_faces_in_group_tree(building),
            })
    return sorted(matches, key=lambda item: item["distance"])


DEFAULT_WALL_THICKNESS = 0.35
WALL_NORMAL_Z_TOLERANCE = 0.1
WALL_BASE_TOLERANCE = 0.01
WALL_VERTEX_TOLERANCE = 1e-4

FLOOR_GROUP_NAME = "floor"
FLOOR_HEIGHT_TOLERANCE = 0.01


def _horizontal_face_height(face, matrix=None, tolerance=FLOOR_HEIGHT_TOLERANCE):
    """Return the face's world Z height when it is horizontal, else None."""
    points = list(getattr(face, "vertices", ()))
    if len(points) < 3:
        return None
    if matrix is not None:
        points = [matrix.map(point) for point in points]
    heights = [float(point.z()) for point in points]
    if max(heights) - min(heights) > tolerance:
        return None
    return sum(heights) / len(heights)


def _face_area(face, matrix=None):
    """Area of a planar face, including its holes, in world square metres."""
    triangles = _triangulate_face(face, matrix)
    area = 0.0
    for a, b, c in triangles:
        ab, ac = _sub(b, a), _sub(c, a)
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        area += 0.5 * (_dot(cross, cross) ** 0.5)
    return area


def analyse_building_floors(building, ground_height=0.0,
                            height_tolerance=FLOOR_HEIGHT_TOLERANCE):
    """Detect the ground-floor face and the first-floor group in a building.

    The ground floor may be directly in the building mesh or in any nested
    group. The first floor is taken only from a group named 'floor'. Geometry
    is measured in world coordinates, including nested placements and holes.
    """
    from core.group import iter_placements

    ground_faces = []
    for placed, matrix in iter_placements(building):
        for index, face in enumerate(getattr(placed.mesh, "faces", ())):
            height = _horizontal_face_height(face, matrix, height_tolerance)
            if height is not None and abs(height - ground_height) <= height_tolerance:
                ground_faces.append({
                    "group": placed, "face_index": index,
                    "height": height, "area": _face_area(face, matrix),
                })

    floor_groups = [
        group for group in _walk_groups([building])
        if (getattr(group, "name", "") or "").strip().casefold()
        == FLOOR_GROUP_NAME
    ]
    first_floor_faces = []
    seen = set()
    for floor_group in floor_groups:
        for placed, matrix in iter_placements(floor_group):
            for index, face in enumerate(getattr(placed.mesh, "faces", ())):
                height = _horizontal_face_height(face, matrix, height_tolerance)
                if height is None or height <= ground_height + height_tolerance:
                    continue
                identity = (id(placed), index)
                if identity in seen:
                    continue
                seen.add(identity)
                first_floor_faces.append({
                    "group": placed, "face_index": index,
                    "height": height, "area": _face_area(face, matrix),
                })

    ground_area = sum(item["area"] for item in ground_faces)
    first_floor_area = sum(item["area"] for item in first_floor_faces)
    heights = [item["height"] for item in first_floor_faces]
    return {
        "ground_floor_faces": ground_faces,
        "ground_floor_face_count": len(ground_faces),
        "ground_floor_area": ground_area,
        "ground_floor_valid": len(ground_faces) == 1,
        "first_floor_faces": first_floor_faces,
        "first_floor_face_count": len(first_floor_faces),
        "first_floor_area": first_floor_area,
        "first_floor_heights": sorted(set(round(value, 4) for value in heights)),
        "first_floor_group_count": len(floor_groups),
    }


def _face_world_normal(face, matrix=None):
    """Return a unit normal from the face's ordered boundary in world space."""
    points = list(getattr(face, "vertices", ()))
    if len(points) < 3:
        return None
    if matrix is not None:
        points = [matrix.map(point) for point in points]
    origin = _point_tuple(points[0])
    normal = None
    for index in range(1, len(points) - 1):
        first = _sub(_point_tuple(points[index]), origin)
        second = _sub(_point_tuple(points[index + 1]), origin)
        cross = (
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        )
        length = _dot(cross, cross) ** 0.5
        if length > 1e-10:
            normal = tuple(value / length for value in cross)
            break
    return normal


def analyse_building_roof(building, upward_tolerance=1e-6):
    """Find outward-facing roof planes by their upward world-space normal.

    Roof faces are individual planes, not closed solids. Their front side must
    point outward and have a positive world Z normal component. Vertical wall
    faces (Z ~= 0) and downward-facing planes are excluded.
    """
    from core.group import iter_placements

    roof_faces = []
    for placed, matrix in iter_placements(building):
        for index, face in enumerate(getattr(placed.mesh, "faces", ())):
            normal = _face_world_normal(face, matrix)
            if normal is None or normal[2] <= upward_tolerance:
                continue
            roof_faces.append({
                "group": placed,
                "face_index": index,
                "normal": normal,
                "area": _face_area(face, matrix),
                "vertices": [
                    matrix.map(point) if matrix is not None else type(point)(point)
                    for point in face.vertices
                ],
            })
    return {
        "roof_faces": roof_faces,
        "roof_face_count": len(roof_faces),
        "roof_area": sum(item["area"] for item in roof_faces),
    }


def analyse_building_walls(building, normal_z_tolerance=WALL_NORMAL_Z_TOLERANCE):
    """Detect outward-facing, predominantly vertical wall planes in world space.

    The face winding is expected to point outwards. A small vertical component
    is allowed for slightly leaning walls; upward roof faces are handled by the
    separate roof detector.
    """
    from core.group import iter_placements

    wall_faces = []
    for placed, matrix in iter_placements(building):
        for index, face in enumerate(getattr(placed.mesh, "faces", ())):
            normal = _face_world_normal(face, matrix)
            if normal is None or abs(normal[2]) > normal_z_tolerance:
                continue
            wall_faces.append({
                "group": placed,
                "face_index": index,
                "normal": normal,
                "area": _face_area(face, matrix),
                "vertices": [
                    matrix.map(point) if matrix is not None else type(point)(point)
                    for point in face.vertices
                ],
            })
    return {
        "wall_faces": wall_faces,
        "wall_face_count": len(wall_faces),
        "wall_area": sum(item["area"] for item in wall_faces),
    }


def _wall_base_segments(wall_faces, height_tolerance=WALL_BASE_TOLERANCE):
    """Extract the lowest horizontal boundary edges from each wall face."""
    segments = []
    for wall in wall_faces:
        vertices = [tuple(point) if not hasattr(point, "x") else _point_tuple(point)
                    for point in wall.get("vertices", ())]
        if len(vertices) < 3:
            continue
        lowest = min(point[2] for point in vertices)
        loop = vertices
        for index, first in enumerate(loop):
            second = loop[(index + 1) % len(loop)]
            if (abs(first[2] - lowest) <= height_tolerance
                    and abs(second[2] - lowest) <= height_tolerance
                    and _distance_squared(first, second) > 1e-12):
                segments.append((first, second))
    return segments


def reconstruct_building_footprint(building, vertex_tolerance=WALL_VERTEX_TOLERANCE,
                                   height_tolerance=WALL_BASE_TOLERANCE):
    """Reconstruct closed footprint loops from the lowest edges of wall faces.

    Endpoints are clustered within vertex_tolerance. Each resulting vertex
    must have degree two; open, branched, or duplicate-edge contours are
    reported rather than guessed. Multiple closed loops are supported.
    """
    walls = analyse_building_walls(building)
    segments = _wall_base_segments(walls["wall_faces"], height_tolerance)
    if not segments:
        return {
            "contours": [], "segments": [], "valid": False,
            "errors": ["Geen horizontale onderranden van wandvlakken gevonden."],
            "wall_face_count": walls["wall_face_count"],
        }

    nodes = {}
    node_points = []
    edges = set()

    def node_id(point):
        key = tuple(round(value / vertex_tolerance) for value in point)
        if key not in nodes:
            nodes[key] = len(node_points)
            node_points.append(tuple(point))
        return nodes[key]

    duplicate_count = 0
    for first, second in segments:
        a, b = node_id(first), node_id(second)
        if a == b:
            continue
        edge = (min(a, b), max(a, b))
        if edge in edges:
            duplicate_count += 1
            continue
        edges.add(edge)

    adjacency = [[] for _ in node_points]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)

    errors = []
    irregular = [
        (index, len(neighbours)) for index, neighbours in enumerate(adjacency)
        if len(neighbours) != 2
    ]
    if irregular:
        errors.append(
            "Buitencontour is niet overal eenduidig gesloten "
            f"({len(irregular)} hoekpunt(en) met een aansluitgraad anders dan 2)."
        )
    if duplicate_count:
        errors.append(f"{duplicate_count} dubbele wandrand(en) aangetroffen.")

    contours = []
    visited_edges = set()
    if not errors:
        for start in range(len(node_points)):
            for neighbour in adjacency[start]:
                first_edge = (min(start, neighbour), max(start, neighbour))
                if first_edge in visited_edges:
                    continue
                loop = [start]
                previous, current = start, neighbour
                visited_edges.add(first_edge)
                while current != start:
                    loop.append(current)
                    candidates = [candidate for candidate in adjacency[current]
                                  if candidate != previous]
                    if len(candidates) != 1:
                        errors.append("Buitencontour kon niet eenduidig worden gevolgd.")
                        break
                    following = candidates[0]
                    edge = (min(current, following), max(current, following))
                    if edge in visited_edges and following != start:
                        errors.append("Wandranden bevatten een onverwachte kringverbinding.")
                        break
                    visited_edges.add(edge)
                    previous, current = current, following
                if errors:
                    break
                contours.append([node_points[index] for index in loop])
            if errors:
                break

    return {
        "contours": contours,
        "segments": segments,
        "valid": bool(contours) and not errors,
        "errors": errors,
        "wall_face_count": walls["wall_face_count"],
        "vertex_count": len(node_points),
        "edge_count": len(edges),
    }


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
    choices = []
    for group in getattr(scene, "groups", None) or ():
        uid = getattr(group, "uid", None)
        if not uid:
            continue
        ifc_class = ((getattr(group, "ifc", None) or {}).get("class") or "")
        label = getattr(group, "name", "") or tr("Naamloos gebouw")
        if ifc_class:
            label += f" [{ifc_class}]"
        choices.append((f"{label} · {uid[:6]}", uid))
    return choices


def analyse_source_building(scene, source_building_uid, max_distance=15.0):
    """Return every marked source opening and its nearby top-level buildings."""
    openings = find_openings_in_building(scene, source_building_uid)
    # Neighbour geometry is static during this analysis. Triangulate each
    # building once, then reuse it for every source opening.
    building_triangles_cache = {}
    return [{
        "opening": opening,
        "nearby_buildings": find_nearby_buildings(
            scene, source_building_uid, opening,
            max_distance=max_distance,
            building_triangles_cache=building_triangles_cache,
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
        self.floor_summary = QLabel()
        self.floor_summary.setWordWrap(True)
        layout.addWidget(self.floor_summary)

        selection_form = QFormLayout()
        self.source_building = QComboBox()
        self.source_building.addItem(tr("— selecteer brongebouw —"), None)
        self.source_building.currentIndexChanged.connect(self._save_selection)
        selection_form.addRow(tr("Brongebouw / brandcompartiment"), self.source_building)
        self.wall_thickness = QDoubleSpinBox()
        self.wall_thickness.setDecimals(3)
        self.wall_thickness.setRange(0.05, 1.0)
        self.wall_thickness.setSingleStep(0.01)
        self.wall_thickness.setSuffix(" m")
        self.wall_thickness.setValue(DEFAULT_WALL_THICKNESS)
        self.wall_thickness.valueChanged.connect(self._save_wall_thickness)
        selection_form.addRow(tr("Uniforme wanddikte"), self.wall_thickness)
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

        source_uid = selected.get("source_building")
        wall_thicknesses = selected.get("wall_thicknesses", {})
        self.wall_thickness.blockSignals(True)
        self.wall_thickness.setEnabled(bool(source_uid))
        self.wall_thickness.setValue(
            float(wall_thicknesses.get(source_uid, DEFAULT_WALL_THICKNESS))
            if source_uid else DEFAULT_WALL_THICKNESS
        )
        self.wall_thickness.blockSignals(False)

        report = validate_selection(self.app.scene, selected)
        source = report["resolved"].get("source_building")
        if source is None:
            self.floor_summary.setText(tr("Selecteer een brongebouw om de vloergeometrie te controleren."))
        else:
            floors = analyse_building_floors(source)
            roof = analyse_building_roof(source)
            walls = analyse_building_walls(source)
            footprint = reconstruct_building_footprint(source)
            ground_status = (
                tr("begane grond: {area:.2f} m²", area=floors["ground_floor_area"])
                if floors["ground_floor_valid"] else
                tr("begane grond: {count} horizontale vlakken op z=0 m (verwacht 1)",
                   count=floors["ground_floor_face_count"])
            )
            first_status = (
                tr("eerste verdieping: {area:.2f} m² op z={heights} m",
                   area=floors["first_floor_area"],
                   heights=", ".join(str(value) for value in floors["first_floor_heights"]))
                if floors["first_floor_face_count"] else
                tr("eerste verdieping: geen horizontale vlakken gevonden in groep 'floor'")
            )
            roof_status = tr(
                "dak: {count} naar boven gerichte vlakken · {area:.2f} m²",
                count=roof["roof_face_count"], area=roof["roof_area"])
            wall_status = tr(
                "buitenwanden: {count} vlakken · {area:.2f} m²",
                count=walls["wall_face_count"], area=walls["wall_area"])
            footprint_status = (
                tr("buitencontour: {count} gesloten contour(en) herkend",
                   count=len(footprint["contours"]))
                if footprint["valid"] else
                tr("buitencontour: niet gesloten — {reason}",
                   reason="; ".join(footprint["errors"]))
            )
            self.floor_summary.setText(
                ground_status + " · " + first_status + " · " +
                roof_status + " · " + wall_status + " · " + footprint_status)
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

    def _save_wall_thickness(self, value):
        state = self.app.document_data({}) or {}
        selection = state.get("selection", {})
        source_uid = selection.get("source_building")
        if not source_uid:
            return
        wall_thicknesses = selection.setdefault("wall_thicknesses", {})
        wall_thicknesses[source_uid] = float(value)
        selection["wall_thicknesses"] = wall_thicknesses
        state["selection"] = selection
        self.app.set_document_data(state)

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
            self.floor_summary.clear()
            self.inventory.setRowCount(0)


def setup(app) -> None:
    panel = BrandoverslagPanel(app)
    dock = app.add_panel(tr("NEN 6068 Brandoverslag"), panel)
    app.add_menu_action(
        tr("NEN 6068 Brandoverslag"), lambda: app.show_panel(dock),
        tip=tr("Open the NEN 6068 fire-spread extension panel."),
    )
    app.on_document_changed(panel.refresh)
