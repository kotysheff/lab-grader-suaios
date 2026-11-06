import numpy as np
from .base import QueueModel


# Настраиваемый «пол» приоритета.
# priority = deadline_текущей_лабы − week, но не меньше этого значения.
#   -3  → просрочка ≥ 3 недель больше не даёт преимущества в очереди
#   -10 → фактически «без ограничения» (эквивалент обычной priority),
#         т.к. максимальная просрочка в модели не превышает N_WEEKS
MIN_PRIORITY = -1


class PriorityClampedQueueModel(QueueModel):
    name = "priority_clamped"
    description = (
        "Как priority, но приоритет ограничен снизу: "
        f"priority = max({MIN_PRIORITY}, deadline_текущей_лабы − week). "
        "Просрочившие на 3+ недель равны между собой и разыгрываются случайно"
    )

    def order_queue(self, state):
        active = state.active()
        if active.size == 0:
            return active

        current_deadlines = state.deadlines[state.current_lab[active]]
        priorities = current_deadlines - state.week
        # ← единственное отличие от PriorityQueueModel
        priorities = np.maximum(priorities, MIN_PRIORITY)

        tiebreak = state.rng.random(active.size)
        order_idx = np.lexsort((tiebreak, priorities))
        return active[order_idx]