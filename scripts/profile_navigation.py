"""Reproducible offline navigation benchmark using a real, mapped Tk window.

Run: python scripts/profile_navigation.py --output build/navigation-before
Uses temporary player data and fake search hits; never launches a game/server.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
from pathlib import Path
import pstats
import statistics
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from src.hexlauncher.utils.settings import Settings
from src.hexlauncher.views import modrinth_view, server_view
from src.hexlauncher.widgets import AvatarWidget


def benchmark(output, rounds=12, stress=False):
    process = psutil.Process()
    report = {"switches": [], "heartbeat_gaps_ms": [], "errors": [], "stress": stress}
    profiler = cProfile.Profile()
    with tempfile.TemporaryDirectory(prefix="hex-navigation-") as directory:
        base = Path(directory)
        with (
            patch.object(main, "BASE_PATH", directory),
            patch.object(main, "MC_DIR", str(base / "game")),
            patch.object(main, "MODS_DIR", str(base / "mods")),
            patch.object(main, "Settings", lambda _: Settings(directory)),
            patch.object(modrinth_view, "BASE_PATH", directory),
            patch.object(server_view, "SERVER_DIR", str(base / "server")),
            patch.object(server_view, "JAVA_DIR", str(base / "java")),
            patch.object(main.HexLauncher, "_fetch_versions", lambda *args: None),
            patch.object(AvatarWidget, "load_avatar", lambda *args: None),
            patch.object(sys, "argv", ["profile_navigation", "--smoke-test"]),
        ):
            main.ctk.set_appearance_mode("dark")
            app = main.HexLauncher()
            app.after_cancel(app._initial_refresh_after_id)
            app.report_callback_exception = lambda *error: report["errors"].append(str(error))
            app.loader_var.set("Fabric")
            app.version_var.set("1.21.1")
            app.modrinth_view.update_filter_badge()
            app.resource_packs_view.refresh_context()
            hits = [dict(title=f"Pack {i}", author="Benchmark", project_id=str(i),
                         description="Offline search result for navigation profiling.") for i in range(20)]
            for hit in hits:
                app.modrinth_view._render_mod_card(hit, "1.21.1", "Fabric")
                app.resource_packs_view._render_card(hit, "1.21.1", app.resource_packs_view._search_generation)
            # CTk.update() performs Windows' initial deiconify. update_idletasks
            # alone leaves CTk's window withdrawn, which cannot measure paint.
            app.update()
            baseline_threads = {t.ident for t in threading.enumerate()}
            report["start"] = {"rss_mb": process.memory_info().rss / 1024**2,
                               "threads": process.num_threads(),
                               "children": [p.name() for p in process.children(recursive=True)],
                               "window_state": app.state(), "viewable": app.winfo_viewable(),
                               "geometry": app.geometry()}
            started = time.perf_counter()
            cpu_start = process.cpu_times()
            last_beat = [started]
            sequence = iter(["mods", "textures", "server", "settings", "home"] * rounds)

            if stress:
                # Deliver two search responses during navigation, with real card
                # widgets and bounded rendering but no remote API or downloads.
                app.modrinth_view.client.search_mods = lambda *args, **kwargs: hits
                app.resource_packs_view.client.search_mods = lambda *args, **kwargs: hits
                app.modrinth_view.search_var.set("benchmark")
                app.after(300, app.modrinth_view.do_search)
                app.after(350, app.resource_packs_view.do_search)

            def heartbeat():
                now = time.perf_counter()
                report["heartbeat_gaps_ms"].append((now - last_beat[0]) * 1000)
                last_beat[0] = now
                app.after(10, heartbeat)

            def step():
                name = next(sequence, None)
                if name is None:
                    finish()
                    return
                before = time.perf_counter()
                app.nav_tabs[name].invoke()
                handler_ms = (time.perf_counter() - before) * 1000

                def painted():
                    view = app.views[name]
                    hit = app.winfo_containing(view.winfo_rootx() + 10, view.winfo_rooty() + 10)
                    if hit is None or not (str(hit) == str(view) or str(hit).startswith(str(view) + ".")):
                        report["errors"].append(f"Wrong page on top after {name}: {hit}")
                    report["switches"].append({"view": name, "handler_ms": handler_ms,
                                               "idle_ms": (time.perf_counter() - before) * 1000})
                    app.after(25, step)

                app.after_idle(painted)

            def finish():
                # Simulate completed icon/progress callbacks, separately from tab changes.
                for _ in range(40):
                    app.queue.put(lambda: app.bottom_bar.progress_bar.set(0.5))
                app.after(200, complete)

            def complete():
                profiler.disable()
                cpu = process.cpu_times()
                report["elapsed_s"] = time.perf_counter() - started
                report["cpu_s"] = cpu.user + cpu.system - cpu_start.user - cpu_start.system
                report["end"] = {"rss_mb": process.memory_info().rss / 1024**2,
                                 "threads": process.num_threads(),
                                 "children": [p.name() for p in process.children(recursive=True)],
                                 "new_python_threads": [t.name for t in threading.enumerate()
                                                        if t.ident not in baseline_threads],
                                 "pending_worker_callbacks": app.queue.qsize(),
                                 "mod_result_containers": len(app.modrinth_view._results_viewport.winfo_children()),
                                 "texture_result_containers": len(app.resource_packs_view._results_viewport.winfo_children()),
                                 "mod_cards": len(app.modrinth_view.results_scroll.winfo_children()),
                                 "texture_cards": len(app.resource_packs_view.results_scroll.winfo_children())}
                app.destroy()

            app.after(10, heartbeat)
            app.after(100, step)
            profiler.enable()
            main.tkinter.Tk.mainloop(app)
    for field in ("handler_ms", "idle_ms"):
        values = sorted(item[field] for item in report["switches"])
        report[field] = {"median": statistics.median(values), "p95": values[int(len(values) * .95)],
                         "max": max(values)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    stream = io.StringIO()
    pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(45)
    output.with_suffix(".txt").write_text(stream.getvalue(), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"switches", "heartbeat_gaps_ms"}}, indent=2))
    print("Maximum heartbeat gap (ms):", max(report["heartbeat_gaps_ms"]))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/navigation-profile"))
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--stress", action="store_true", help="Render search responses during navigation")
    options = parser.parse_args()
    if options.rounds < 1:
        parser.error("--rounds must be positive")
    benchmark(options.output, options.rounds, options.stress)
