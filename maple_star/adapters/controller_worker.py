from __future__ import annotations

import multiprocessing as mp
import os
import queue
import time
from dataclasses import dataclass
from typing import Any

from .debug_logging import configure_debug_logging, log_exception

EVENT_STATUS = "status"
EVENT_ERROR = "error"
EVENT_DEVICE_ADDED = "device_added"
EVENT_DEVICE_REMOVED = "device_removed"
EVENT_BUTTON_DOWN = "button_down"
EVENT_BUTTON_UP = "button_up"
EVENT_RELEASE_ALL = "release_all"

SDL_CONTROLLER_BUTTON_A = 0
SDL_CONTROLLER_BUTTON_B = 1
SDL_CONTROLLER_BUTTON_X = 2
SDL_CONTROLLER_BUTTON_Y = 3
SDL_CONTROLLER_BUTTON_BACK = 4
SDL_CONTROLLER_BUTTON_GUIDE = 5
SDL_CONTROLLER_BUTTON_START = 6
SDL_CONTROLLER_BUTTON_LEFTSTICK = 7
SDL_CONTROLLER_BUTTON_RIGHTSTICK = 8
SDL_CONTROLLER_BUTTON_LEFTSHOULDER = 9
SDL_CONTROLLER_BUTTON_RIGHTSHOULDER = 10
SDL_CONTROLLER_BUTTON_DPAD_UP = 11
SDL_CONTROLLER_BUTTON_DPAD_DOWN = 12
SDL_CONTROLLER_BUTTON_DPAD_LEFT = 13
SDL_CONTROLLER_BUTTON_DPAD_RIGHT = 14

CONTROLLER_BUTTONS_BY_NAME = {
    "A": SDL_CONTROLLER_BUTTON_A,
    "B": SDL_CONTROLLER_BUTTON_B,
    "X": SDL_CONTROLLER_BUTTON_X,
    "Y": SDL_CONTROLLER_BUTTON_Y,
    "LB": SDL_CONTROLLER_BUTTON_LEFTSHOULDER,
    "RB": SDL_CONTROLLER_BUTTON_RIGHTSHOULDER,
    "BACK": SDL_CONTROLLER_BUTTON_BACK,
    "START": SDL_CONTROLLER_BUTTON_START,
    "HOME": SDL_CONTROLLER_BUTTON_GUIDE,
    "L3": SDL_CONTROLLER_BUTTON_LEFTSTICK,
    "R3": SDL_CONTROLLER_BUTTON_RIGHTSTICK,
    "DPAD_UP": SDL_CONTROLLER_BUTTON_DPAD_UP,
    "DPAD_DOWN": SDL_CONTROLLER_BUTTON_DPAD_DOWN,
    "DPAD_LEFT": SDL_CONTROLLER_BUTTON_DPAD_LEFT,
    "DPAD_RIGHT": SDL_CONTROLLER_BUTTON_DPAD_RIGHT,
}
BUTTON_NAMES = {button: name for name, button in CONTROLLER_BUTTONS_BY_NAME.items()}
ControllerWorkerEvent = tuple[str, int | str | None, str | None]


@dataclass
class ControllerEventWorker:
    process: mp.Process
    event_queue: mp.Queue
    stop_event: mp.Event


def button_name(button: int) -> str:
    return BUTTON_NAMES.get(button, f"BUTTON_{button}")


def start_controller_event_worker(poll_interval_seconds: float) -> ControllerEventWorker:
    context = mp.get_context("spawn")
    event_queue: mp.Queue = context.Queue(maxsize=256)
    stop_event: mp.Event = context.Event()
    process = context.Process(
        target=run_controller_event_worker,
        args=(event_queue, stop_event, poll_interval_seconds),
        name="MapleStarControllerWorker",
        daemon=True,
    )
    process.start()
    return ControllerEventWorker(process=process, event_queue=event_queue, stop_event=stop_event)


def stop_controller_event_worker(worker: ControllerEventWorker) -> None:
    worker.stop_event.set()
    worker.process.join(timeout=2.0)
    if worker.process.is_alive():
        worker.process.terminate()
        worker.process.join(timeout=2.0)
    worker.event_queue.close()
    worker.event_queue.join_thread()


