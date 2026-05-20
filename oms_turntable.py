bl_info = {
    "name": "OMS Turntable 360°",
    "author": "OMS Studio",
    "version": (3, 1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > OMS Studio",
    "description": "Turntable 360° multi-objets — pivot par objet, export MP4 direct",
    "category": "Animation",
}

import bpy
import math
import os
from bpy.props import (
    IntProperty, EnumProperty, StringProperty,
    BoolProperty, FloatProperty
)
from bpy.types import Panel, Operator, PropertyGroup


# ═══════════════════════════════════════════════════════════════════
#  COMPAT — fcurves Blender 3 / 4 / 5
# ═══════════════════════════════════════════════════════════════════

def get_fcurves(action):
    if hasattr(action, 'fcurves'):
        return list(action.fcurves)
    fcurves = []
    if not hasattr(action, 'layers'):
        return fcurves
    for layer in action.layers:
        for strip in layer.strips:
            cb_attr = getattr(strip, 'channelbag', None)
            if cb_attr is None:
                continue
            if callable(cb_attr):
                slots = getattr(action, 'slots', [])
                for slot in slots:
                    try:
                        bag = cb_attr(slot)
                        if bag and hasattr(bag, 'fcurves'):
                            fcurves.extend(bag.fcurves)
                    except Exception:
                        pass
                if not slots:
                    try:
                        bag = cb_attr()
                        if bag and hasattr(bag, 'fcurves'):
                            fcurves.extend(bag.fcurves)
                    except Exception:
                        pass
            else:
                try:
                    for bag in cb_attr:
                        if hasattr(bag, 'fcurves'):
                            fcurves.extend(bag.fcurves)
                except TypeError:
                    pass
    return fcurves


# ═══════════════════════════════════════════════════════════════════
#  OUTPUT FORMAT
# ═══════════════════════════════════════════════════════════════════

def set_mp4_output(render, quality_preset):
    try:
        render.image_settings.file_format = 'FFMPEG'
        render.ffmpeg.format      = 'MPEG4'
        render.ffmpeg.codec       = 'H264'
        render.ffmpeg.audio_codec = 'NONE'
        crf_map = {
            'FAST':   ('HIGH',     'FAST'),
            'NORMAL': ('HIGH',     'GOOD'),
            'ULTRA':  ('LOSSLESS', 'BEST'),
        }
        render.ffmpeg.constant_rate_factor = crf_map[quality_preset][0]
        render.ffmpeg.ffmpeg_preset        = crf_map[quality_preset][1]
        return True
    except (TypeError, AttributeError):
        pass
    try:
        if hasattr(render.image_settings, 'media_type'):
            render.image_settings.media_type = 'VIDEO'
            for attr in ('ffmpeg', 'ffmpeg_settings'):
                ff = getattr(render, attr, None)
                if ff:
                    try:
                        ff.format = 'MPEG4'
                        ff.codec  = 'H264'
                        if hasattr(ff, 'audio_codec'):
                            ff.audio_codec = 'NONE'
                    except Exception:
                        pass
            return True
    except Exception:
        pass
    try:
        render.image_settings.file_format = 'AVI_JPEG'
        render.image_settings.quality = 95
        return True
    except Exception:
        pass
    return False

def set_png_output(render):
    render.image_settings.file_format = 'PNG'
    render.image_settings.color_mode  = 'RGBA'
    render.image_settings.compression = 15


# ═══════════════════════════════════════════════════════════════════
#  EEVEE / Cycles helpers
# ═══════════════════════════════════════════════════════════════════

def set_eevee_samples(scene, samples):
    for attr in ('taa_render_samples', 'render_samples', 'samples'):
        if hasattr(scene.eevee, attr):
            try:
                setattr(scene.eevee, attr, samples)
                return
            except Exception:
                continue

def safe_set(obj, attr, val):
    if hasattr(obj, attr):
        try:
            setattr(obj, attr, val)
        except Exception:
            pass

def set_cycles_denoiser(cycles):
    safe_set(cycles, 'use_denoising', True)
    for d in ('OPENIMAGEDENOISE', 'NLM'):
        try:
            cycles.denoiser = d
            return
        except Exception:
            continue

def get_default_output():
    return os.path.join(os.path.expanduser("~"), "Desktop", "OMS_Render")

def resolve_output(props):
    raw = props.output_path.strip()
    path = bpy.path.abspath(raw) if raw else get_default_output()
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        path = get_default_output()
        os.makedirs(path, exist_ok=True)
    return path


# ═══════════════════════════════════════════════════════════════════
#  PIVOT HELPERS
# ═══════════════════════════════════════════════════════════════════

PIVOT_PREFIX = "OMS_Pivot_"

def pivot_name_for(obj_name):
    safe = obj_name.replace(" ", "_")[:20]
    return f"{PIVOT_PREFIX}{safe}"

def get_all_oms_pivots():
    return [o for o in bpy.data.objects if o.name.startswith(PIVOT_PREFIX)]

def create_pivot(context, name):
    pivot = bpy.data.objects.new(name, None)
    pivot.empty_display_type = 'PLAIN_AXES'
    pivot.empty_display_size = 0.01
    pivot.hide_render = True
    context.collection.objects.link(pivot)
    return pivot

def center_pivot_on_objects(pivot, objects):
    from mathutils import Vector
    lo = Vector((1e10,) * 3)
    hi = Vector((-1e10,) * 3)
    for obj in objects:
        for corner in obj.bound_box:
            wco = obj.matrix_world @ __import__('mathutils').Vector(corner)
            lo.x = min(lo.x, wco.x); hi.x = max(hi.x, wco.x)
            lo.y = min(lo.y, wco.y); hi.y = max(hi.y, wco.y)
            lo.z = min(lo.z, wco.z); hi.z = max(hi.z, wco.z)
    pivot.location = (lo + hi) / 2

def remove_pivot(pivot):
    for child in list(pivot.children):
        mat = child.matrix_world.copy()
        child.parent = None
        child.matrix_world = mat
    bpy.data.objects.remove(pivot, do_unlink=True)

def set_linear_interpolation(action, axis_idx):
    try:
        for fc in get_fcurves(action):
            if fc.data_path == "rotation_euler" and fc.array_index == axis_idx:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'
    except Exception:
        pass

def update_scene_frame_range(context, start_frame):
    pivots = get_all_oms_pivots()
    all_starts, all_ends = [start_frame], []
    for p in pivots:
        if p.animation_data and p.animation_data.action:
            for fc in get_fcurves(p.animation_data.action):
                if fc.keyframe_points:
                    all_starts.append(int(fc.keyframe_points[0].co.x))
                    all_ends.append(int(fc.keyframe_points[-1].co.x))
    if all_ends:
        context.scene.frame_start   = min(all_starts)
        context.scene.frame_end     = max(all_ends)
        context.scene.frame_current = min(all_starts)

def apply_turntable_to_pivot(pivot, axis_idx, start, total, sign, loops):
    """Applique une animation turntable sur un pivot existant."""
    end = start + total
    pivot.animation_data_clear()
    pivot.rotation_euler[axis_idx] = 0.0
    pivot.keyframe_insert(data_path="rotation_euler", index=axis_idx, frame=start)
    pivot.rotation_euler[axis_idx] = sign * math.pi * 2 * loops
    pivot.keyframe_insert(data_path="rotation_euler", index=axis_idx, frame=end)
    if pivot.animation_data and pivot.animation_data.action:
        set_linear_interpolation(pivot.animation_data.action, axis_idx)
    return end


# ═══════════════════════════════════════════════════════════════════
#  PROPERTIES
# ═══════════════════════════════════════════════════════════════════

class OMS_TurntableProperties(PropertyGroup):
    duration:    IntProperty(name="Durée (frames)", default=120, min=12, max=9999)
    loops:       IntProperty(name="Tours",          default=1,   min=1,  max=100)
    start_frame: IntProperty(name="Frame départ",   default=1,   min=0)
    axis: EnumProperty(name="Axe", default='Z', items=[
        ('Z', "Z — Haut", ""),
        ('Y', "Y",        ""),
        ('X', "X",        ""),
    ])
    direction: EnumProperty(name="Sens", default='POS', items=[
        ('POS', "Anti-horaire  ↺", ""),
        ('NEG', "Horaire  ↻",      ""),
    ])
    mode: EnumProperty(name="Cible", default='ACTIVE', items=[
        ('ACTIVE',    "Objet actif",  ""),
        ('SELECTION', "Sélection",    ""),
    ])
    output_path: StringProperty(name="Dossier", default="", subtype='DIR_PATH')
    output_filename: StringProperty(
        name="Nom du fichier",
        default="turntable",
        description="Nom du fichier de sortie (sans extension)",
    )
    render_mode: EnumProperty(
        name="", default='VIDEO',
        items=[
            ('VIDEO', "Vidéo  MP4", ""),
            ('IMAGE', "Image  PNG", ""),
        ],
    )
    fps: EnumProperty(
        name="FPS",
        default='24',
        description="Images par seconde",
        items=[
            ('24', "24 fps", "Cinéma standard"),
            ('30', "30 fps", "Web / TikTok"),
            ('60', "60 fps", "Smooth / Gaming"),
        ],
    )
    pivots_hidden: BoolProperty(
        name="Pivots cachés",
        default=False,
        description="État hide/show des pivots dans le viewport",
    )


# ═══════════════════════════════════════════════════════════════════
#  OPERATOR — Ajouter turntable
# ═══════════════════════════════════════════════════════════════════

class OMS_OT_CreateTurntable(Operator):
    bl_idname  = "oms.create_turntable"
    bl_label   = "Ajouter Turntable"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.mode == 'OBJECT'

    def execute(self, context):
        props = context.scene.oms_turntable

        if props.mode == 'SELECTION':
            targets = [o for o in context.selected_objects
                       if o.type not in {'CAMERA','LIGHT','EMPTY'}
                       and not o.name.startswith(PIVOT_PREFIX)]
        else:
            obj = context.active_object
            if obj.type in {'CAMERA','LIGHT','EMPTY'} or obj.name.startswith(PIVOT_PREFIX):
                self.report({'WARNING'}, "Sélectionne un objet 3D valide")
                return {'CANCELLED'}
            targets = [obj]

        if not targets:
            self.report({'WARNING'}, "Aucun objet valide")
            return {'CANCELLED'}

        pname = pivot_name_for(context.active_object.name)
        if pname in bpy.data.objects:
            remove_pivot(bpy.data.objects[pname])

        pivot = create_pivot(context, pname)
        center_pivot_on_objects(pivot, targets)
        pivot.rotation_euler = (0, 0, 0)

        for obj in targets:
            if obj.parent and obj.parent.name == pname:
                continue
            mat = obj.matrix_world.copy()
            obj.parent = pivot
            obj.matrix_parent_inverse = pivot.matrix_world.inverted()
            obj.matrix_world = mat

        axis_idx = {'X': 0, 'Y': 1, 'Z': 2}[props.axis]
        sign     = 1 if props.direction == 'POS' else -1
        total    = props.duration * props.loops
        end = apply_turntable_to_pivot(
            pivot, axis_idx, props.start_frame, total, sign, props.loops)

        # Sync FPS
        context.scene.render.fps = int(props.fps)

        update_scene_frame_range(context, props.start_frame)
        self.report({'INFO'}, f"✅ '{pname}' — {len(targets)} obj · {total} frames")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════
#  OPERATOR — Appliquer à tous les pivots
# ═══════════════════════════════════════════════════════════════════

class OMS_OT_ApplyAll(Operator):
    bl_idname  = "oms.apply_all"
    bl_label   = "Appliquer à Tous"
    bl_description = "Applique les settings actuels (axe, durée, sens) à tous les pivots existants"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(get_all_oms_pivots()) > 0

    def execute(self, context):
        props    = context.scene.oms_turntable
        pivots   = get_all_oms_pivots()
        axis_idx = {'X': 0, 'Y': 1, 'Z': 2}[props.axis]
        sign     = 1 if props.direction == 'POS' else -1
        total    = props.duration * props.loops

        for pivot in pivots:
            apply_turntable_to_pivot(
                pivot, axis_idx, props.start_frame, total, sign, props.loops)

        context.scene.render.fps = int(props.fps)
        update_scene_frame_range(context, props.start_frame)
        self.report({'INFO'}, f"✅ Settings appliqués à {len(pivots)} pivot(s)")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════
#  OPERATOR — Dupliquer turntable
# ═══════════════════════════════════════════════════════════════════

class OMS_OT_DuplicateTurntable(Operator):
    bl_idname  = "oms.duplicate_turntable"
    bl_label   = "Dupliquer vers Actif"
    bl_description = "Copie les settings du 1er pivot existant vers l'objet actif"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        pivots = get_all_oms_pivots()
        obj    = context.active_object
        if not obj or not pivots or context.mode != 'OBJECT':
            return False
        # Au moins un pivot source qui n'est PAS l'objet actif
        pname_active = pivot_name_for(obj.name)
        return any(p.name != pname_active for p in pivots)

    def execute(self, context):
        props  = context.scene.oms_turntable
        obj    = context.active_object
        pivots = get_all_oms_pivots()

        pname_active = pivot_name_for(obj.name)
        # Trouver le pivot source (premier différent de l'actif)
        source_pivot = next(
            (p for p in pivots if p.name != pname_active), None)
        if not source_pivot:
            self.report({'WARNING'}, "Aucun pivot source trouvé")
            return {'CANCELLED'}

        # Lire les settings depuis le pivot source
        axis_idx, sign, loops, start = None, 1, 1, 1
        if source_pivot.animation_data and source_pivot.animation_data.action:
            fcs = get_fcurves(source_pivot.animation_data.action)
            for fc in fcs:
                if fc.data_path == "rotation_euler":
                    axis_idx = fc.array_index
                    if len(fc.keyframe_points) >= 2:
                        v0 = fc.keyframe_points[0].co.y
                        v1 = fc.keyframe_points[-1].co.y
                        start = int(fc.keyframe_points[0].co.x)
                        end_f = int(fc.keyframe_points[-1].co.x)
                        total = end_f - start
                        sign  = 1 if v1 > v0 else -1
                        full  = abs(v1 - v0)
                        loops = max(1, round(full / (math.pi * 2)))
                    break

        if axis_idx is None:
            self.report({'WARNING'}, "Impossible de lire les settings du pivot source")
            return {'CANCELLED'}

        # Créer le pivot pour l'objet actif
        if pname_active in bpy.data.objects:
            remove_pivot(bpy.data.objects[pname_active])

        pivot = create_pivot(context, pname_active)
        center_pivot_on_objects(pivot, [obj])
        pivot.rotation_euler = (0, 0, 0)

        mat = obj.matrix_world.copy()
        obj.parent = pivot
        obj.matrix_parent_inverse = pivot.matrix_world.inverted()
        obj.matrix_world = mat

        apply_turntable_to_pivot(pivot, axis_idx, start, total, sign, loops)
        update_scene_frame_range(context, start)
        self.report({'INFO'}, f"✅ Settings copiés de '{source_pivot.name}' → '{pname_active}'")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════
#  OPERATOR — Hide / Show pivots
# ═══════════════════════════════════════════════════════════════════

class OMS_OT_TogglePivots(Operator):
    bl_idname  = "oms.toggle_pivots"
    bl_label   = "Toggle Pivots"
    bl_description = "Cacher / afficher les pivots Empty dans le viewport"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(get_all_oms_pivots()) > 0

    def execute(self, context):
        props  = context.scene.oms_turntable
        pivots = get_all_oms_pivots()
        # Toggle
        new_state = not props.pivots_hidden
        for p in pivots:
            p.hide_viewport = new_state
        props.pivots_hidden = new_state
        state_label = "cachés" if new_state else "visibles"
        self.report({'INFO'}, f"Pivots {state_label} ({len(pivots)})")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════
#  OPERATOR — Clear actif / tous
# ═══════════════════════════════════════════════════════════════════

class OMS_OT_ClearActive(Operator):
    bl_idname  = "oms.clear_active"
    bl_label   = "Clear Actif"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not context.active_object:
            return False
        return pivot_name_for(context.active_object.name) in bpy.data.objects

    def execute(self, context):
        pname = pivot_name_for(context.active_object.name)
        if pname in bpy.data.objects:
            remove_pivot(bpy.data.objects[pname])
            self.report({'INFO'}, f"🗑️ {pname} supprimé")
        return {'FINISHED'}

class OMS_OT_ClearAll(Operator):
    bl_idname  = "oms.clear_all"
    bl_label   = "Clear Tous"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(get_all_oms_pivots()) > 0

    def execute(self, context):
        pivots = get_all_oms_pivots()
        n = len(pivots)
        for p in pivots:
            remove_pivot(p)
        context.scene.oms_turntable.pivots_hidden = False
        self.report({'INFO'}, f"🗑️ {n} pivot(s) supprimé(s)")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════
#  OPERATOR — Preview tous
# ═══════════════════════════════════════════════════════════════════

class OMS_OT_PlayPreview(Operator):
    bl_idname  = "oms.play_preview"
    bl_label   = "Preview Tous"

    def execute(self, context):
        pivots = get_all_oms_pivots()
        if not pivots:
            self.report({'WARNING'}, "Aucun turntable actif")
            return {'CANCELLED'}
        update_scene_frame_range(context, context.scene.oms_turntable.start_frame)
        bpy.ops.screen.animation_play()
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════
#  RENDER
# ═══════════════════════════════════════════════════════════════════

def apply_render_preset(context, preset):
    scene   = context.scene
    render  = scene.render
    props   = scene.oms_turntable
    engine  = render.engine
    mode    = props.render_mode
    out_dir = resolve_output(props)

    # FPS
    render.fps = int(props.fps)
    render.use_motion_blur = False

    configs = {
        'FAST':   (1080, 1080, 80,  64,   16,  0.05),
        'NORMAL': (1080, 1080, 100, 256,  64,  0.02),
        'ULTRA':  (2160, 2160, 100, 1024, 256, 0.005),
    }
    rx, ry, pct, cyc_s, eev_s, threshold = configs[preset]
    render.resolution_x          = rx
    render.resolution_y          = ry
    render.resolution_percentage = pct

    if 'CYCLES' in engine:
        scene.cycles.samples = cyc_s
        set_cycles_denoiser(scene.cycles)
        safe_set(scene.cycles, 'use_adaptive_sampling', True)
        safe_set(scene.cycles, 'adaptive_threshold', threshold)
    else:
        set_eevee_samples(scene, eev_s)
        bloom = preset != 'FAST'
        safe_set(scene.eevee, 'use_bloom', bloom)
        safe_set(scene.eevee, 'use_ssr',   bloom)
        if preset == 'ULTRA':
            safe_set(scene.eevee, 'use_ssr_refraction', True)

    # Nom de fichier custom
    fname = props.output_filename.strip() or "turntable"
    # Sanitize
    fname = "".join(c for c in fname if c.isalnum() or c in ('_', '-', ' ')).strip()
    fname = fname.replace(" ", "_") or "turntable"

    if mode == 'IMAGE':
        render.filepath = os.path.join(out_dir, f"{fname}_")
        set_png_output(render)
        return out_dir, 'IMAGE', fname

    if preset == 'ULTRA':
        render.use_motion_blur = True
    render.filepath = os.path.join(out_dir, fname)
    set_mp4_output(render, preset)
    return out_dir, 'VIDEO', fname


def do_render(operator, context, preset):
    try:
        out_dir, mode, fname = apply_render_preset(context, preset)
        is_anim = (mode == 'VIDEO')
        bpy.ops.render.render('INVOKE_DEFAULT', animation=is_anim)
        ext = ".mp4" if is_anim else ".png"
        operator.report({'INFO'}, f"✅ {fname}{ext} → {out_dir}")
    except Exception as e:
        operator.report({'ERROR'}, f"Erreur : {e}")

class OMS_OT_RenderFast(Operator):
    bl_idname = "oms.render_fast"
    bl_label  = "Rapide"
    bl_description = "864p · 64 samples · Preview client"
    def execute(self, context):
        do_render(self, context, 'FAST'); return {'FINISHED'}

class OMS_OT_RenderNormal(Operator):
    bl_idname = "oms.render_normal"
    bl_label  = "Normal"
    bl_description = "1080p · 256 samples · Tebex / Discord"
    def execute(self, context):
        do_render(self, context, 'NORMAL'); return {'FINISHED'}

class OMS_OT_RenderUltra(Operator):
    bl_idname = "oms.render_ultra"
    bl_label  = "Ultra"
    bl_description = "4K · 1024 samples · TikTok / Portfolio"
    def execute(self, context):
        do_render(self, context, 'ULTRA'); return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════
#  PANELS
# ═══════════════════════════════════════════════════════════════════

class OMS_PT_Main(Panel):
    bl_label       = "OMS  Turntable  360°"
    bl_idname      = "OMS_PT_main"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "OMS Studio"

    def draw_header(self, context):
        self.layout.label(text="", icon='LOOP_FORWARDS')

    def draw(self, context):
        layout = self.layout
        obj    = context.active_object
        props  = context.scene.oms_turntable
        pivots = get_all_oms_pivots()
        n_pivots = len(pivots)
        is_ok  = obj is not None and context.mode == 'OBJECT'

        # ── STATUS ───────────────────────────────────────────────────
        status = layout.box()
        status.scale_y = 0.85
        if context.mode != 'OBJECT':
            status.label(text="Object Mode requis", icon='ERROR')
        elif obj:
            n_sel = len([o for o in context.selected_objects
                         if o.type not in {'CAMERA','LIGHT','EMPTY'}
                         and not o.name.startswith(PIVOT_PREFIX)])
            col = status.column(align=True)
            col.label(text=obj.name, icon='OBJECT_DATA')
            col.label(
                text=f"{n_sel} sélectionné(s)  ·  {n_pivots} pivot(s) actif(s)",
                icon='EMPTY_AXIS',
            )
        else:
            status.label(text="Sélectionne un objet", icon='RESTRICT_SELECT_OFF')

        # ── LISTE PIVOTS ─────────────────────────────────────────────
        if pivots:
            layout.separator(factor=0.3)
            box_list = layout.box()
            row_head = box_list.row()
            row_head.label(text="Turntables actifs :", icon='ANIM')
            # Hide/show
            hidden = props.pivots_hidden
            row_head.operator(
                "oms.toggle_pivots",
                text="Cacher" if not hidden else "Afficher",
                icon='HIDE_ON' if not hidden else 'HIDE_OFF',
                emboss=False,
            )
            for p in pivots:
                row = box_list.row()
                row.scale_y = 0.8
                frames_info = ""
                if p.animation_data and p.animation_data.action:
                    fcs = get_fcurves(p.animation_data.action)
                    if fcs and fcs[0].keyframe_points:
                        s = int(fcs[0].keyframe_points[0].co.x)
                        e = int(fcs[0].keyframe_points[-1].co.x)
                        frames_info = f"  [{s} → {e}]"
                clean = p.name.replace(PIVOT_PREFIX, "")
                row.label(text=f"↺  {clean}{frames_info}", icon='EMPTY_AXIS')

        layout.separator(factor=0.5)

        # ── BOUTON PRINCIPAL ─────────────────────────────────────────
        main_row = layout.row()
        main_row.scale_y = 2.0
        main_row.enabled = is_ok
        main_row.operator(
            "oms.create_turntable",
            text="  Ajouter  Turntable  360°",
            icon='LOOP_FORWARDS',
        )

        layout.separator(factor=0.3)

        # ── APPLY ALL + DUPLICATE ────────────────────────────────────
        tools = layout.row(align=True)
        tools.scale_y = 1.2

        apply_row = tools.row(align=True)
        apply_row.enabled = n_pivots > 0
        apply_row.operator("oms.apply_all", text="Appliquer à Tous", icon='CHECKMARK')

        dup_row = tools.row(align=True)
        dup_row.operator("oms.duplicate_turntable", text="Dupliquer", icon='DUPLICATE')

        layout.separator(factor=0.3)

        # ── PREVIEW ──────────────────────────────────────────────────
        prev_row = layout.row()
        prev_row.scale_y = 1.3
        prev_row.enabled = n_pivots > 0
        prev_row.operator("oms.play_preview", text="▶  Preview Tous", icon='PLAY')

        layout.separator(factor=0.2)

        # ── CLEAR ────────────────────────────────────────────────────
        clear_row = layout.row(align=True)
        clear_row.scale_y = 1.1

        c1 = clear_row.row(align=True)
        pname_active = pivot_name_for(obj.name) if obj else ""
        c1.enabled = pname_active in bpy.data.objects if pname_active else False
        c1.operator("oms.clear_active", text="Clear Actif", icon='OBJECT_DATA')

        c2 = clear_row.row(align=True)
        c2.alert   = n_pivots > 0
        c2.enabled = n_pivots > 0
        c2.operator("oms.clear_all", text=f"Clear Tous ({n_pivots})", icon='TRASH')


# ── Animation ─────────────────────────────────────────────────────

class OMS_PT_Animation(Panel):
    bl_label       = "Animation"
    bl_idname      = "OMS_PT_animation"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "OMS Studio"
    bl_parent_id   = "OMS_PT_main"
    bl_options     = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='TIME')

    def draw(self, context):
        layout = self.layout
        props  = context.scene.oms_turntable

        box_cible = layout.box()
        box_cible.label(text="Cible", icon='RESTRICT_SELECT_OFF')
        row = box_cible.row(align=True)
        row.scale_y = 1.2
        row.prop(props, "mode", expand=True)
        sub = box_cible.row()
        sub.scale_y = 0.7
        if props.mode == 'ACTIVE':
            sub.label(text="Pivot indépendant par objet", icon='INFO')
        else:
            sub.label(text="Pivot groupé pour la sélection", icon='INFO')

        layout.separator(factor=0.5)

        box_dur = layout.box()
        box_dur.label(text="Durée", icon='TIME')
        col = box_dur.column(align=True)
        col.prop(props, "duration")
        col.prop(props, "loops")
        col.prop(props, "start_frame")

        layout.separator(factor=0.5)

        # FPS
        box_fps = layout.box()
        box_fps.label(text="Images par seconde", icon='RENDER_ANIMATION')
        row_fps = box_fps.row(align=True)
        row_fps.scale_y = 1.2
        row_fps.prop(props, "fps", expand=True)

        layout.separator(factor=0.3)

        fps   = int(props.fps)
        total = props.duration * props.loops
        secs  = total / fps
        info  = layout.box()
        info.scale_y = 0.8
        row_i = info.row()
        row_i.label(text=f"  {total} frames", icon='RENDER_ANIMATION')
        row_i.label(text=f"{secs:.1f}s  @  {fps} fps")


