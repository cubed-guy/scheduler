from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
	from typing_extensions import TypeAlias, override
	nonempty: TypeAlias = list

from time import perf_counter
from abc import ABC, abstractmethod
from enum import Enum, auto
from datetime import (
	datetime as dt,
	timedelta as td,
)

class DummyTime(Enum):
	NOW = auto()
	NEVER = auto()

NOW = DummyTime.NOW
NEVER = DummyTime.NEVER
now = dt.now()

class Condition(ABC):
	@abstractmethod
	def next_true(self, log: list[ScheduleEntry], qtask: Task) -> dt | DummyTime:  ...

	@abstractmethod
	def next_false(self, log: list[ScheduleEntry], qtask: Task) -> dt | DummyTime:  ...

class Task:
	def __init__(self, name, colour, cond: Condition):
		self.name = name
		self.colour = colour
		self.cond = cond

	def __repr__(self):
		return self.name

	def next_true(self, log: list[ScheduleEntry]) -> dt | DummyTime:
		return self.cond.next_true(log, self)

	def next_false(self, log: list[ScheduleEntry]) -> dt | DummyTime:
		return self.cond.next_false(log, self)

if TYPE_CHECKING:
	ScheduleEntry = tuple[Task, dt, dt]

class Never(Condition):
	def next_true(self, log, qtask) -> dt | DummyTime:
		return NEVER

	def next_false(self, log, qtask) -> dt | DummyTime:
		return NOW

FREE = Task('(free)', (0, 0, 0), Never())

class Always(Condition):
	def next_true(self, log, qtask) -> dt | DummyTime:
		return NOW

	def next_false(self, log, qtask) -> dt | DummyTime:
		return NEVER

class Before(Condition):
	def __init__(self, time: dt):
		self.time = time
	
	def next_true(self, log, qtask) -> dt | DummyTime:
		if not log:
			# print(f'  [NTRUE] Next true of before({self.time:%a %d %H:%M})@(empty) -> NOW for {qtask}')
			return NOW

		if log[-1][2] < self.time:
			# print(f'  [NTRUE] Next true of before({self.time:%a %d %H:%M})@({log[-1][2]:%a %d %H:%M}) -> NOW for {qtask}')
			return NOW
		else:
			# print(f'  [NTRUE] Next true of before({self.time:%a %d %H:%M})@({log[-1][2]:%a %d %H:%M}) -> NEVER for {qtask}')
			return NEVER

	def next_false(self, log, qtask) -> dt | DummyTime:
		if not log:
			# print(f'  [FALSE] Next false of before({self.time})@(empty) -> {self.time:%a %H:%M} for {qtask}')
			return self.time

		if log[-1][2] < self.time:
			# print(f'  [FALSE] Next false of before({self.time})@({log[-1][2]:%a %H:%M}) -> {self.time:%a %H:%M} for {qtask}')
			return self.time
		else:
			# print(f'  [FALSE] Next false of before({self.time})@({log[-1][2]:%a %H:%M}) -> NEVER for {qtask}')
			return NEVER

class Total(Condition):
	def __init__(self, duration: td):  # true if you haven't duration enough duration
		self.duration = duration

	def find_rem(self, log, qtask) -> td:
		if not log: return NOW  # should be (latest + self.duration)

		last = log[-1][2]

		qtime = self.duration

		for task, start, end in reversed(log):
			if task is not qtask: continue

			task_time = end-start
			if task_time >= qtime: return td(0)  # may cause inf loops if not taken are of

			qtime -= task_time

		return qtime

	def next_false(self, log, qtask) -> dt | DummyTime:
		if not log: return NOW  # should be (latest + self.duration)
		last = log[-1][2]

		qtime = self.find_rem(log, qtask)

		# print(f'  [FALSE] Next false of in({self.duration}) -> {last+qtime:%a %d %H:%M} for {qtask}')
		return last+qtime

	def next_true(self, log, qtask) -> dt | DummyTime:
		if not log: return NOW

		qtime = self.find_rem(log, qtask)

		if qtime > td(0):
			# There is time to spend
			# print(f'  [NTRUE] Next true of total(rem {qtime} of {self.duration}) -> NOW for {qtask}')
			return NOW
		else:
			# print(f'  [NTRUE] Next true of total(rem {qtime} of {self.duration}) -> NEVER for {qtask}')
			return NEVER

