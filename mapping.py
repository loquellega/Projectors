"""
Image mapping for projectors: corner pin (keystone), image transform and crop.

The mapping lives inside each projector's spot light node group as a chain of
nodes that sits between the projector raster coordinates and every texture
lookup. Working backwards from an output pixel of the projector:

    raster coord p --(inverse corner pin / homography)--> quad coord q
    q --(inverse transform: offset, rotation, scale, flip)--> content coord c
    c --(crop)--> source image uv

Anything that falls outside the pinned quad or outside the transformed content
is pushed far outside the image so it renders black (Image Texture uses CLIP).

All matrix math is done in Python and written into the nodes as constant
vectors, so the shader stays small: a handful of dot products and divisions.

Coordinates are normalized, origin bottom-left, like Blender UVs:
(0, 0) is the bottom-left of the projector frame, (1, 1) the top-right.
"""
import math

import bpy
from bpy.types import Operator
from mathutils import Matrix, Vector

from .helper import get_projectors, get_projector

PREFIX = 'map_'
OUTSIDE = 10.0  # Pushed this far outside the [0, 1] range when masked.

CORNERS = [
    ('corner_bl', 'Bottom Left', '', 'TRIA_DOWN', 0),
    ('corner_br', 'Bottom Right', '', 'TRIA_DOWN', 1),
    ('corner_tr', 'Top Right', '', 'TRIA_UP', 2),
    ('corner_tl', 'Top Left', '', 'TRIA_UP', 3),
]
CORNER_DEFAULTS = {
    'corner_bl': (0.0, 0.0),
    'corner_br': (1.0, 0.0),
    'corner_tr': (1.0, 1.0),
    'corner_tl': (0.0, 1.0),
}


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------

def square_to_quad(p0, p1, p2, p3):
    """
    Homography that maps the unit square to the quad p0..p3
    ((0,0)->p0, (1,0)->p1, (1,1)->p2, (0,1)->p3). Heckbert's closed form.
    """
    x0, y0 = p0
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    sx = x0 - x1 + x2 - x3
    sy = y0 - y1 + y2 - y3
    if abs(sx) < 1e-12 and abs(sy) < 1e-12:
        # Affine case (parallelogram).
        return Matrix(((x1 - x0, x3 - x0, x0),
                       (y1 - y0, y3 - y0, y0),
                       (0.0, 0.0, 1.0)))
    dx1, dx2 = x1 - x2, x3 - x2
    dy1, dy2 = y1 - y2, y3 - y2
    det = dx1 * dy2 - dx2 * dy1
    if abs(det) < 1e-12:
        raise ValueError('Degenerate quad')
    g = (sx * dy2 - dx2 * sy) / det
    h = (dx1 * sy - sx * dy1) / det
    return Matrix(((x1 - x0 + g * x1, x3 - x0 + h * x3, x0),
                   (y1 - y0 + g * y1, y3 - y0 + h * y3, y0),
                   (g, h, 1.0)))


def corner_pin_matrix(ms):
    """ Inverse homography: projector raster -> unit quad coordinates. """
    corners = [tuple(getattr(ms, c[0])) for c in CORNERS]
    try:
        inv = square_to_quad(*corners).inverted()
    except (ValueError, ZeroDivisionError):
        return None
    # Make sure the denominator is positive inside the quad, so the
    # 'w > 0' test only rejects the mirrored solution.
    cx = sum(c[0] for c in corners) / 4
    cy = sum(c[1] for c in corners) / 4
    if (inv[2][0] * cx + inv[2][1] * cy + inv[2][2]) < 0:
        inv = inv * -1
    return inv


