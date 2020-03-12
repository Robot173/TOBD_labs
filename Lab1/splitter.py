import functools
import multiprocessing
import os
import queue as mul_q
import time
from collections import defaultdict
import json

CHUNK_SIZE = 1000 * 1024
FILE = "inputv10.txt"
FILE_OUTPUT = "output.json"


class Process(multiprocessing.Process):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.finished = multiprocessing.Value('i', 0)

    def run(self):
        self.finished.value = 0
        res = super().run()
        self.finished.value = 1
        return res


def timeit(func):
    @functools.wraps(func)
    def _wrapped(*args, **kwargs):
        start = time.clock()
        result = func(*args, **kwargs)
        end = time.clock()
        print(func.__name__, end - start)
        return result

    return _wrapped


def show_process_id(func):
    @functools.wraps(func)
    def _wrapped(*args, **kwargs):
        print(func.__name__, 'starting', multiprocessing.current_process().pid)
        result = func(*args, **kwargs)
        print(func.__name__, 'finishing', multiprocessing.current_process().pid)
        return result

    return _wrapped


def is_alive(processes):
    def wrapped():
        # print(list(map(lambda x: x.finished.value, processes)))
        return not all(map(lambda x: x.finished.value, processes))

    return wrapped


def start_processes(processes):
    for p in processes:
        p.start()


def stop_processes(processes):
    for p in processes:
        p.join()


@show_process_id
@timeit
def splitter(input_queue: multiprocessing.Queue, output_queue: multiprocessing.Queue, should_continue, timeout=0.05):
    with open(FILE, 'r') as f:
        while should_continue.value or not input_queue.empty():
            try:
                task = input_queue.get(timeout=timeout)
            except mul_q.Empty:
                continue

            start_index, size = task

            f.seek(start_index)
            chunk = f.read(size).split('\n')[:-1]
            output_queue.put(chunk)


@show_process_id
@timeit
def mapper(input_queue: multiprocessing.Queue, output_queue: multiprocessing.Queue, should_continue, timeout=0.05):
    while should_continue() or not input_queue.empty():
        try:
            chunk = input_queue.get(timeout=timeout)
        except mul_q.Empty:
            continue

        result_dict = defaultdict(int)
        for c in chunk:
            result_dict[c] += 1
        output_queue.put(result_dict)


@show_process_id
@timeit
def reducer(input_queue, output_queue, should_continue, timeout=0.05):
    result = dict()

    while should_continue() or not input_queue.empty():
        try:
            input_dict = input_queue.get(timeout=timeout)
        except mul_q.Empty:
            continue

        for k in input_dict:
            if k in result:
                result[k] += input_dict[k]
            else:
                result[k] = input_dict[k]

    output_queue.put(result)


@timeit
def final_reducer(input_queue, should_continue, timeout=0.05):
    result = dict()

    while should_continue() or not input_queue.empty():
        try:
            input_dict = input_queue.get(timeout=timeout)
        except mul_q.Empty:
            continue

        for k in input_dict:
            if k in result:
                result[k] += input_dict[k]
            else:
                result[k] = input_dict[k]

    return result


@timeit
def start():
    should_continue = multiprocessing.Value('d', 1)

    queue_splitter_input = multiprocessing.Queue(maxsize=100)
    queue_splitter_output = multiprocessing.Queue(maxsize=100)

    splitters = [
        Process(target=splitter, args=(queue_splitter_input, queue_splitter_output, should_continue)),
        Process(target=splitter, args=(queue_splitter_input, queue_splitter_output, should_continue)),
    ]

    start_processes(splitters)

    queue_map_output = multiprocessing.Queue(maxsize=100)

    mappers = [
        Process(target=mapper, args=(queue_splitter_output, queue_map_output, is_alive(splitters),)),
        Process(target=mapper, args=(queue_splitter_output, queue_map_output, is_alive(splitters),)),
        Process(target=mapper, args=(queue_splitter_output, queue_map_output, is_alive(splitters),)),
    ]

    start_processes(mappers)
    queue_reducers_output = multiprocessing.Queue(maxsize=100)

    reducers = [
        Process(target=reducer, args=(queue_map_output, queue_reducers_output, is_alive(mappers),)),
        Process(target=reducer, args=(queue_map_output, queue_reducers_output, is_alive(mappers),)),
        Process(target=reducer, args=(queue_map_output, queue_reducers_output, is_alive(mappers),)),
        Process(target=reducer, args=(queue_map_output, queue_reducers_output, is_alive(mappers),)),
    ]

    start_processes(reducers)
    file_size = os.path.getsize(FILE)

    with open(FILE, 'rb') as inp:
        pos_start = 0
        pos_end = CHUNK_SIZE

        while pos_end < file_size:
            inp.seek(pos_end)
            while inp.read(1) != b'\n':
                pos_end = pos_end + 1
            queue_splitter_input.put([pos_start, pos_end - pos_start])
            pos_start = pos_end
            pos_end = min(pos_start + CHUNK_SIZE, file_size)

        queue_splitter_input.put([pos_start, pos_end - pos_start])
        should_continue.value = 0

    result = final_reducer(queue_reducers_output, is_alive(reducers))

    queue_splitter_input.close()
    stop_processes(splitters)

    queue_splitter_output.close()
    stop_processes(mappers)

    queue_map_output.close()
    queue_reducers_output.close()
    stop_processes(reducers)

    return result


if __name__ == '__main__':
    result = start()
    # with open(FILE_OUTPUT, 'w') as out:
    #     json.dump(result, out)
