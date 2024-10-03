from __future__ import annotations

from typing import TYPE_CHECKING, Union
if TYPE_CHECKING:
	from typing_extensions import TypeAlias, override
	nonempty = tuple

from time import perf_counter
from abc import ABC, abstractmethod
from enum import Enum, auto
from datetime import (
	datetime as dt,
	timedelta as td,
)

def Singleton(cls):
	return cls()

@Singleton
class DONE: ...

class DummyTime(Enum):
	# NOW = auto()
	NEVER = auto()

# NOW = DummyTime.NOW
NEVER = DummyTime.NEVER
now = dt.now()
MAX_ITERATIONS = 1<<20

class Condition(ABC):
	@abstractmethod
	def next_true(self, log: list[LogEntry], now: dt, qtask: Task) -> dt | DummyTime:
		'''Assume false now, return when next to set true'''
		...

	@abstractmethod
	def next_false(self, log: list[LogEntry], now: dt, qtask: Task) -> dt | DummyTime:
		'''Assume true now, return when next to set false'''
		...

	def __repr__(self):
		return f'<Condition {self.__class__}>'

class Task:
	def __init__(self, name, colour, cond: Condition):
		self.name = name
		self.colour = colour
		self.cond = cond

	def __repr__(self):
		return self.name

	def next_true(self, log: list[LogEntry], now: dt) -> dt | DummyTime:
		return self.cond.next_true(log, now, self)

	def next_false(self, log: list[LogEntry], now: dt) -> dt | DummyTime:
		return self.cond.next_false(log, now, self)

if TYPE_CHECKING:
	ScheduleEntry = tuple[Task, dt, dt]
	LogEntry = tuple[Task, Union[dt, DONE], dt]

class Never(Condition):
	def next_true(self, log, now, qtask) -> dt | DummyTime:
		return NEVER

	def next_false(self, log, now, qtask) -> dt | DummyTime:
		return now

FREE = Task('(free)', (0, 0, 0), Never())

class Always(Condition):
	def next_true(self, log, now, qtask) -> dt | DummyTime:
		return now

	def next_false(self, log, now, qtask) -> dt | DummyTime:
		return NEVER

class Before(Condition):
	def __init__(self, time: dt):
		self.time = time

	def next_true(self, log, now, qtask) -> dt | DummyTime:
		if now < self.time: return now
		return NEVER

	def next_false(self, log, now, qtask) -> dt | DummyTime:
		if now < self.time: return self.time
		return now

class Total(Condition):
	'''true if you haven't spent enough duration'''

	def __init__(self, duration: td):
		self.duration = duration

	def find_rem(self, log, qtask) -> td:
		qtime = self.duration

		for task, start, end in reversed(log):
			if task is not qtask: continue

			task_time = end-start
			if task_time >= qtime: return td(0)  # may cause inf loops if not taken are of

			qtime -= task_time

		return qtime

	def next_false(self, log, now, qtask) -> dt | DummyTime:
		return now + self.find_rem(log, qtask)

	def next_true(self, log, now, qtask) -> dt | DummyTime:
		# Now if there is time to spend
		if self.find_rem(log, qtask) > td(0): return now

		# No more time to spend
		return NEVER

class In(Condition):
	'''true if you haven't spent enough time recently'''

	def __init__(self, spent: td, past: td):
		self.spent = spent
		self.past = past
		
	def next_false(self, log, now, qtask) -> dt | DummyTime:
		limit = now-self.past+self.spent

		rem = self.spent

		for task, start, end in reversed(log):
			if end <= limit: break
			if task is not qtask: continue

			if start <= limit-rem: start = limit-rem
			task_time = end-start
			if task_time >= rem: return now

			rem -= task_time
			limit -= task_time

		# print(f'  [FALSE] Next false of in({self.spent}) -> {now+rem:%a %d %H:%M} for {qtask}')
		return now+rem

	def next_true(self, log, now, qtask) -> dt | DummyTime:
		limit = now-self.past
		to_spend = self.spent

		for task, start, end in reversed(log):
			if end < limit: break
			if task is not qtask: continue

			if start < limit: start = limit

			task_time = end-start
			if task_time < to_spend:
				to_spend -= task_time
			else:
				# print(f'  [NTRUE] Next true of in({self.spent})@({start:%a %d %H:%M} to {end:%a %d %H:%M}) -> {end-to_spend+self.past:%a %H:%M} for {qtask}')
				return end-to_spend + self.past

		# There is time to spend
		# print(f'  [NTRUE] Next true of in(rem {to_spend} of {self.spent}) -> NOW for {qtask}')
		return now

