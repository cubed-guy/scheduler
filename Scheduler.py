from abc import ABC, abstractmethod
from datetime import (
	datetime as dt,
	timedelta as td,
)

ScheduleEntry = tuple[Task, dt, dt]
NOW = type('NOW', (), {'__repr__': lambda s: "(now)"})()
NEVER = type('NEVER', (), {'__repr__': lambda s: "(never)"})()

class Condition(ABC):
	@abstractmethod
	def next_true(self, log: list[ScheduleEntry], qtask: Task) -> Union[dt, NOW, NEVER]:  ...

	@abstractmethod
	def next_false(self, log: list[ScheduleEntry], qtask: Task) -> Union[dt, NOW, NEVER]:  ...

class Before(Condition):
	def __init__(self, time: dt):
		self.time = time
	
	def next_true(self, log, qtask):
		if not log: return NOW
		return log[-1][2]

	def next_false(self, log, qtask):
		if not log: return self.time

		if log[-1][2] < self.time:
			return self.time
		else:
			return NEVER

class In(Condition):
	def __init__(self, spent: td, past: td):  # true if you haven't spent enough time recently
		self.spent = spent
		self.past = past
		
	def find_spent(self, log: 'nonempty', qtask: Task) -> td:
		last = log[-1][2]
		limit = last-self.past

		spent = td(0)

		for task, start, end in reversed(log):
			if end < limit: break

			if task is not qtask: continue

			if start < limit: start = limit
			spent += end-start

		return spent

	def next_false(self, log, qtask):
		if not log: return NOW  # should be (latest + self.spent)

		last = log[-1][2]
		log_spent = self.find_spent(log, qtask)
		if log_spent > self.spent: return NOW
		return self.spent-log_spent

	def next_true(self, log, qtask):
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
				return end-to_spend

		return NOW

class Repeat(Condition):
	def __init__(self, anchor: dt, interval: td, duration: td):
		self.anchor = anchor
		self.interval = interval  # start once a day, once a week etc
		self.duration = duration  # how long after starting

	def next_true(self, log, qtask):
		if not log: return self.anchor

		last = log[-1][2]
		diff = last - self.anchor
		offset = diff % interval
		return last + offset

	def next_false(self, log, qtask):
		if not log: return self.anchor+self.duration

		if log[-1][0] is qtask:
			return log[-1][1] + self.duration
		else:
			return self.next_true(log, qtask) + self.duration

class Event(Condition):
	def __init__(self, start: dt, end: dt):
		self.start = start
		self.end = end

	def next_true(self, log, qtask):
		if not log: return self.start

		last = log[-1][2]
		if last > self.start: return last
		elif self.end < last: return NEVER
		else: return self.start

	def next_false(self, log, qtask):
		if not log: return self.end

		last = log[-1][2]
		if self.end < last: return NOW
		else: return self.end

class Or(Condition):
	def __init__(self, *conds):
		self.conds = conds

	def next_true(self, log, qtask):
		out = NEVER
		for cond in self.conds:
			cond_next = cond.next_true(log, qtask)
			if cond_next is NOW: return NOW

			if out is NEVER or cond_next < out: out = cond_next

		return out

	def next_false(self, log, qtask):
		out = NOW
		for cond in self.conds:
			cond_next = cond.next_false(log, qtask)
			if cond_next is NEVER: return NEVER

			if out is NOW or cond_next > out: out = cond_next

		return out

class And(Condition):
	def __init__(self, *conds):
		self.conds = conds

	def next_true(self, log, qtask):
		out = NOW
		for cond in self.conds:
			cond_next = cond.next_true(log, qtask)
			if cond_next is NEVER: return NEVER

			if out is NOW or cond_next > out: out = cond_next

		return out

	def next_false(self, log, qtask):
		out = NEVER
		for cond in self.conds:
			cond_next = cond.next_false(log, qtask)
			if cond_next is NOW: return NOW

			if out is NEVER or cond_next < out: out = cond_next

		return out

class Task:
	def __init__(self, item, colour, condition: Condition):
		self.item = item
		self.colour = colour
		self.condition = condition

def compute_schedule_now(tasks: list[Task], log: list[ScheduleEntry], limit: dt) -> list[ScheduleEntry]:
	if not tasks: return

	log = log.copy()  # We will modify this. Don't want the caller to get a modified log
	latest = dt.latest()

	perf_start = perf_counter()

	if not log: latest = add_one_task(tasks, log, latest)
	while log[-1][2] < limit:
		latest = add_one_task(tasks, log, latest)
		if latest is NEVER: log[-1][2] = limit; break

	perf_end = perf_counter()
	print(f'Scheduling took {perf_end-perf_start:02f}s')

def add_one_task(tasks: 'nonempty', log, now: dt) -> dt:  # return the new latest time
	best_task = tasks[0]
	best_next = best_task.next_true()
	best_idx = 0
	for i, task in enumerate(tasks):
		task_next = task.next_true(log)
		if task_next is NEVER: continue

		if task_next is NOW:
			best_task = task
			best_next = task_next
			best_idx = i
			break

		if task_next < best_next:
			best_task = task
			best_next = task_next
			best_idx = i

	if best_next is NEVER: return  # no more tasks
	if best_next is NOW: best_next = now

	log.append((FREE, log[-1][2], best_next))

	best_end = best_task.next_false(log)
	if best_end is not NOW:
		for task in tasks[:best_idx]:
			task_next = task.next_true(log)
			if task_next is NEVER: continue
			if task_next is NOW:
				raise RuntimeError('Got a higher priority urgent task that was not assigned')

			if best_end is NEVER or task_next < best_end: best_end = task_next

	log.append((best_task, best_next, best_end))
	return best_end