class In(Condition):
	def __init__(self, spent: td, past: td):  # true if you haven't spent enough time recently
		self.spent = spent
		self.past = past
		
	def next_false(self, log, qtask) -> dt | DummyTime:
		if not log: return NOW  # should be (latest + self.spent)

		last = log[-1][2]
		limit = last-self.past+self.spent

		qtime = self.spent

		for task, start, end in reversed(log):
			if end <= limit: break
			if task is not qtask: continue

			task_time = end-start
			if task_time >= qtime: return NOW  # may cause inf loops if not taken are of

			qtime -= task_time
			limit -= task_time

		# print(f'  [FALSE] Next false of in({self.spent}) -> {last+qtime:%a %d %H:%M} for {qtask}')
		return last+qtime

	def next_true(self, log, qtask) -> dt | DummyTime:
		if not log: return NOW

		last = log[-1][2]
		limit = last-self.past
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
		return NOW

class Repeat(Condition):
	def __init__(self, anchor: dt, interval: td, duration: td):
		self.anchor = anchor
		self.interval = interval  # start once a day, once a week etc
		self.duration = duration  # how long after starting

	def rem_next_false(self, last) -> td:
		diff = self.anchor + self.duration - last
		time_till_end = diff % self.interval

		# Prevent zero length events
		if time_till_end == td(0): return self.interval
		return time_till_end

	def next_true(self, log, qtask) -> dt | DummyTime:
		if not log:
			# print(f'  [NTRUE] Next true of repeat({self.anchor:%a %H:%M})@(empty) -> {self.anchor:%a %d %H:%M} for {qtask}')
			return self.anchor

		last = log[-1][2]
		time_till_end = self.rem_next_false(last)

		if time_till_end < self.duration:
			# print(f'  [NTRUE] repeat({self.anchor:%a %H:%M})@{last:(%a %H:%M)} -> NOW for {qtask}')
			return NOW

		# print(f'  [NTRUE] repeat({self.anchor:%a %H:%M})@{last:(%a %H:%M)} -> {last + time_till_end - self.duration:%a %d %H:%M} for {qtask}')
		return last + time_till_end - self.duration

	def next_false(self, log, qtask) -> dt | DummyTime:
		if not log:
			# print(f'  [FALSE] repeat({self.anchor:%a %H:%M}) on (empty) -> {self.anchor+seld.duration:%a %d %H:%M} for {qtask}')
			return self.anchor+seld.duration

		last = log[-1][2]
		time_till_end = self.rem_next_false(last)
		
		# print(f'  [FALSE] repeat({self.anchor:%a %H:%M}) on {last} -> {last + time_till_end:%a %d %H:%M} for {qtask}')
		return last + time_till_end

class Event(Condition):
	def __init__(self, start: dt, end: dt):
		self.start = start
		self.end = end

	def next_true(self, log, qtask) -> dt | DummyTime:
		if not log:
			# print(f'  [NTRUE] event({self.start:%a %d %H:%M} to {self.end:%a %d %H:%M})@(empty) -> {self.start:%a %d %H:%M} for {qtask}')
			return self.start

		last = log[-1][2]
		if last < self.start: out = self.start

		# self.start <= last
		elif self.end <= last:
			# print(f'  [NTRUE] event({self.start:%a %d %H:%M} to {self.end:%a %d %H:%M})@({last:%a %d %H:%M}) -> NEVER for {qtask}')
			return NEVER
		else: out = last

		# print(f'  [NTRUE] event({self.start:%a %d %H:%M} to {self.end:%a %d %H:%M})@({last:%a %d %H:%M}) -> {out:%a %d %H:%M} for {qtask}')
		return out

	def next_false(self, log, qtask) -> dt | DummyTime:
		if not log: return self.end

		last = log[-1][2]
		if self.end < last: return NOW
		else: return self.end

class Or(Condition):
	def __init__(self, *conds):
		self.conds = conds

	def next_true(self, log, qtask) -> dt | DummyTime:
		out = NEVER
		for cond in self.conds:
			cond_next = cond.next_true(log, qtask)
			if cond_next is NOW: return NOW

			if out is NEVER or cond_next < out: out = cond_next

		return out

	def next_false(self, log, qtask) -> dt | DummyTime:
		out = NOW
		for cond in self.conds:
			cond_next = cond.next_false(log, qtask)
			if cond_next is NEVER: return NEVER

			if out is NOW or cond_next > out: out = cond_next

		return out