def transform_matrix(ms, aspect):
    """
    Inverse image transform: quad coord -> content coord.
    Rotation is done in aspect-corrected space so it does not shear.
    """
    fx = -1.0 if ms.flip_x else 1.0
    fy = -1.0 if ms.flip_y else 1.0
    sx = ms.scale[0] * ms.scale_uniform * fx
    sy = ms.scale[1] * ms.scale_uniform * fy
    if abs(sx) < 1e-6 or abs(sy) < 1e-6:
        return None
    a = aspect if aspect > 0 else 1.0
    r = ms.rotation

    def t(x, y):
        return Matrix(((1, 0, x), (0, 1, y), (0, 0, 1)))

    def s(x, y):
        return Matrix(((x, 0, 0), (0, y, 0), (0, 0, 1)))

    rot = Matrix(((math.cos(r), -math.sin(r), 0),
                  (math.sin(r), math.cos(r), 0),
                  (0, 0, 1)))
    # Forward: content -> quad.
    forward = (t(0.5 + ms.offset[0], 0.5 + ms.offset[1])
               @ s(1 / a, 1) @ rot @ s(a, 1)
               @ s(sx, sy) @ t(-0.5, -0.5))
    return forward.inverted()


def crop_matrix(ms):
    """ Content coord (0..1) -> source image uv inside the crop window. """
    left, right = ms.crop_left / 100, ms.crop_right / 100
    bottom, top = ms.crop_bottom / 100, ms.crop_top / 100
    w = max(1e-4, 1.0 - left - right)
    h = max(1e-4, 1.0 - bottom - top)
    return Matrix(((w, 0, left), (0, h, bottom), (0, 0, 1)))


def raster_coord_of_point(projector, world_co):
    """
    Where a world-space point lands in the projector raster (normalized,
    origin bottom-left). Returns None when the point is behind the projector.
    Mirrors the math of the spot light node setup.
    """
    from .projector import get_resolution_for
    ps = projector.proj_settings
    local = projector.matrix_world.inverted() @ Vector(world_co)
    if local.z >= -1e-9:
        return None
    xn = local.x / -local.z
    yn = local.y / -local.z
    w, h = get_resolution_for(projector)
    aspect = w / h
    tr = ps.throw_ratio
    u = xn * tr + 0.5 - ps.h_shift / 100
    v = yn * tr * aspect + 0.5 - ps.v_shift / 100
    return u, v


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def _group_tree(projector):
    return projector.children[0].data.node_tree.nodes['Group'].node_tree


def _inside_mask(nodes, links, vec_socket, name, loc):
    """ 1.0 when vec.xy is inside [0, 1], else 0.0. """
    x, y = loc
    sub = nodes.new('ShaderNodeVectorMath')
    sub.operation = 'SUBTRACT'
    sub.inputs[1].default_value = (0.5, 0.5, 0.0)
    sub.location = (x, y)
    ab = nodes.new('ShaderNodeVectorMath')
    ab.operation = 'ABSOLUTE'
    ab.location = (x + 160, y)
    sep = nodes.new('ShaderNodeSeparateXYZ')
    sep.location = (x + 320, y)
    mx = nodes.new('ShaderNodeMath')
    mx.operation = 'MAXIMUM'
    mx.location = (x + 480, y)
    lt = nodes.new('ShaderNodeMath')
    lt.operation = 'LESS_THAN'
    lt.inputs[1].default_value = 0.5 + 1e-5
    lt.name = PREFIX + name
    lt.location = (x + 640, y)
    links.new(vec_socket, sub.inputs[0])
    links.new(sub.outputs[0], ab.inputs[0])
    links.new(ab.outputs[0], sep.inputs[0])
    links.new(sep.outputs[0], mx.inputs[0])
    links.new(sep.outputs[1], mx.inputs[1])
    links.new(mx.outputs[0], lt.inputs[0])
    return lt.outputs[0]


def _dot_row(nodes, links, vec_socket, name, loc):
    n = nodes.new('ShaderNodeVectorMath')
    n.operation = 'DOT_PRODUCT'
    n.name = PREFIX + name
    n.label = name
    n.location = loc
    links.new(vec_socket, n.inputs[0])
    return n.outputs['Value']


