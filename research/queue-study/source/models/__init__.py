from .base import QueueModel
# импорт «триггерит» регистрацию классов через __init_subclass__
from . import random_model      # noqa: F401
from . import priority_model    # noqa: F401
from . import priority_clamped_model  # noqa: F401
from . import most_passed_model       # noqa: F401
from . import fifo_model        # noqa: F401

MODELS = QueueModel.all()