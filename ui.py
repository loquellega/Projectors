from .helper import get_projectors
from .projector import RESOLUTIONS, Textures

import bpy
from bpy.types import Panel, PropertyGroup, UIList, Operator


class PROJECTOR_PT_projector_settings(Panel):
    bl_idname = 'OBJECT_PT_projector_n_panel'
    bl_label = 'Projector'
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Projector"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row(align=True)
        row.operator('projector.create',
                     icon='ADD', text="New")
        row.operator('projector.delete',
                     text='Remove', icon='REMOVE')

        if context.scene.render.engine == 'BLENDER_EEVEE':
            box = layout.box()
            box.label(text='Image Projection only works in Cycles.', icon='ERROR')
            box.operator('projector.switch_to_cycles')

        selected_projectors = get_projectors(context, only_selected=True)
        if len(selected_projectors) == 1:
            projector = selected_projectors[0]
            proj_settings = projector.proj_settings

            layout.separator()

            layout.label(text='Projector Settings:')
            box = layout.box()
            box.prop(proj_settings, 'throw_ratio')
            box.prop(proj_settings, 'power', text='Power')
            res_row = box.row()
            res_row.prop(proj_settings, 'resolution',
                         text='Resolution', icon='PRESET')
            if proj_settings.projected_texture == Textures.CUSTOM_TEXTURE.value and proj_settings.use_custom_texture_res:
                res_row.active = False
                res_row.enabled = False
            else:
                res_row.active = True
                res_row.enabled = True
            # Lens Shift
            col = box.column(align=True)
            col.prop(proj_settings,
                     'h_shift', text='Horizontal Shift')
            col.prop(proj_settings, 'v_shift', text='Vertical Shift')
            layout.prop(proj_settings,
                        'projected_texture', text='Project')
            # Pixel Grid
            box.prop(proj_settings, 'show_pixel_grid')

            # Custom Texture
            if proj_settings.projected_texture == Textures.CUSTOM_TEXTURE.value:
                box = layout.box()
                box.prop(proj_settings, 'use_custom_texture_res')
                node = get_projectors(context, only_selected=True)[
                    0].children[0].data.node_tree.nodes['Image Texture']
                box.template_image(node, 'image', node.image_user, compact=False)


class PROJECTOR_PT_projected_color(Panel):
    bl_label = "Projected Color"
    bl_parent_id = "OBJECT_PT_projector_n_panel"
    bl_option = {'DEFAULT_CLOSED'}
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    @classmethod
    def poll(self, context):
        """ Only show if projected texture is set to  'checker'."""
        projector = context.object
        return bool(get_projectors(context, only_selected=True)) and projector.proj_settings.projected_texture == Textures.CHECKER.value

    def draw(self, context):
        projector = context.object
        layout = self.layout
        layout.use_property_decorate = False
        col = layout.column()
        col.use_property_split = True
        col.prop(projector.proj_settings, 'projected_color', text='Color')
        col.operator('projector.change_color',
                     icon='MODIFIER_ON', text='Random Color')


class PROJECTOR_PT_mapping(Panel):
    bl_label = "Image Mapping"
    bl_parent_id = "OBJECT_PT_projector_n_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    @classmethod
    def poll(cls, context):
        return len(get_projectors(context, only_selected=True)) == 1

    def draw_header(self, context):
        ms = get_projectors(context, only_selected=True)[0].proj_settings.mapping
        self.layout.prop(ms, 'enabled', text='')

    def draw(self, context):
        projector = get_projectors(context, only_selected=True)[0]
        ms = projector.proj_settings.mapping
        layout = self.layout
        layout.use_property_decorate = False
        layout.active = ms.enabled
        layout.operator('projector.mapping_reset', icon='LOOP_BACK', text='Reset All').section = 'ALL'


