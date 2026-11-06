import numpy as np
from .base import QueueModel


class FifoQueueModel(QueueModel):
    name = "fifo"
    description = "Кто дольше всех ждёт (меньший номер текущей лабы — первым)"

    def order_queue(self, state):
        active = state.active()
        if active.size == 0:
            return active
        keys = state.current_lab[active]
        tiebreak = state.rng.random(active.size)
        order_idx = np.lexsort((tiebreak, keys))
        return active[order_idx]