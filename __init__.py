from . import ui
from . import projector
from . import operators
from . import mapping


def register():
    projector.register()
    operators.register()
    mapping.register()
    ui.register()


def unregister():
    ui.unregister()
    mapping.unregister()
    operators.unregister()
    projector.unregister()