def _homogeneous(nodes, links, vec_socket, loc):
    """ (x, y, *) -> (x, y, 1) """
    sep = nodes.new('ShaderNodeSeparateXYZ')
    sep.location = loc
    com = nodes.new('ShaderNodeCombineXYZ')
    com.inputs[2].default_value = 1.0
    com.location = (loc[0] + 160, loc[1])
    links.new(vec_socket, sep.inputs[0])
    links.new(sep.outputs[0], com.inputs[0])
    links.new(sep.outputs[1], com.inputs[1])
    return com.outputs[0]


def has_mapping_nodes(projector):
    try:
        return PREFIX + 'out' in _group_tree(projector).nodes
    except (IndexError, KeyError, AttributeError):
        return False


def ensure_mapping_nodes(projector):
    """
    Insert the mapping chain into the projector node group if it is not there
    yet. Also upgrades projectors created with older versions of the add-on.
    """
    if has_mapping_nodes(projector):
        return
    tree = _group_tree(projector)
    nodes, links = tree.nodes, tree.links

    # The raster coordinate is whatever currently feeds the image texture.
    img = nodes['Image Texture']
    if not img.inputs['Vector'].is_linked:
        return
    src_socket = img.inputs['Vector'].links[0].from_socket
    consumers = [l.to_socket for l in links if l.from_socket == src_socket]

    x0, y0 = img.location[0], img.location[1] - 700
    before = set(n.name for n in nodes)

    # 1) Corner pin: q = H^-1 * (p, 1)
    p_h = _homogeneous(nodes, links, src_socket, (x0, y0))
    hx = _dot_row(nodes, links, p_h, 'h0', (x0 + 360, y0))
    hy = _dot_row(nodes, links, p_h, 'h1', (x0 + 360, y0 - 160))
    hw = _dot_row(nodes, links, p_h, 'h2', (x0 + 360, y0 - 320))
    div_x = nodes.new('ShaderNodeMath')
    div_x.operation = 'DIVIDE'
    div_x.location = (x0 + 540, y0)
    div_y = nodes.new('ShaderNodeMath')
    div_y.operation = 'DIVIDE'
    div_y.location = (x0 + 540, y0 - 160)
    links.new(hx, div_x.inputs[0])
    links.new(hw, div_x.inputs[1])
    links.new(hy, div_y.inputs[0])
    links.new(hw, div_y.inputs[1])
    q = nodes.new('ShaderNodeCombineXYZ')
    q.inputs[2].default_value = 1.0
    q.location = (x0 + 720, y0)
    links.new(div_x.outputs[0], q.inputs[0])
    links.new(div_y.outputs[0], q.inputs[1])
    w_pos = nodes.new('ShaderNodeMath')
    w_pos.operation = 'GREATER_THAN'
    w_pos.inputs[1].default_value = 0.0
    w_pos.location = (x0 + 540, y0 - 320)
    links.new(hw, w_pos.inputs[0])
    m_quad = _inside_mask(nodes, links, q.outputs[0], 'mask_quad', (x0 + 900, y0 - 320))

    # 2) Transform: c = T^-1 * (q, 1)
    cx = _dot_row(nodes, links, q.outputs[0], 't0', (x0 + 900, y0))
    cy = _dot_row(nodes, links, q.outputs[0], 't1', (x0 + 900, y0 - 160))
    c = nodes.new('ShaderNodeCombineXYZ')
    c.inputs[2].default_value = 1.0
    c.location = (x0 + 1080, y0)
    links.new(cx, c.inputs[0])
    links.new(cy, c.inputs[1])
    m_content = _inside_mask(nodes, links, c.outputs[0], 'mask_content', (x0 + 1260, y0 - 320))

    # 3) Crop: uv = C * (c, 1)
    ux = _dot_row(nodes, links, c.outputs[0], 'c0', (x0 + 1260, y0))
    uy = _dot_row(nodes, links, c.outputs[0], 'c1', (x0 + 1260, y0 - 160))
    uv = nodes.new('ShaderNodeCombineXYZ')
    uv.location = (x0 + 1440, y0)
    links.new(ux, uv.inputs[0])
    links.new(uy, uv.inputs[1])

    # 4) Mask: uv * m + (m - 1) * OUTSIDE  -> far outside when masked.
    m1 = nodes.new('ShaderNodeMath')
    m1.operation = 'MULTIPLY'
    m1.location = (x0 + 1440, y0 - 480)
    links.new(w_pos.outputs[0], m1.inputs[0])
    links.new(m_quad, m1.inputs[1])
    m2 = nodes.new('ShaderNodeMath')
    m2.operation = 'MULTIPLY'
    m2.name = PREFIX + 'mask'
    m2.location = (x0 + 1620, y0 - 480)
    links.new(m1.outputs[0], m2.inputs[0])
    links.new(m_content, m2.inputs[1])
    scale = nodes.new('ShaderNodeVectorMath')
    scale.operation = 'SCALE'
    scale.location = (x0 + 1620, y0)
    links.new(uv.outputs[0], scale.inputs[0])
    links.new(m2.outputs[0], scale.inputs['Scale'])
    off = nodes.new('ShaderNodeMath')
    off.operation = 'MULTIPLY_ADD'
    off.inputs[1].default_value = OUTSIDE
    off.inputs[2].default_value = -OUTSIDE
    off.location = (x0 + 1800, y0 - 480)
    links.new(m2.outputs[0], off.inputs[0])
    off_v = nodes.new('ShaderNodeCombineXYZ')
    off_v.location = (x0 + 1980, y0 - 480)
    links.new(off.outputs[0], off_v.inputs[0])
    links.new(off.outputs[0], off_v.inputs[1])
    out = nodes.new('ShaderNodeVectorMath')
    out.operation = 'ADD'
    out.name = PREFIX + 'out'
    out.label = 'Mapped UV'
    out.location = (x0 + 2160, y0)
    links.new(scale.outputs[0], out.inputs[0])
    links.new(off_v.outputs[0], out.inputs[1])

    # Reroute everything that used the raw raster coordinate.
    for sock in consumers:
        links.new(out.outputs[0], sock)

    # Frame the new nodes so they are easy to find.
    frame = nodes.new('NodeFrame')
    frame.name = PREFIX + 'frame'
    frame.label = 'Mapping (corner pin / transform / crop)'
    for n in nodes:
        if n.name not in before and n != frame:
            n.parent = frame