class PROJECTOR_PT_mapping_corners(Panel):
    bl_label = "Corner Pin"
    bl_parent_id = "PROJECTOR_PT_mapping"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        projector = get_projectors(context, only_selected=True)[0]
        ms = projector.proj_settings.mapping
        layout = self.layout
        layout.use_property_decorate = False
        layout.active = ms.enabled

        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=False)
        for key, label in (('corner_tl', 'Top Left'), ('corner_tr', 'Top Right'),
                           ('corner_bl', 'Bottom Left'), ('corner_br', 'Bottom Right')):
            col = grid.column(align=True)
            col.label(text=label)
            col.prop(ms, key, text='')

        box = layout.box()
        box.label(text='Pin Tools', icon='PIVOT_CURSOR')
        box.row().prop(ms, 'active_corner', expand=True)
        box.operator('projector.corner_to_cursor', icon='CURSOR')
        row = box.row(align=True)
        row.operator('projector.corner_nudge', text='', icon='TRIA_LEFT').direction = 'LEFT'
        row.operator('projector.corner_nudge', text='', icon='TRIA_DOWN').direction = 'DOWN'
        row.operator('projector.corner_nudge', text='', icon='TRIA_UP').direction = 'UP'
        row.operator('projector.corner_nudge', text='', icon='TRIA_RIGHT').direction = 'RIGHT'
        row.prop(ms, 'nudge_step', text='px')
        box.operator('projector.corners_to_face', icon='FACESEL')
        box.label(text='Select projector + mesh (selected quad face).', icon='INFO')

        layout.operator('projector.mapping_reset', text='Reset Corners').section = 'CORNERS'


class PROJECTOR_PT_mapping_transform(Panel):
    bl_label = "Transform"
    bl_parent_id = "PROJECTOR_PT_mapping"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        ms = get_projectors(context, only_selected=True)[0].proj_settings.mapping
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.active = ms.enabled
        col = layout.column(align=True)
        col.prop(ms, 'offset')
        col = layout.column(align=True)
        col.prop(ms, 'scale_uniform')
        col.prop(ms, 'scale')
        layout.prop(ms, 'rotation')
        row = layout.row(align=True)
        row.prop(ms, 'flip_x', toggle=True)
        row.prop(ms, 'flip_y', toggle=True)
        layout.operator('projector.mapping_reset', text='Reset Transform').section = 'TRANSFORM'


class PROJECTOR_PT_mapping_crop(Panel):
    bl_label = "Crop"
    bl_parent_id = "PROJECTOR_PT_mapping"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        ms = get_projectors(context, only_selected=True)[0].proj_settings.mapping
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.active = ms.enabled
        col = layout.column(align=True)
        col.prop(ms, 'crop_left')
        col.prop(ms, 'crop_right')
        col.prop(ms, 'crop_top')
        col.prop(ms, 'crop_bottom')
        layout.operator('projector.mapping_reset', text='Reset Crop').section = 'CROP'


MAPPING_PANELS = (PROJECTOR_PT_mapping, PROJECTOR_PT_mapping_corners,
                  PROJECTOR_PT_mapping_transform, PROJECTOR_PT_mapping_crop)


def append_to_add_menu(self, context):
    self.layout.operator('projector.create',
                         text='Projector', icon='CAMERA_DATA')


def register():
    bpy.utils.register_class(PROJECTOR_PT_projector_settings)
    bpy.utils.register_class(PROJECTOR_PT_projected_color)
    for cls in MAPPING_PANELS:
        bpy.utils.register_class(cls)
    # Register create  in the blender add menu.
    bpy.types.VIEW3D_MT_light_add.append(append_to_add_menu)


def unregister():
    # Register create in the blender add menu.
    bpy.types.VIEW3D_MT_light_add.remove(append_to_add_menu)
    for cls in reversed(MAPPING_PANELS):
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(PROJECTOR_PT_projected_color)
    bpy.utils.unregister_class(PROJECTOR_PT_projector_settings)
