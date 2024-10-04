from __future__ import annotations

from datetime import datetime as dt
from Scheduler import Task, Never, DONE
import struct

from typing import TYPE_CHECKING
if TYPE_CHECKING:
	from Scheduler import LogEntry

# taskid != taskidx
# taskid:  str
# taskidx: int

from typing import Any
binary = Any

taskidx_fmt  = '!I'
tasklen_fmt  = '!B'
logentry_fmt = f'{taskidx_fmt}iI'  # taskidx, start, end

taskidx_size  = struct.calcsize(taskidx_fmt)
tasklen_size  = struct.calcsize(tasklen_fmt)
logentry_size = struct.calcsize(logentry_fmt)

def dummy_task(name: str, colour) -> Task:
	return Task(name, colour, Never())

def read(tasks: tuple[Task, ...], file: 'binary', default_colour=(27, 27, 27)) -> list[LogEntry]:
	task_map = {}  # using name as the unique identifier
	for task in tasks:
		if task.name in task_map:
			raise ValueError(f'{task.name!r} already exists. Task names must be unique.')

		task_map[task.name] = task

	[ntasks] = struct.unpack(taskidx_fmt, file.read(taskidx_size))

	tasklens = [
		struct.unpack(tasklen_fmt, file.read(tasklen_size))[0]
		for _ in range(ntasks)
	]

	log_tasks = []
	for l in tasklens:
		taskid = file.read(l).decode()
		if taskid in task_map:
			task = task_map[taskid]
		else:
			task = dummy_task(taskid, default_colour)
			task_map[taskid] = task
			# raise ValueError(f'{taskid!r} is not a defined task')

		log_tasks.append(task)

	log = []

	while 1:
		entry_code = file.read(logentry_size)
		if not entry_code: break
		if len(entry_code) < logentry_size:
			raise ValueError('Log file is corrupted. Found invalid size')

		task_idx, start, end = struct.unpack(logentry_fmt, entry_code)
		if start < 0:
			start = DONE
		else:
			start = dt.fromtimestamp(start)
		log.append((log_tasks[task_idx], start, dt.fromtimestamp(end)))

	return log

def write(tasks: tuple[Task, ...], log: list[LogEntry], file: 'binary') -> None:
	task_map = {}  # using name as the unique identifier
	for i, task in enumerate(tasks):
		if task.name in task_map:
			raise ValueError(f'{task.name!r} already exists. Task names must be unique.')

		task_map[task.name] = i

	# file must be read-write
	log_backup = file.read()

	try:
		file.seek(0)
		file.write(struct.pack(taskidx_fmt, len(tasks)))

		encoded_names = [task.name.encode() for task in tasks]

		for enc_name in encoded_names:
			file.write(struct.pack(tasklen_fmt, len(enc_name)))

		for enc_name in encoded_names: file.write(enc_name)

		for task, start, end in log:
			if task.name in task_map:
				taskid = task_map[task.name]
			else:
				taskid = len(task_map)
				task_map[task.name] = taskid

			if isinstance(start, dt):
				start_time = int(start.timestamp())
			else:
				start_time = -1

			file.write(struct.pack(logentry_fmt, taskid, start_time, int(end.timestamp())))

	except:
		# Restore backup
		file.seek(0)
		file.write(log_backup)
		file.truncate()
		raise

if __name__ == '__main__':
	import Scheduler as shd
	from temp_data import tasks, now

	with open('scheduler.log', 'rb') as f:
		log = read([shd.FREE]+tasks, f)
	print('Log file has been parsed:')
	for task, start, end in log:
		print(f'  {task} {start:%a, %d %b %H:%M} to {end:%a, %d %b %H:%M}')
