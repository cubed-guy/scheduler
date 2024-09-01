# Visualiser + Realtime logger for scheduler

from os import environ
environ['PYGAME_HIDE_SUPPORT_PROMPT'] = 'true'

from io import StringIO
from os.path import expanduser
from enum import Enum, auto
from temp_data import shd, tasks, now, epoch
from itertools import chain as iter_chain
from datetime import (
	datetime as dt,
	timedelta as td,
)
import logfile  # logfile encoder and decoder

import pygame
from pygame.locals import *
pygame.font.init()
font_path = expanduser('~/Assets/Product Sans Regular.ttf')
font = pygame.font.Font(font_path, 72)
stat_font = pygame.font.Font(font_path, 18)

c = type('c', (), {'__matmul__': (lambda s, x: (*x.to_bytes(3, 'big'),)), '__sub__': (lambda s, x: (x&255,)*3)})()

# CONSTANTS

bg = c-34
fg = c@0xff9088
GREEN = c@0xa0ffe0
BLACK = c-0
WHITE = c--1

SH = 30
FPS = 60
REFRESH_INTERVAL = td(seconds=1)

ZOOM_FAC = 0.88
MAX_ZOOM = td(days=30)/1280
MIN_ZOOM = td(minutes=5)/1280
ROW_HEIGHT = 75
ROW_PAD = 5
TOTAL_ROW_HEIGHT = ROW_HEIGHT+ROW_PAD

class RowSize(Enum):
	day = auto()
	week = auto()

def from_screen_space(pos):
	global zoom, scroll
	x = pos[0] * zoom + scroll[0]
	y = pos[1] - scroll[1]  # no zoom on y
	return x, y

def to_screen_space(x: td, y: float):
	global zoom, scroll
	return (x - scroll[0]) / zoom, y + scroll[1]  # no zoom on y

def from_screen_scale(delta):
	global zoom
	x = delta[0] * zoom
	y = delta[1]  # no zoom on y
	return x, y

def to_screen_scale(dx, dy):
	global zoom
	return dx / zoom, dy  # no zoom on y

def time_to_screen_space(t: dt, interval):
	global scroll, zoom, origin

	since_epoch = t-origin
	row_n, since_interval_start = divmod(since_epoch, interval)
	return to_screen_space(since_interval_start, TOTAL_ROW_HEIGHT * row_n)

def update_stat(*msg, update = True):
	# call this if you have a long loop that'll take too long
	rect = (0, h-SH, w, SH+1)
	display.fill(BLACK, rect)

	tsurf = stat_font.render(' '.join(map(str, msg)), True, WHITE)
	display.blit(tsurf, (5, h-SH))

	if update: pygame.display.update(rect)

def resize(size, flags=RESIZABLE):
	global w, h, res, display
	w, h = res = size
	display = pygame.display.set_mode(res, flags)
	update_display()

def toggle_fullscreen():
	global res, pres
	res, pres = pres, res
	resize(res, display.get_flags()^FULLSCREEN)

def update_display():
	global origin

	display.fill(bg)

	if   row_size is RowSize.day:
		interval = td(1)
	elif row_size is RowSize.week:
		interval = td(7)
	else:
		raise ValueError(f'{row_size!r} is not yet supported')

	drect = display.get_rect()

	# show timeline
	for task, start, end in iter_chain(log, scheduled):
		x_start, y_start = time_to_screen_space(start, interval)
		x_end, y_end = time_to_screen_space(end, interval)

		# print(f'{x_start:.02f} {y_start:.02f}', f'{x_end:.02f} {y_end:.02f}', curr_task, scroll, zoom)
		if y_start == y_end:
			display.fill(task.colour, drect.clip((x_start, y_start, x_end-x_start, ROW_HEIGHT)))
		else:
			display.fill(task.colour, drect.clip((x_start, y_start, (interval-scroll[0])/zoom-x_start, ROW_HEIGHT)))
			display.fill(task.colour, drect.clip((-scroll[0]/zoom, y_end, x_end+scroll[0]/zoom, ROW_HEIGHT)))

	cursor_pos = time_to_screen_space(now, interval)
	cursor_rect = pygame.Rect(cursor_pos, (1, TOTAL_ROW_HEIGHT))
	display.fill(c-0, drect.clip(cursor_rect.inflate(2, 0)))
	display.fill(c@0xffffe0, drect.clip(cursor_rect))

	# print()
	# update_stat(f'{x_start:.02f} {y_start:.02f}', f'{x_end:.02f} {y_end:.02f}', update = False)
	update_stat(ongoing_task, f'({selected_task.name!r} selected, priority: {scheduled[0][0]} till {scheduled[0][2]:%H:%M})', update = False)
	pygame.display.flip()


