import xbmc
import xbmcgui


HOME_TILE_IDS = (1101, 1102, 1103, 1104)
HOME_TILES = {
    1101: {"label": "Fernsehen", "target": "TVGuide"},
    1102: {"label": "Mediatheken", "target": "Window(1112)"},
    1103: {"label": "Bibliothek", "target": "Videos"},
    1104: {"label": "Einstellungen", "target": "Settings"},
}
WAIT_STEPS = 20
WAIT_MS = 100
SYNC_LOOPS = 15


def _log(message: str) -> None:
    xbmc.log(f"skin.kodi4seniors focus_handler: {message}", xbmc.LOGINFO)


def _home_window() -> xbmcgui.Window:
    return xbmcgui.Window(xbmcgui.getCurrentWindowId())


def _focus_tile(window: xbmcgui.Window, control_id: int) -> bool:
    try:
        window.setFocusId(control_id)
        return True
    except RuntimeError:
        return False


def _read_focus_id(window: xbmcgui.Window) -> int:
    try:
        return window.getFocusId()
    except RuntimeError:
        return -1


def _sync_properties(window: xbmcgui.Window) -> None:
    focus_id = _read_focus_id(window)
    tile = HOME_TILES.get(focus_id, HOME_TILES[1101])
    window.setProperty("k4s.home.focus_id", str(focus_id))
    window.setProperty("k4s.home.focus_label", tile["label"])
    window.setProperty("k4s.home.focus_target", tile["target"])
    window.setProperty(
        "k4s.home.technician_locked",
        "true" if not xbmc.getCondVisibility("Skin.HasSetting(technician_mode)") else "false",
    )


def main() -> None:
    monitor = xbmc.Monitor()
    window = _home_window()

    for _ in range(WAIT_STEPS):
        if _focus_tile(window, HOME_TILE_IDS[0]):
            break
        if monitor.waitForAbort(WAIT_MS / 1000):
            return
    else:
        _log("home controls not ready; skipping focus initialization")
        return

    _sync_properties(window)

    for _ in range(SYNC_LOOPS):
        if monitor.waitForAbort(WAIT_MS / 1000):
            return
        _sync_properties(window)

    _log(
        "initialized focus on tile "
        f"{window.getProperty('k4s.home.focus_id')} "
        f"({window.getProperty('k4s.home.focus_label')})"
    )


if __name__ == "__main__":
    main()