def run_controller_event_worker(event_queue: mp.Queue, stop_event: mp.Event, poll_interval_seconds: float) -> None:
    configure_debug_logging()
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    try:
        import pygame
        import pygame._sdl2.controller as controller
    except Exception as exc:
        log_exception("手把監聽 worker 初始化失敗")
        _put_event(event_queue, (EVENT_ERROR, None, f"缺少 pygame-ce 或 SDL controller 初始化失敗：{exc}"))
        return

    controllers_by_id: dict[int, Any] = {}
    joysticks_by_id: dict[int, Any] = {}
    try:
        pygame.init()
        pygame.joystick.init()
        controller.init()
        controllers_by_id = _open_connected_controllers(controller, event_queue)
        if not controllers_by_id:
            joysticks_by_id = _open_connected_joysticks(pygame, event_queue)

        while not stop_event.is_set():
            for event in pygame.event.get():
                if event.type == pygame.CONTROLLERDEVICEADDED:
                    if controller.is_controller(event.device_index):
                        pad = controller.Controller(event.device_index)
                        controllers_by_id[pad.id] = pad
                        _put_event(event_queue, (EVENT_DEVICE_ADDED, int(pad.id), str(pad.name)))

                elif event.type == pygame.CONTROLLERDEVICEREMOVED:
                    controller_id = int(getattr(event, "instance_id", getattr(event, "which", -1)))
                    pad = controllers_by_id.pop(controller_id, None)
                    name = str(pad.name) if pad is not None else "unknown"
                    _close_controller(pad)
                    _put_event(event_queue, (EVENT_DEVICE_REMOVED, controller_id, name))

                elif event.type == pygame.CONTROLLERBUTTONDOWN:
                    _put_event(event_queue, (EVENT_BUTTON_DOWN, int(event.button), None))

                elif event.type == pygame.CONTROLLERBUTTONUP:
                    _put_event(event_queue, (EVENT_BUTTON_UP, int(event.button), None))

                elif not controllers_by_id and event.type == pygame.JOYDEVICEADDED:
                    pad = pygame.joystick.Joystick(event.device_index)
                    pad.init()
                    joystick_id = _joystick_instance_id(pad)
                    joysticks_by_id[joystick_id] = pad
                    _put_event(event_queue, (EVENT_DEVICE_ADDED, joystick_id, f"{pad.get_name()} (Joystick)"))

                elif not controllers_by_id and event.type == pygame.JOYDEVICEREMOVED:
                    joystick_id = int(getattr(event, "instance_id", getattr(event, "which", -1)))
                    pad = joysticks_by_id.pop(joystick_id, None)
                    name = f"{pad.get_name()} (Joystick)" if pad is not None else "unknown"
                    _close_controller(pad)
                    _put_event(event_queue, (EVENT_DEVICE_REMOVED, joystick_id, name))

                elif not controllers_by_id and event.type == pygame.JOYBUTTONDOWN:
                    _put_event(event_queue, (EVENT_BUTTON_DOWN, int(event.button), None))

                elif not controllers_by_id and event.type == pygame.JOYBUTTONUP:
                    _put_event(event_queue, (EVENT_BUTTON_UP, int(event.button), None))

            time.sleep(max(0.001, poll_interval_seconds))
    except Exception as exc:
        log_exception("手把監聽 worker 未預期錯誤")
        _put_event(event_queue, (EVENT_ERROR, None, f"手把監聽 worker 錯誤：{exc}"))
    finally:
        for pad in controllers_by_id.values():
            _close_controller(pad)
        for pad in joysticks_by_id.values():
            _close_controller(pad)
        try:
            controller.quit()
        except Exception:
            pass
        try:
            pygame.quit()
        except Exception:
            pass


def _open_connected_controllers(controller: Any, event_queue: mp.Queue) -> dict[int, Any]:
    controllers_by_id: dict[int, Any] = {}
    count = int(controller.get_count())
    _put_event(event_queue, (EVENT_STATUS, None, f"偵測到 {count} 個 SDL Controller。"))

    for index in range(count):
        if controller.is_controller(index):
            pad = controller.Controller(index)
            controllers_by_id[pad.id] = pad
            _put_event(event_queue, (EVENT_DEVICE_ADDED, int(pad.id), str(pad.name)))

    return controllers_by_id


def _open_connected_joysticks(pygame: Any, event_queue: mp.Queue) -> dict[int, Any]:
    joysticks_by_id: dict[int, Any] = {}
    count = int(pygame.joystick.get_count())
    _put_event(event_queue, (EVENT_STATUS, None, f"偵測到 0 個 SDL Controller，改用 Joystick fallback：{count} 個裝置。"))

    for index in range(count):
        pad = pygame.joystick.Joystick(index)
        pad.init()
        joystick_id = _joystick_instance_id(pad)
        joysticks_by_id[joystick_id] = pad
        _put_event(event_queue, (EVENT_DEVICE_ADDED, joystick_id, f"{pad.get_name()} (Joystick)"))

    return joysticks_by_id


def _joystick_instance_id(pad: Any) -> int:
    try:
        return int(pad.get_instance_id())
    except Exception:
        return int(pad.get_id())


def _close_controller(pad: Any) -> None:
    if pad is None:
        return
    close = getattr(pad, "quit", None)
    if close is not None:
        try:
            close()
        except Exception:
            pass


def _put_event(event_queue: mp.Queue, event: ControllerWorkerEvent) -> None:
    try:
        event_queue.put_nowait(event)
    except queue.Full:
        # A lost BUTTON_UP can leave a macro key held indefinitely.  Collapse
        # a saturated stream into an explicit reconciliation event instead.
        try:
            while True:
                event_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            event_queue.put_nowait(
                (EVENT_RELEASE_ALL, None, "手把事件佇列飽和，已安全釋放所有按鍵。")
            )
        except queue.Full:
            pass
