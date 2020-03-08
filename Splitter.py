import multiprocessing
import threading
from collections import defaultdict
from pprint import pprint
import time
import queue as mul_q
from datetime import datetime

def mapper(input, output, index, shoot_continue, is_finished):
    print('start', threading.get_ident(), index)
    while shoot_continue.value:
        try:
            chunk = input.get(timeout=0.05)
            result_dict = defaultdict(int)
            for c in chunk:
                result_dict[c] += 1
            # print(chunk)
            output.put(result_dict)
        except mul_q.Empty:
            pass
    print('finish', threading.get_ident(), index)
    is_finished.value = 1
    
def reduce_dict(input_reduce, shoot_continue, is_finished_all):
    result = dict()

    while sum([x.value for x in is_finished_all]) < 3 or not input_reduce.empty():
        try:
            input_dict = input_reduce.get(timeout=0.05)
            for k, v in input_dict.items():
                if k in result:
                    result[k] += v
                else:
                    result[k] = v
        except mul_q.Empty:
            pass
    pprint(result) 

if __name__ == '__main__': 
    time_start = datetime.now()
    queue_map = multiprocessing.Queue()
    queue_reduce = multiprocessing.Queue()
    shoot_continue = multiprocessing.Value('d', 1)
    
    is_finished1 = multiprocessing.Value('d', 0)
    is_finished2 = multiprocessing.Value('d', 0)
    is_finished3 = multiprocessing.Value('d', 0)
    
    procs = [
        multiprocessing.Process(target=mapper, args=(queue_map, queue_reduce, 1, shoot_continue, is_finished1)),
        multiprocessing.Process(target=mapper, args=(queue_map, queue_reduce, 2, shoot_continue, is_finished2)),
        multiprocessing.Process(target=mapper, args=(queue_map, queue_reduce, 3, shoot_continue, is_finished3)),
        multiprocessing.Process(target=reduce_dict, args=(queue_reduce, shoot_continue, [is_finished1, is_finished2, is_finished3])),
    ]
    
    for p in procs:
        p.start()

    with open('file.txt') as inp:
        chunk = []
        start_elapsed = time.time_ns()
        while True:
            line = inp.readline()[0:-1]
            if line == '':
                time_elapsed = time.time_ns() - start_elapsed
                if time_elapsed < 100000000:
                    time.sleep(0.1)
                queue_map.put(chunk, timeout=0.1)
                start_elapsed = time.time_ns()
                break
            
            chunk.append(line)
            if len(chunk) > 200000:
                time_elapsed = time.time_ns() - start_elapsed
                #pprint(time_elapsed)
                if time_elapsed < 100000000:
                    time.sleep(0.1)
                queue_map.put(chunk, timeout=0.1)
                start_elapsed = time.time_ns()
                chunk = []
    shoot_continue.value = 0
    queue_map.close()
    queue_map.join_thread()
    queue_reduce.close()

    for p in procs:
        p.join()
    time_end = datetime.now()
    print(((time_end - time_start).seconds))