# ── Rotation ──────────────────────────────────────────────────────

class OMS_PT_Rotation(Panel):
    bl_label       = "Rotation"
    bl_idname      = "OMS_PT_rotation"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "OMS Studio"
    bl_parent_id   = "OMS_PT_main"
    bl_options     = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='DRIVER_ROTATIONAL_DIFFERENCE')

    def draw(self, context):
        layout = self.layout
        props  = context.scene.oms_turntable

        box_ax = layout.box()
        box_ax.label(text="Axe de rotation", icon='ORIENTATION_GLOBAL')
        row = box_ax.row(align=True)
        row.scale_y = 1.2
        row.prop(props, "axis", expand=True)

        layout.separator(factor=0.5)

        box_sens = layout.box()
        box_sens.label(text="Sens", icon='LOOP_FORWARDS')
        row2 = box_sens.row(align=True)
        row2.scale_y = 1.2
        row2.prop(props, "direction", expand=True)


# ── Rendu & Export ────────────────────────────────────────────────

class OMS_PT_Render(Panel):
    bl_label       = "Rendu & Export"
    bl_idname      = "OMS_PT_render"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "OMS Studio"
    bl_parent_id   = "OMS_PT_main"
    bl_options     = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='RENDER_ANIMATION')

    def draw(self, context):
        layout = self.layout
        props  = context.scene.oms_turntable
        engine = context.scene.render.engine
        engine_label = "Cycles" if 'CYCLES' in engine else "EEVEE"

        # Format
        box_type = layout.box()
        box_type.label(text="Format de sortie", icon='FILE_MOVIE')
        row_t = box_type.row(align=True)
        row_t.scale_y = 1.3
        row_t.prop(props, "render_mode", expand=True)
        sub = box_type.row()
        sub.scale_y = 0.75
        if props.render_mode == 'VIDEO':
            sub.label(text="Animation complète · H264", icon='CHECKMARK')
        else:
            sub.label(text="Frame courante · PNG RGBA", icon='IMAGE_DATA')

        layout.separator(factor=0.5)

        # Nom du fichier
        box_name = layout.box()
        box_name.label(text="Nom du fichier", icon='FILE')
        row_name = box_name.row(align=True)
        row_name.prop(props, "output_filename", text="")
        sub_name = box_name.row()
        sub_name.scale_y = 0.7
        fname = props.output_filename.strip() or "turntable"
        ext = ".mp4" if props.render_mode == 'VIDEO' else ".png"
        sub_name.label(text=f"→ {fname}{ext}", icon='DISCLOSURE_TRI_RIGHT')

        layout.separator(factor=0.5)

        # Dossier
        box_out = layout.box()
        box_out.label(text="Dossier de sortie", icon='FILE_FOLDER')
        box_out.prop(props, "output_path")
        raw     = props.output_path.strip()
        display = bpy.path.abspath(raw) if raw else get_default_output()
        sub2 = box_out.row()
        sub2.scale_y = 0.7
        sub2.label(text=display[:44], icon='DISCLOSURE_TRI_RIGHT')

        layout.separator(factor=0.5)

        # Moteur
        layout.box().label(text=f"Moteur : {engine_label}", icon='SHADING_RENDERED')

        layout.separator(factor=0.5)

        # Qualité
        layout.box().label(text="Qualité de rendu", icon='SETTINGS')
        layout.separator(factor=0.2)

        row_f = layout.row(align=True)
        row_f.scale_y = 1.6
        row_f.operator("oms.render_fast", text="⚡  Rapide", icon='TRIA_RIGHT')
        sub_f = layout.row(); sub_f.scale_y = 0.65
        sub_f.label(text="     864p  ·  64 samples  ·  Denoiser  ·  Preview")

        layout.separator(factor=0.15)

        row_n = layout.row(align=True)
        row_n.scale_y = 1.6
        row_n.operator("oms.render_normal", text="🎬  Normal", icon='TRIA_RIGHT')
        sub_n = layout.row(); sub_n.scale_y = 0.65
        sub_n.label(text="     1080p  ·  256 samples  ·  Denoiser  ·  Tebex")

        layout.separator(factor=0.15)

        row_u = layout.row(align=True)
        row_u.scale_y = 1.6
        row_u.operator("oms.render_ultra", text="💎  Ultra", icon='TRIA_RIGHT')
        sub_u = layout.row(); sub_u.scale_y = 0.65
        sub_u.label(text="     4K  ·  1024 samples  ·  Denoiser  ·  TikTok")


# ═══════════════════════════════════════════════════════════════════
#  REGISTER
# ═══════════════════════════════════════════════════════════════════

classes = (
    OMS_TurntableProperties,
    OMS_OT_CreateTurntable,
    OMS_OT_ApplyAll,
    OMS_OT_DuplicateTurntable,
    OMS_OT_TogglePivots,
    OMS_OT_ClearActive,
    OMS_OT_ClearAll,
    OMS_OT_PlayPreview,
    OMS_OT_RenderFast,
    OMS_OT_RenderNormal,
    OMS_OT_RenderUltra,
    OMS_PT_Main,
    OMS_PT_Animation,
    OMS_PT_Rotation,
    OMS_PT_Render,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.oms_turntable = bpy.props.PointerProperty(
        type=OMS_TurntableProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.oms_turntable

if __name__ == "__main__":
    register()
