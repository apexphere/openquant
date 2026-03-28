import threading
import time
from typing import List
from collections import deque
import multiprocessing as mp
import traceback
from openquant.services.redis import sync_publish, sync_redis
from openquant.services.failure import terminate_session
import openquant.helpers as jh
from openquant.services.env import ENV_VALUES
import os
import signal

# set multiprocessing process type to spawn
mp.set_start_method('spawn', force=True)


class Process(mp.Process):
    def __init__(self, *args, **kwargs):
        mp.Process.__init__(self, *args, **kwargs)

    def run(self):
        try:
            mp.Process.run(self)
        except Exception as e:
            if type(e).__name__ == 'Termination':
                sync_publish('termination', {})
                jh.terminate_app()
            else:
                sync_publish(
                    'exception',
                    {
                        'error': f'{type(e).__name__}: {e}',
                        'traceback': str(traceback.format_exc()),
                    },
                )

                print('Unhandled exception in the process:')
                print(traceback.format_exc())

                terminate_session()


class ProcessManager:
    """Manages background processes with a task queue.

    Only one task runs at a time. Additional tasks are queued and
    started automatically when the current task finishes. This prevents
    concurrent optimizations/backtests from competing for CPU/memory.
    """

    def __init__(self):
        self._workers: List[Process] = []
        self._pid_to_client_id_map = {}
        self.client_id_to_pid_to_map = {}
        self._queue: deque = deque()  # pending tasks
        self._queue_lock = threading.Lock()
        try:
            port = ENV_VALUES.get('APP_PORT', '9000')
        except:
            port = '9000'

        self._active_workers_key = f"{port}|active-processes"
        self._cleanup_thread = threading.Thread(target=self._cleanup_finished_workers, daemon=True)
        self._cleanup_thread.start()

    def _reset(self):
        self._workers = []
        self._pid_to_client_id_map = {}
        self.client_id_to_pid_to_map = {}
        with self._queue_lock:
            self._queue.clear()
        # clear all process status
        sync_redis.delete(self._active_workers_key)

    @staticmethod
    def _prefixed_pid(pid):
        return f"{ENV_VALUES['APP_PORT']}|{pid}"

    @staticmethod
    def _prefixed_client_id(client_id):
        return f"{ENV_VALUES['APP_PORT']}|{client_id}"

    def _add_process(self, client_id):
        sync_redis.sadd(self._active_workers_key, client_id)

    def _has_active_worker(self) -> bool:
        """Check if any worker is currently running."""
        return any(w.is_alive() for w in self._workers)

    def _start_task(self, function, args):
        """Start a task immediately as a child process."""
        client_id = args[0]
        w = Process(target=function, args=args)
        self._workers.append(w)
        w.start()

        self._pid_to_client_id_map[self._prefixed_pid(w.pid)] = self._prefixed_client_id(client_id)
        self.client_id_to_pid_to_map[self._prefixed_client_id(client_id)] = self._prefixed_pid(w.pid)
        self._add_process(client_id)

    def add_task(self, function, *args):
        """Add a task. Starts immediately if no task is running, otherwise queues it."""
        with self._queue_lock:
            if self._has_active_worker():
                self._queue.append((function, args))
                jh.debug(f'Task queued (queue size: {len(self._queue)}). Will start when current task finishes.')
            else:
                self._start_task(function, args)

    def _start_next_queued(self):
        """Start the next queued task if any."""
        with self._queue_lock:
            if self._queue and not self._has_active_worker():
                function, args = self._queue.popleft()
                remaining = len(self._queue)
                jh.debug(f'Starting queued task ({remaining} remaining in queue)')
                self._start_task(function, args)

    def get_client_id(self, pid):
        try:
            client_id: str = self._pid_to_client_id_map[self._prefixed_pid(pid)]
        except KeyError:
            return None
        return jh.string_after_character(client_id, '|')

    def get_pid(self, client_id):
        return self.client_id_to_pid_to_map[self._prefixed_client_id(client_id)]

    def cancel_process(self, client_id):
        sync_redis.srem(self._active_workers_key, client_id)

    def flush(self):
        for w in self._workers:
            try:
                # Try terminate first
                w.terminate()
                # Give it a moment to terminate gracefully
                w.join(timeout=3)

                # If still alive, wait a brief moment then force kill
                if w.is_alive():
                    time.sleep(0.5)  # Give terminate a chance to complete
                    os.kill(w.pid, signal.SIGKILL)

                w.close()
            except Exception as e:
                jh.debug(f"Error while terminating process: {str(e)}")

        self._reset()

    def _cleanup_finished_workers(self):
        while True:
            try:
                cleaned = False
                for w in self._workers[:]:  # Create a copy of the list to avoid modification during iteration
                    if not w.is_alive():
                        try:
                            # Get the client_id for this worker before removing it
                            client_id = self.get_client_id(w.pid)

                            w.join(timeout=1)
                            w.close()
                            self._workers.remove(w)
                            cleaned = True

                            # Remove from Redis active workers set
                            if client_id:
                                sync_redis.srem(self._active_workers_key, client_id)
                                jh.debug(f"Removed finished worker {client_id} from active workers")
                        except Exception as e:
                            jh.debug(f"Error during worker cleanup: {str(e)}")

                # If a worker finished, try starting the next queued task
                if cleaned:
                    self._start_next_queued()
            except Exception as e:
                jh.debug(f"Error in cleanup thread: {str(e)}")
            time.sleep(5)


process_manager = ProcessManager()