class Repeat(Condition):
	def __init__(self, anchor: dt, interval: td, duration: td):
		self.anchor = anchor
		self.interval = interval  # start once a day, once a week etc
		self.duration = duration  # how long after starting

	def get_rep_pos(self, now: dt) -> td:
		return (now - self.anchor) % self.interval

	def next_true(self, log, now, qtask) -> dt | DummyTime:
		interval_pos = self.get_rep_pos(now)

		if interval_pos < self.duration: return now
		return now - interval_pos + self.interval
		
	def next_false(self, log, now, qtask) -> dt | DummyTime:
		interval_pos = self.get_rep_pos(now)

		if interval_pos > self.duration: return now
		return now - interval_pos + self.duration

class Event(Condition):
	def __init__(self, start: dt, end: dt):
		self.start = start
		self.end = end

	def next_true(self, log, now, qtask) -> dt | DummyTime:
		if now < self.start: return self.start
		if now < self.end: return now
		return NEVER

	def next_false(self, log, now, qtask) -> dt | DummyTime:
		if now < self.start: return now
		if now < self.end: return self.end
		return now

class Or(Condition):
	def __init__(self, *conds: Condition):
		self.conds = conds

	def next_true(self, log, now, qtask) -> dt | DummyTime:
		out: dt | DummyTime = NEVER

		for cond in self.conds:
			cond_next = cond.next_true(log, now, qtask)
			if cond_next is NEVER: continue
			if cond_next == now: return now
			if out is NEVER or cond_next < out: out = cond_next

		return out

	def next_false(self, log, now, qtask) -> dt | DummyTime:
		latest = now
		last_entry = [qtask, now, now]  # TODO: Forwards compatibility with groups
		simulated_log = log + [last_entry]

		for _ in range(MAX_ITERATIONS):  # avoid `while 1`, maybe check latest < limit
			for cond in self.conds:
				cond_next = cond.next_false(simulated_log, latest, qtask)

				if cond_next is NEVER: return NEVER
				if cond_next > latest:
					latest = cond_next
					last_entry[2] = latest
					break

			else:
				return latest

		raise TimeoutError(f'Scheduling took too long')

class And(Condition):
	def __init__(self, *conds: Condition):
		self.conds = conds

	def next_false(self, log, now, qtask) -> dt | DummyTime:
		out: dt | DummyTime = NEVER

		for cond in self.conds:
			cond_next = cond.next_false(log, now, qtask)
			if cond_next is NEVER: continue
			if cond_next == now: return now
			if out is NEVER or cond_next < out: out = cond_next

		return out

	def next_true(self, log, now, qtask) -> dt | DummyTime:
		latest = now

		for _ in range(MAX_ITERATIONS):  # avoid `while 1`, maybe check latest < limit
			for cond in self.conds:
				cond_next = cond.next_true(log, latest, qtask)

				if cond_next is NEVER: return NEVER
				if cond_next > latest:
					latest = cond_next
					break

			else:
				return latest

		raise TimeoutError(f'Scheduling took too long')

class Not(Condition):
	def __init__(self, cond):
		self.cond = cond

	def next_true(self, log, now, qtask) -> dt | DummyTime:
		return self.cond.next_false(log, now, qtask)

	def next_false(self, log, now, qtask) -> dt | DummyTime:
		return self.cond.next_false(log, now, qtask)

class DoneOnce(Condition):
	def next_true(self, log, qtask) -> dt | DummyTime:
		return NOW

	def next_false(self, log, qtask) -> dt | DummyTime:
		return NEVER