class And(Condition):
	def __init__(self, *conds):
		self.conds = conds

	def next_true(self, log, qtask) -> dt | DummyTime:
		out = NOW
		for cond in self.conds:
			cond_next = cond.next_true(log, qtask)
			if cond_next is NEVER: return NEVER
			if cond_next is NOW: continue

			if out is NOW or cond_next > out: out = cond_next

		return out

	def next_false(self, log, qtask) -> dt | DummyTime:
		out = NEVER
		for cond in self.conds:
			cond_next = cond.next_false(log, qtask)
			if cond_next is NOW: return NOW

			if out is NEVER or cond_next < out: out = cond_next

		return out

def compute_schedule(tasks: list[Task], log: list[ScheduleEntry], latest: dt, limit: dt, *, report_time = True) -> list[ScheduleEntry]:
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

	return log[l:]

def add_one_task(tasks: nonempty[Task], log, now: dt) -> DummyTime | dt:  # return the new latest time
	best_task = tasks[0]
	best_next = best_task.next_true(log)
	best_idx = 0
	# print(f'  [BETRS] {best_next} for {best_task}')

	if best_next is not NOW:
		for i, task in enumerate(tasks):
			task_next = task.next_true(log)
			if task_next is NEVER: continue

			if task_next is NOW or task_next == now:
				best_task = task
				best_next = task_next
				best_idx = i
				# print(f'  [SHRTS] {best_next} for {task}')
				break

			elif task_next < best_next:  # type: ignore[operator]
				best_task = task
				best_next = task_next
				best_idx = i
				# print(f'  [BETRS] {best_next} for {task}')

			# else:
				# print(f'[WORSS] {task_next} for {task}')

	if best_next is NEVER:
		log.append((FREE, log[-1][2], NEVER))
		# print('  [RET]    NEVER')
		return NEVER  # no more tasks
	if best_next is NOW: best_next = now

	# print(f'  [BESTS] {best_next:%a %d %H:%M} from {best_task} ({now = : %a %d %H:%M})')

	if log and log[-1][2] < best_next:
		log.append((FREE, log[-1][2], best_next))
		# print(f'  [GAP]   {log[-1]}')

	# print(f'  [COND] ', best_task.cond.__class__.__name__)
	best_end: dt | DummyTime = best_task.next_false(log)
	if best_end is not NOW:
		# if best_end is not NEVER:
		# 	print(f'  [BETRE] {best_end:%a %H:%M} from {best_task}')

		for task in tasks[:best_idx]:
			task_next = task.next_true(log)
			if task_next is NEVER: continue
			if isinstance(task_next, DummyTime):
				# print(f'  [SHTRE] {best_end:%a %H:%M} from {task}')
				raise RuntimeError('Got a higher priority urgent task that was not assigned')

			if isinstance(best_end, DummyTime) or task_next < best_end:
				best_end = task_next
				# print(f'  [BETRE] {best_end:%a %H:%M} from {task}')
			# else:
				# print(f'[WORSE] {task_next} for {task}')

		if best_end is NOW:
			best_end = now

	else:
		best_end = now

	# print(f'  [BESTE] {best_end:%a %H:%M}')

	if TYPE_CHECKING:
		reveal_type(best_next)
		reveal_type(best_end)

	if best_end <= best_next:
		raise RuntimeError(f'{best_task} at has nonpositive duration ({best_next:%a %d %H:%M} to {best_end:%a %d %H:%M})')

	log.append((best_task, best_next, best_end))
	task, start, end = log[-1]
	# print(f'  [TASK]  {start:%a %H:%M} to {end:%a %H:%M} -> {task}')
	return best_end

def main(now, limit, log: list[ScheduleEntry] = None):
	epoch = dt.utcfromtimestamp(0)  # Thursday
	from temp_data import tasks, shd

	if log is None: log = [(shd.FREE, now, now)]

	schedule = shd.compute_schedule(tasks, log, now, limit)
	print()
	print(len(schedule), 'tasks')
	for task, start, end in schedule:
		# if task is shd.FREE: continue
		print(f'{start:%a %d %H:%M} to {end:%a %d %H:%M} ({end-start}) -> {task}')

if __name__ == '__main__':
	now = dt.now()
	now = now.replace(microsecond=0)
	main(now, now+td(2))