# Initialising variables to initial values

w, h = res = (1280, 720)
row_size = RowSize.day

origin = now.replace(hour=0, minute=0, second=0)
scroll = [td(0), -TOTAL_ROW_HEIGHT * ((now-origin)//td(1))]
zoom = td(1)/w  # one day in the screen
dragging = False
ticks = 0
y_end = None

# Assume tasks is not empty. Crash otherwise.
selected_task_id = 0
selected_task = tasks[selected_task_id]
ongoing_task = shd.FREE

with open('scheduler.log', 'rb') as f:
	log = logfile.read([shd.FREE]+tasks, f)
log.append((ongoing_task, now, now))

today = now
limit = today+td(7)
scheduled = shd.compute_schedule(tasks, log, today, limit)

resize(res)
pres = pygame.display.list_modes()[0]
# pygame.key.set_repeat(500, 50)
clock = pygame.time.Clock()
running = True
while running:
	now = dt.now()

	for event in pygame.event.get():
		if event.type == KEYDOWN:
			if   event.key == K_ESCAPE: running = False
			elif event.key == K_F11: toggle_fullscreen()
			elif event.key == K_UP:
				selected_task_id -= 1
				selected_task_id %= len(tasks)
				selected_task = tasks[selected_task_id]
			elif event.key == K_DOWN:
				selected_task_id += 1
				selected_task_id %= len(tasks)
				selected_task = tasks[selected_task_id]
			elif event.key == K_SPACE:
				log[-1] = *log[-1][:2], now
				if ongoing_task is shd.FREE:
					ongoing_task = selected_task
				else:
					ongoing_task = shd.FREE
				log.append((ongoing_task, now, now))
			elif event.key == K_s:
				update_stat('Saving log file...')
				with open('scheduler.log', 'wb') as f:
					logfile.write([shd.FREE]+tasks, log, f)

		elif event.type == VIDEORESIZE:
			resize(event.size, display.get_flags())
		elif event.type == QUIT: running = False
		elif event.type == MOUSEWHEEL:
			mods = pygame.key.get_mods()
			if mods & (KMOD_LCTRL|KMOD_RCTRL):
				# Zooms wrt object-space origin
				zoom *= ZOOM_FAC ** event.y
				zoom = min(max(zoom, MIN_ZOOM), MAX_ZOOM)
			else:
				dx, dy = from_screen_scale((event.x * 7, event.y * 7))
				scroll[0] += dx
				scroll[1] += dy
		elif event.type == MOUSEBUTTONDOWN:
			if event.button == 1:
				dragging = True
		elif event.type == MOUSEBUTTONUP:
			if event.button == 1:
				dragging = False
		elif event.type == MOUSEMOTION:
			if dragging:
				...

	# update the latest log entry
	log[-1] = (log[-1][0], log[-1][1], now)
	if (
		scheduled[0][0] is not ongoing_task and scheduled[0][1]+REFRESH_INTERVAL < now
		or scheduled[0][2] < now
	):
		# print('rescheduling', now)
		scheduled = shd.compute_schedule(tasks, log, now, limit, report_time = False)

	update_display()
	frame_time = clock.tick(FPS)
	# ticks += frame_time
