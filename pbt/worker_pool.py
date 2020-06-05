import os
import gc
import sys
import copy
import time
import math
import random
import warnings
import itertools
from collections.abc import Iterable
from functools import partial
from typing import List, Sequence, Iterable, Callable, Generator
from multiprocessing.managers import SyncManager

import numpy as np
import torch
from multiprocessing.pool import ThreadPool

from pbt.utils.iterable import is_iterable
from .worker import STOP_FLAG, FailMessage, Trial, Worker
from .utils.cuda import get_gpu_memory_stats


# various settings for reproducibility
# set random seed
random.seed(0)
np.random.seed(0)
torch.manual_seed(0)
torch.cuda.manual_seed(0)
torch.cuda.manual_seed_all(0)
# set torch settings
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False
torch.backends.cudnn.enabled = True


class WorkerPool:
    def __init__(self, manager: SyncManager, devices: Sequence[str] = ('cpu',), n_jobs: int = 1, verbose: int = 0):
        if not isinstance(manager, SyncManager):
            raise TypeError(f"the manager specified was of wrong type {type(manager)}, expected {SyncManager}.")
        if not isinstance(devices, (list, tuple)):
            raise TypeError(f"the devices specified was of wrong type {type(devices)}, expected {list} or {tuple}.")
        if not is_iterable(devices):
            raise TypeError(f"the devices specified was not iterable.")
        if not isinstance(n_jobs, int):
            raise TypeError(f"the n_jobs specified was of wrong type {type(n_jobs)}, expected {int}.")
        if n_jobs < len(devices):
            raise ValueError(f"the n_jobs specified must be larger or equal the number of devices, i.e. {n_jobs} < {len(devices)}.")
        if not isinstance(verbose, int):
            raise TypeError(f"the manager specified was of wrong type {type(verbose)}, expected {int}.")
        self.verbose = verbose
        self._cuda = any(device.startswith('cuda') for device in devices)
        self._manager = manager
        self._end_event = manager.Event()
        send_queues = [torch.multiprocessing.Queue() for _ in devices]
        self._workers: List[Worker] = [
            Worker(uid=uid, end_event=self._end_event, receive_queue=send_queue,
                   device=device, random_seed=uid, verbose=verbose > 1)
            for uid, send_queue, device in zip(range(n_jobs), itertools.cycle(send_queues), itertools.cycle(devices))]
        self._workers_iterator = itertools.cycle(self._workers)
        self.__async_return_queue = None

    def _print(self, message: str) -> None:
        if self.verbose < 1:
            return
        full_message = f"{self.__class__.__name__}: {message}"
        print(full_message)

    def __print_gpu_memory_stats(self) -> None:
        if self.verbose < 2 or not self._cuda or os.name == 'nt':
            return
        memory_stats = get_gpu_memory_stats()
        memory_stats_formatted = (
            f"CUDA:{uid} ({memory[0]}/{memory[1]}MB)" for uid, memory in memory_stats.items())
        output = ', '.join(memory_stats_formatted)
        self._print(output)

    def _on_fail_message(self, message: FailMessage) -> None:
        # print info
        print(f"{self.__class__.__name__}: fail message received from worker {message.sender_id}: {message.text}.")
        if message.exception:
            print(f"{self.__class__.__name__}: exception: {message.exception}.")

    def _respawn(self, worker_id: int) -> None:
        # stop existing worker
        worker = self._workers[worker_id]
        self._print(f"terminating old worker with uid {worker_id}...")
        self._stop_worker(worker)
        # spawn new worker
        self._print(f"spawning new worker with uid {worker.uid}...")
        self._workers[worker_id] = Worker(uid=worker.uid, end_event=self._end_event, receive_queue=worker.receive_queue,
                                          device=worker.device, random_seed=worker.uid, verbose=self.verbose > 1)
        self._workers[worker_id].start()

    def _stop_worker(self, worker: Worker) -> None:
        worker.terminate()
        worker.join()
        worker.close()

    def start(self) -> None:
        if any(worker.is_alive() for worker in self._workers):
            raise Exception("service is already running. Consider calling stop() when service is not in use.")
        [worker.start() for worker in self._workers]

    def stop(self) -> None:
        self._end_event.set()
        try:
            if not any(worker.is_alive() for worker in self._workers):
                warnings.warn("service is not running.")
                return
            [worker.receive_queue.put(STOP_FLAG) for worker in self._workers]
            [worker.join() for worker in self._workers]
            [worker.close() for worker in self._workers]
        except ValueError:
            warnings.warn("one or more members are not running.")

    def apply_async(self, function: Callable[[object], object], parameters: object) -> None:
        if self.__async_return_queue is None:
            self.__async_return_queue = self._manager.Queue()
        worker = next(self._workers_iterator)
        self._print(f"pushing job to worker receive queue...")
        trial = Trial(return_queue=self.__async_return_queue, function=function, parameters=parameters)
        worker.receive_queue.put(trial)

    def get(self) -> object:
        if self.__async_return_queue is None:
            raise Exception("'apply_async' must be called at least once before 'get'.")
        result = self.__async_return_queue.get()
        if isinstance(result, FailMessage):
            self._on_fail_message(result)
            raise Exception("worker failed.")
        return result

    def imap(self, function: Callable[[object], object], parameters: Sequence[object], shuffle: bool = False) -> Generator[object, None, None]:
        if not callable(function):
            raise TypeError("'function' is not callable")
        if not isinstance(parameters, (list, tuple)):
            raise TypeError("'parameters' is not a sequence")
        if not isinstance(shuffle, bool):
            raise TypeError("'shuffle' is not a bool")
        if shuffle:
            random.shuffle(parameters)
        n_sent = 0
        n_returned = 0
        failed_workers = set()
        return_queue = self._manager.Queue()
        self._print(f"queuing parameters...")
        for parameters, worker in zip(parameters, self._workers_iterator):
            trial = Trial(return_queue=return_queue, function=function, parameters=parameters)
            worker.receive_queue.put(trial)
            n_sent += 1
        self._print(f"awaiting results...")
        while n_returned != n_sent and len(failed_workers) < len(self._workers):
            result = return_queue.get()
            if isinstance(result, FailMessage):
                self._on_fail_message(result)
                failed_workers.add(result.sender_id)
                continue
            n_returned += 1
            yield result
        # check if all processes were successful
        if not return_queue.empty():
            raise Exception("return queue is not empty.")
        elif len(failed_workers) == len(self._workers):
            raise Exception("all workers failed.")
        elif n_returned < n_sent:
            if failed_workers:
                raise Exception(f"{len(failed_workers)} workers failed.")
            else:
                raise Exception(f"{n_sent - n_returned} one or more parameters failed.")
        elif failed_workers:
            self._respawn(failed_workers)
        else:
            self._print("all parameters were executed successfully.")
