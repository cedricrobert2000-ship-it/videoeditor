"""Point d'entrée commun : menu Scripts de Resolve ou ligne de commande."""

from __future__ import annotations

from typing import Optional

from . import motion, pipeline
from .config import load_settings
from .resolve_bridge import ResolveSession, get_resolve


def launch(scope: Optional[dict] = None, headless: bool = False) -> None:
    scope = scope or {}
    resolve = get_resolve(scope)
    session = ResolveSession(resolve)

    def runner(settings, log):
        return pipeline.run(session, settings, log=log)

    def motion_runner(settings, text, log):
        return motion.create_motion(session, settings, text, log=log)

    def read_subtitle():
        timeline = session.project.GetCurrentTimeline()
        return session.subtitle_at_playhead(timeline) if timeline else ""

    if headless:
        runner(load_settings(), print)
        return

    fusion = scope.get("fusion")
    bmd = scope.get("bmd")
    if fusion is None:
        try:
            fusion = resolve.Fusion()
        except Exception:
            fusion = None
    if bmd is None:
        try:
            import DaVinciResolveScript as bmd  # type: ignore
        except ImportError:
            bmd = None

    if fusion is not None and bmd is not None and getattr(fusion, "UIManager", None):
        try:
            from .ui import show_resolve_ui
            show_resolve_ui(fusion, bmd, runner, motion_runner, read_subtitle)
            return
        except Exception as exc:  # UIManager absent ou incomplet selon la version
            print(f"[ReelAI] Interface Resolve indisponible ({exc}), passage à Tkinter.")

    try:
        from .ui import show_tk_ui
        show_tk_ui(runner, motion_runner, read_subtitle)
    except Exception as exc:
        print(f"[ReelAI] Pas d'interface graphique ({exc}) : exécution avec les réglages sauvegardés.")
        runner(load_settings(), print)
