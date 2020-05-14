import random

import torch
import numpy as np
from torch.utils.tensorboard import SummaryWriter

from main_helper import run

if __name__ == "__main__":
    # set global parameters
    torch.multiprocessing.set_sharing_strategy('file_system')
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    # set torch settings
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.enabled = True

    run(task='fashionmnist_lenet5', evolver='lshade_state_sharing_conservative', population_size = 30, batch_size=64,
        step_size=250, end_nfe = 30 * 40, n_jobs=8, devices=['cuda:0'], eval_steps=8, tensorboard=False, verbose=3, logging=True)