def _set_rows(nodes, names, matrix):
    for i, name in enumerate(names):
        row = matrix[i]
        nodes[PREFIX + name].inputs[1].default_value = (row[0], row[1], row[2])


def apply_mapping(projector):
    """ Push the mapping settings of a projector into its nodes. """
    from .projector import get_resolution_for
    ensure_mapping_nodes(projector)
    if not has_mapping_nodes(projector):
        return
    ms = projector.proj_settings.mapping
    nodes = _group_tree(projector).nodes

    ident = Matrix.Identity(3)
    if ms.enabled:
        h = corner_pin_matrix(ms) or ident
        w, hgt = get_resolution_for(projector)
        t = transform_matrix(ms, w / hgt) or ident
        c = crop_matrix(ms)
    else:
        h = t = c = ident
    _set_rows(nodes, ('h0', 'h1', 'h2'), h)
    _set_rows(nodes, ('t0', 't1'), t)
    _set_rows(nodes, ('c0', 'c1'), c)


def update_mapping(ms, context):
    projector = ms.id_data
    if projector and projector.type == 'CAMERA' and projector.children:
        apply_mapping(projector)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

def _corner_prop(name, default):
    return bpy.props.FloatVectorProperty(
        name=name, size=2, default=default,
        soft_min=-0.5, soft_max=1.5, step=0.1, precision=4,
        description=f'{name} corner of the image in the projector frame '
                    '(0,0 = bottom left of the frame, 1,1 = top right)',
        update=update_mapping)


