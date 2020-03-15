import datetime
import functools
import multiprocessing
import os
import queue as mul_q
import time
from collections import defaultdict
from itertools import zip_longest

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


def timeit(timer=time.clock):
    def _inner(func):
        @functools.wraps(func)
        def _wrapped(*args, **kwargs):
            start = timer()
            result = func(*args, **kwargs)
            end = timer()
            print(func.__name__, end - start)
            return result

        return _wrapped

    return _inner


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
        return not all(map(lambda x: x.finished.value, processes))

    return wrapped


def start_processes(processes):
    for p in processes:
        p.start()


def stop_processes(processes):
    for p in processes:
        p.join()


@show_process_id
@timeit()
def splitter(input_queue: multiprocessing.Queue, output_queue: multiprocessing.Queue, should_continue, timeout=0.001):
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
@timeit()
def mapper(input_queue: multiprocessing.Queue, output_queue: multiprocessing.Queue, should_continue, timeout=0.001):
    while should_continue() or not input_queue.empty():
        try:
            chunk = input_queue.get(timeout=timeout)
        except mul_q.Empty:
            continue

        result_dict = defaultdict(int)
        for c in chunk:
            result_dict[c] += 1
        output_queue.put(dict(result_dict))


def grouper(iterable, n, fillvalue=None):
    """Collect data into fixed-length chunks or blocks"""
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    args = [iter(iterable)] * n
    return zip_longest(fillvalue=fillvalue, *args)


def merge_dicts(dict1, dict2, group_size=128):
    if len(dict1) == 0:
        dict1.update(dict2)
        return dict1

    for chunk in grouper(dict2.items(), group_size):
        chunk = filter(None, chunk)

        dict1.update({k: v + dict1.get(k, 0) for k, v in chunk})

    return dict1


@show_process_id
@timeit()
def reducer(input_queue: multiprocessing.Queue, output_queue: multiprocessing.Queue, should_continue, merge_count=128, timeout=0.01):
    result = dict()
    counter = 0

    while should_continue() or not input_queue.empty():
        try:
            input_dict = input_queue.get(timeout=timeout)
        except mul_q.Empty:
            if counter > merge_count / 10:
                output_queue.put(result)
                result = dict()
                counter = 0
            else:
                time.sleep(timeout)
            continue

        merge_dicts(result, input_dict)
        counter = counter + 1
        if counter > merge_count:
            output_queue.put(result)
            result = dict()
            counter = 0

    output_queue.put(result)


@timeit()
def final_reducer(input_queue, should_continue, timeout=0.05):
    result = dict()

    while should_continue() or not input_queue.empty():
        try:
            input_dict = input_queue.get(timeout=timeout)
        except mul_q.Empty:
            continue

        merge_dicts(result, input_dict)

    return result


@timeit(timer=datetime.datetime.now)
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

    queue_reducers_output = multiprocessing.Queue(maxsize=1024)

    reducers = [
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
    stop_processes(reducers)

    queue_reducers_output.close()

    return result


if __name__ == '__main__':
    result = start()
    print(len(result))

    # import json
    # with open(FILE_OUTPUT, 'w') as out:
    #     json.dump(result, out)
