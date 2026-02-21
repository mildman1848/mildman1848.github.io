# -*- coding: utf-8 -*-
import time

import xbmc

from resources.lib import utils


class AbsPlayerMonitor(xbmc.Monitor):
    def __init__(self, api, item_id, episode_id=None, resume_time=0.0):
        super().__init__()
        self.api = api
        self.item_id = item_id
        self.episode_id = episode_id
        self.resume_time = float(max(0.0, resume_time or 0.0))
        self.player = xbmc.Player()
        self.interval = max(5, int(utils.ADDON.getSetting("progress_sync_interval") or "30"))
        self.finished_threshold = max(50, min(100, int(utils.ADDON.getSetting("mark_finished_threshold") or "97")))
        self._resume_applied = False

    def run(self):
        started = time.time()
        # Wait up to 15s for playback to start.
        while not self.abortRequested() and (time.time() - started) < 15:
            if self.player.isPlayingAudio():
                break
            self.waitForAbort(0.2)

        last_sync = 0
        while not self.abortRequested() and self.player.isPlayingAudio():
            if not self._resume_applied and self.resume_time > 0:
                try:
                    if float(self.player.getTime() or 0.0) < max(1.0, self.resume_time - 2.0):
                        self.player.seekTime(self.resume_time)
                    self._resume_applied = True
                except Exception as exc:
                    utils.log("Initial resume seek failed: %s" % exc, xbmc.LOGWARNING)
            now = time.time()
            if now - last_sync >= self.interval:
                self.sync_progress(False)
                last_sync = now
            self.waitForAbort(0.5)

        # Final sync when playback stops.
        self.sync_progress(True)

    def sync_progress(self, final):
        try:
            if not self.player.isPlayingAudio() and not final:
                return
            current_time = float(self.player.getTime() or 0.0)
            total_time = float(self.player.getTotalTime() or 0.0)
            is_finished = False
            if total_time > 0:
                is_finished = (current_time / total_time) * 100.0 >= self.finished_threshold
            self.api.patch_progress(
                item_id=self.item_id,
                episode_id=self.episode_id,
                current_time=current_time,
                duration=total_time,
                is_finished=is_finished,
            )
        except Exception as exc:
            utils.log("Progress sync failed: %s" % exc, xbmc.LOGWARNING)