class ProjectorMappingSettings(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name='Use Mapping', default=True, update=update_mapping,
        description='Apply corner pin, transform and crop to the projected image')

    # Corner pin
    corner_bl: _corner_prop('Bottom Left', CORNER_DEFAULTS['corner_bl'])
    corner_br: _corner_prop('Bottom Right', CORNER_DEFAULTS['corner_br'])
    corner_tr: _corner_prop('Top Right', CORNER_DEFAULTS['corner_tr'])
    corner_tl: _corner_prop('Top Left', CORNER_DEFAULTS['corner_tl'])
    active_corner: bpy.props.EnumProperty(
        name='Corner', items=[c[:3] + (c[4],) for c in CORNERS], default='corner_tl',
        description='Corner used by the snap and nudge tools')
    nudge_step: bpy.props.FloatProperty(
        name='Nudge Step (px)', default=1.0, min=0.01, soft_max=100,
        description='Nudge distance in projector pixels')

    # Transform
    offset: bpy.props.FloatVectorProperty(
        name='Offset', size=2, default=(0.0, 0.0), soft_min=-1, soft_max=1,
        step=0.1, precision=4, update=update_mapping,
        description='Move the image inside the pinned area (fraction of the area)')
    scale: bpy.props.FloatVectorProperty(
        name='Scale', size=2, default=(1.0, 1.0), soft_min=0.05, soft_max=4,
        step=1, precision=3, update=update_mapping)
    scale_uniform: bpy.props.FloatProperty(
        name='Uniform Scale', default=1.0, soft_min=0.05, soft_max=4,
        step=1, precision=3, update=update_mapping)
    rotation: bpy.props.FloatProperty(
        name='Rotation', default=0.0, subtype='ANGLE', update=update_mapping)
    flip_x: bpy.props.BoolProperty(name='Flip X', default=False, update=update_mapping)
    flip_y: bpy.props.BoolProperty(name='Flip Y', default=False, update=update_mapping)

    # Crop (percent of the source image)
    crop_left: bpy.props.FloatProperty(
        name='Left', default=0.0, min=0, max=100, subtype='PERCENTAGE', update=update_mapping)
    crop_right: bpy.props.FloatProperty(
        name='Right', default=0.0, min=0, max=100, subtype='PERCENTAGE', update=update_mapping)
    crop_top: bpy.props.FloatProperty(
        name='Top', default=0.0, min=0, max=100, subtype='PERCENTAGE', update=update_mapping)
    crop_bottom: bpy.props.FloatProperty(
        name='Bottom', default=0.0, min=0, max=100, subtype='PERCENTAGE', update=update_mapping)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class _ProjectorOperator:
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_projector(context) is not None


class PROJECTOR_OT_mapping_reset(_ProjectorOperator, Operator):
    """Reset mapping settings of the selected projector"""
    bl_idname = 'projector.mapping_reset'
    bl_label = 'Reset Mapping'

    section: bpy.props.EnumProperty(items=[
        ('ALL', 'All', ''),
        ('CORNERS', 'Corner Pin', ''),
        ('TRANSFORM', 'Transform', ''),
        ('CROP', 'Crop', ''),
    ], default='ALL')

    def execute(self, context):
        ms = get_projector(context).proj_settings.mapping
        if self.section in {'ALL', 'CORNERS'}:
            for key, val in CORNER_DEFAULTS.items():
                setattr(ms, key, val)
        if self.section in {'ALL', 'TRANSFORM'}:
            ms.offset = (0, 0)
            ms.scale = (1, 1)
            ms.scale_uniform = 1
            ms.rotation = 0
            ms.flip_x = ms.flip_y = False
        if self.section in {'ALL', 'CROP'}:
            ms.crop_left = ms.crop_right = ms.crop_top = ms.crop_bottom = 0
        return {'FINISHED'}