def compute_schedule(tasks: tuple[Task, ...], log: list[LogEntry], latest: dt, limit: dt, *, report_time = True) -> list[ScheduleEntry]:
	if not tasks: return []

	if not isinstance(tasks[0], Task):
		raise TypeError(f'Incorrect Task type: 0x{id(type(tasks[0])):012x} expected 0x{id(Task):012x}')

	log = log.copy()  # We will modify this. Don't want the caller to get a modified log
	l = len(log)

	perf_start = perf_counter()

	while not log or log[-1][2] < limit:
		res = add_one_task(tasks, log, latest)
		if isinstance(res, DummyTime):
			if res is NEVER:
				task, start, _end = log[-1]
				log[-1] = (task, start, limit)
				break
		else:
			latest = res

		# print(f'->[REACH] {latest:%a %d %H:%M}')

	perf_end = perf_counter()
	if report_time:
		print()
		print(f'# Automated scheduling took {(perf_end-perf_start)*1e3:.04f}ms')

	return log[l:]  # type: ignore[return-value]

def add_one_task(tasks: tuple[Task, ...], log: list[LogEntry], now: dt) -> DummyTime | dt:  # return the new latest time
	best_task = tasks[0]
	best_next = best_task.next_true(log, now)
	best_idx = 0

	if best_next is NEVER or best_next > now:
		for i, task in enumerate(tasks[1:]):
			task_next = task.next_true(log, now)
			if task_next is NEVER: continue

			if task_next < best_next:  # type: ignore[operator]
				best_task = task
				best_next = task_next
				best_idx = i
				if task_next == now: break
				# print(f'  [BETRS] {best_next} for {task}')

			# else:
				# print(f'[WORSS] {task_next} for {task}')

	if best_next is NEVER:
		# log.append((FREE, log[-1][2], NEVER))
		# print('  [RET]    NEVER')
		return NEVER  # no more tasks

	# print(f'  [BESTS] {best_next:%a %d %H:%M} from {best_task} ({now = : %a %d %H:%M})')

	if log and log[-1][2] < best_next:
		log.append((FREE, log[-1][2], log[-1][2]))
		# print(f'  [GAP]   {log[-1]}')

	# print(f'  [COND] ', best_task.cond.__class__.__name__)
	best_end: dt | DummyTime = best_task.next_false(log, best_next)
	if best_end != now:
		# if best_end is not NEVER:
		# 	print(f'  [BETRE] {best_end:%a %H:%M} from {best_task}')

		for task in tasks[:best_idx]:
			task_next = task.next_true(log, now)
			if task_next is NEVER: continue
			
			if best_end is NEVER or task_next < best_end:
				best_end = task_next
				# print(f'  [BETRE] {best_end:%a %H:%M} from {task}')
			# else:
				# print(f'[WORSE] {task_next} for {task}')

	# print(f'  [BESTE] {best_end:%a %H:%M}')

	if best_end is NEVER:
		log.append((FREE, log[-1][2], log[-1][2]))
		return NEVER

	if best_end <= best_next:
		raise RuntimeError(f'{best_task} has nonpositive duration ({best_next:%a %d %H:%M} to {best_end:%a %d %H:%M})')

	log.append((best_task, best_next, best_end))
	# print(f'  [TASK]  {best_next:%a %H:%M} to {best_end:%a %H:%M} -> {best_task}')
	return best_end

def main(now, limit, log: list[LogEntry] | None = None):
	epoch = dt.utcfromtimestamp(0)  # Thursday
	from temp_data import tasks, shd
	import logfile

	if log is None:
		with open('scheduler.log', 'rb') as f:
			log = logfile.read((shd.FREE,)+tasks, f)

	schedule = shd.compute_schedule(tasks, log, now, limit)
	print()
	print(len(schedule), 'tasks')
	for task, start, end in schedule:
		# if task is shd.FREE: continue
		print(f'{start:%a %d %H:%M} to {end:%a %d %H:%M} ({end-start}) -> #{int.from_bytes(task.colour, "big"):06x} {task}')

if __name__ == '__main__':
	now = dt.now()
	now = now.replace(microsecond=0)
	main(now, now+td(2))