class PROJECTOR_OT_corner_to_cursor(_ProjectorOperator, Operator):
    """Pin the active corner to the 3D cursor. Snap the cursor to a vertex of your
set piece first (Shift+Right Click with snapping) to map onto real geometry"""
    bl_idname = 'projector.corner_to_cursor'
    bl_label = 'Pin Corner to 3D Cursor'

    def execute(self, context):
        projector = get_projector(context)
        ms = projector.proj_settings.mapping
        co = raster_coord_of_point(projector, context.scene.cursor.location)
        if co is None:
            self.report({'WARNING'}, '3D cursor is behind the projector')
            return {'CANCELLED'}
        setattr(ms, ms.active_corner, co)
        return {'FINISHED'}


class PROJECTOR_OT_corners_to_face(_ProjectorOperator, Operator):
    """Pin the four corners to the selected face of a mesh (edit mode selection
of the active object, or its first quad). Corners are matched by position in
the projector frame"""
    bl_idname = 'projector.corners_to_face'
    bl_label = 'Pin Corners to Face'

    target: bpy.props.StringProperty(name='Mesh Object')

    def execute(self, context):
        projector = get_projector(context)
        obj = bpy.data.objects.get(self.target) if self.target else None
        if obj is None:
            obj = next((o for o in context.selected_objects
                        if o.type == 'MESH'), None)
        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, 'Select the projector and a mesh object')
            return {'CANCELLED'}
        if obj.mode == 'EDIT':
            obj.update_from_editmode()
        mesh = obj.data
        face = next((f for f in mesh.polygons if f.select and len(f.vertices) == 4), None)
        if face is None:
            face = next((f for f in mesh.polygons if len(f.vertices) == 4), None)
        if face is None:
            self.report({'WARNING'}, 'No quad face found')
            return {'CANCELLED'}
        pts = []
        for vi in face.vertices:
            co = raster_coord_of_point(projector, obj.matrix_world @ mesh.vertices[vi].co)
            if co is None:
                self.report({'WARNING'}, 'Face is (partly) behind the projector')
                return {'CANCELLED'}
            pts.append(co)
        assign_quad(projector.proj_settings.mapping, pts)
        return {'FINISHED'}


def assign_quad(ms, pts):
    """ Assign 4 raster points to BL, BR, TR, TL keeping the polygon order. """
    cx = sum(p[0] for p in pts) / 4
    cy = sum(p[1] for p in pts) / 4
    # Order counter-clockwise around the center, starting at bottom-left.
    pts = sorted(pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    start = min(range(4), key=lambda i: pts[i][0] + pts[i][1])
    ordered = pts[start:] + pts[:start]
    for key, p in zip(('corner_bl', 'corner_br', 'corner_tr', 'corner_tl'), ordered):
        setattr(ms, key, p)


class PROJECTOR_OT_corner_nudge(_ProjectorOperator, Operator):
    """Nudge the active corner by a number of projector pixels"""
    bl_idname = 'projector.corner_nudge'
    bl_label = 'Nudge Corner'

    direction: bpy.props.EnumProperty(items=[
        ('LEFT', 'Left', ''), ('RIGHT', 'Right', ''),
        ('UP', 'Up', ''), ('DOWN', 'Down', '')])

    def execute(self, context):
        from .projector import get_resolution_for
        projector = get_projector(context)
        ms = projector.proj_settings.mapping
        w, h = get_resolution_for(projector)
        dx, dy = {'LEFT': (-1, 0), 'RIGHT': (1, 0),
                  'UP': (0, 1), 'DOWN': (0, -1)}[self.direction]
        co = list(getattr(ms, ms.active_corner))
        co[0] += dx * ms.nudge_step / w
        co[1] += dy * ms.nudge_step / h
        setattr(ms, ms.active_corner, co)
        return {'FINISHED'}


classes = (
    PROJECTOR_OT_mapping_reset,
    PROJECTOR_OT_corner_to_cursor,
    PROJECTOR_OT_corners_to_face,
    PROJECTOR_OT_corner_nudge,
)


def register():
    # ProjectorMappingSettings is registered from projector.py, before
    # ProjectorSettings, because it is nested inside it.
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
