"""Fenêtre ReelAI : interface native Resolve (UIManager), sinon Tkinter."""

from __future__ import annotations

import traceback
from typing import Callable

from .config import Settings, load_settings, save_settings
from .motion import STYLES

LANGUAGES = [("fr", "Français"), ("en", "English"), ("es", "Español"), ("de", "Deutsch"),
             ("it", "Italiano"), ("pt", "Português"), ("", "Auto")]
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]


def _run_safely(settings: Settings, runner: Callable[[Settings, Callable], list], log: Callable) -> str:
    save_settings(settings)
    try:
        results = runner(settings, log)
    except Exception as exc:  # affiché dans la fenêtre plutôt qu'un crash silencieux
        traceback.print_exc()
        return f"Erreur : {exc}"
    lines = [f"✔ {len(results)} reel(s) créés :"]
    for r in results:
        lines.append(f"• {r.timeline_name} ({r.plan.duration:.0f} s)")
        lines += [f"  ⚠ {w}" for w in r.warnings]
    return "\n".join(lines)


def _run_motion(settings: Settings, motion_runner, text: str, log: Callable) -> str:
    save_settings(settings)
    try:
        result = motion_runner(settings, text, log)
    except Exception as exc:
        traceback.print_exc()
        return f"Erreur : {exc}"
    return f"✔ Motion « {result.brief.concept} » ajouté ({result.file_path})"


# --------------------------------------------------------------- Resolve UI
def show_resolve_ui(fusion, bmd, runner, motion_runner=None, read_subtitle=None) -> None:
    ui = fusion.UIManager
    disp = bmd.UIDispatcher(ui)
    s = load_settings()

    def row(label, widget):
        return ui.HGroup({"Weight": 0}, [ui.Label({"Text": label, "MinimumSize": [170, 0], "Weight": 0}), widget])

    win = disp.AddWindow(
        {"ID": "ReelAIWin", "WindowTitle": "ReelAI - Reels automatiques par IA", "Geometry": [200, 120, 560, 720]},
        ui.VGroup({"Spacing": 6}, [
            ui.Label({"Text": "<h2>ReelAI</h2>Sélectionne une vidéo dans le Media Pool puis clique sur Générer.",
                      "Weight": 0, "WordWrap": True}),
            row("Clé API Anthropic", ui.LineEdit({"ID": "ApiKey", "Text": s.api_key, "EchoMode": "Password",
                                                    "PlaceholderText": "sk-ant-... (ou variable ANTHROPIC_API_KEY)"})),
            row("Nombre de reels", ui.SpinBox({"ID": "Count", "Minimum": 1, "Maximum": 10, "Value": s.reel_count})),
            row("Durée visée (s)", ui.SpinBox({"ID": "Target", "Minimum": 10, "Maximum": 180, "Value": int(s.target_duration)})),
            row("Durée min / max (s)", ui.HGroup([
                ui.SpinBox({"ID": "Min", "Minimum": 5, "Maximum": 180, "Value": int(s.min_duration)}),
                ui.SpinBox({"ID": "Max", "Minimum": 10, "Maximum": 600, "Value": int(s.max_duration)})])),
            row("Langue de la vidéo", ui.ComboBox({"ID": "Lang"})),
            row("Précision transcription", ui.ComboBox({"ID": "Whisper"})),
            ui.Label({"Text": "Consignes pour l'IA (facultatif) :", "Weight": 0}),
            ui.TextEdit({"ID": "Prompt", "PlainText": s.instructions, "Weight": 1,
                         "PlaceholderText": "Ex : garde les conseils concrets, ton motivant, cible entrepreneurs"}),
            ui.CheckBox({"ID": "Silences", "Text": "Couper les blancs", "Checked": s.remove_silences, "Weight": 0}),
            ui.CheckBox({"ID": "Fillers", "Text": "Couper les « euh », « hum »...", "Checked": s.remove_fillers, "Weight": 0}),
            ui.CheckBox({"ID": "Vertical", "Text": "Format vertical 9:16 (1080x1920)", "Checked": s.vertical, "Weight": 0}),
            ui.CheckBox({"ID": "Subs", "Text": "Sous-titres automatiques", "Checked": s.subtitles, "Weight": 0}),
            ui.CheckBox({"ID": "Upper", "Text": "Sous-titres en MAJUSCULES", "Checked": s.subtitle_uppercase, "Weight": 0}),
            ui.CheckBox({"ID": "Render", "Text": "Exporter en MP4 automatiquement", "Checked": s.render, "Weight": 0}),
            ui.HGroup({"Weight": 0}, [
                ui.Button({"ID": "Go", "Text": "🎬 Générer les reels"}),
                ui.Button({"ID": "Close", "Text": "Fermer"})]),
            ui.Label({"Text": "<hr><b>✨ Motion design (Higgsfield)</b> : place la tête de lecture sur "
                              "la timeline du reel, choisis le texte, puis crée le motion.",
                      "Weight": 0, "WordWrap": True}),
            row("Clé Higgsfield", ui.LineEdit({"ID": "HfKey", "Text": s.higgsfield_key, "EchoMode": "Password",
                                                "PlaceholderText": "key-id:key-secret"})),
            row("Texte du motion", ui.HGroup([
                ui.LineEdit({"ID": "MotionText", "PlaceholderText": "Ex : 3 erreurs qui tuent ta croissance"}),
                ui.Button({"ID": "ReadSub", "Text": "↓ Sous-titre", "Weight": 0})])),
            row("Style", ui.ComboBox({"ID": "MotionStyle"})),
            row("Durée (s)", ui.SpinBox({"ID": "MotionDur", "Minimum": 3, "Maximum": 10, "Value": int(s.motion_duration)})),
            ui.CheckBox({"ID": "MotionOverlay", "Text": "Texte net ajouté par Resolve (recommandé, typo parfaite)",
                         "Checked": s.motion_text_overlay, "Weight": 0}),
            ui.Button({"ID": "Motion", "Text": "✨ Créer le motion à la tête de lecture", "Weight": 0}),
            ui.TextEdit({"ID": "Status", "ReadOnly": True, "Weight": 1, "PlainText": "Prêt."}),
        ]),
    )
    it = win.GetItems()
    it["Lang"].AddItems([name for _, name in LANGUAGES])
    codes = [c for c, _ in LANGUAGES]
    it["Lang"].CurrentIndex = codes.index(s.language) if s.language in codes else 0
    it["Whisper"].AddItems(WHISPER_MODELS)
    it["Whisper"].CurrentIndex = WHISPER_MODELS.index(s.whisper_model) if s.whisper_model in WHISPER_MODELS else 2

    styles = list(STYLES)
    it["MotionStyle"].AddItems(styles)
    it["MotionStyle"].CurrentIndex = styles.index(s.motion_style) if s.motion_style in styles else 0

    def log(msg):
        print(f"[ReelAI] {msg}")
        it["Status"].Append(msg)

    def on_read_sub(ev):
        text = read_subtitle() if read_subtitle else ""
        if text:
            it["MotionText"].Text = text
        else:
            log("Aucun sous-titre sous la tête de lecture.")

    def on_motion(ev):
        if motion_runner is None:
            return
        s.api_key = it["ApiKey"].Text.strip()
        s.higgsfield_key = it["HfKey"].Text.strip()
        s.motion_style = styles[int(it["MotionStyle"].CurrentIndex)]
        s.motion_duration = int(it["MotionDur"].Value)
        s.motion_text_overlay = bool(it["MotionOverlay"].Checked)
        it["Motion"].Enabled = False
        it["Status"].PlainText = "Création du motion... (Resolve peut sembler figé quelques minutes)"
        log(_run_motion(s, motion_runner, it["MotionText"].Text, log))
        it["Motion"].Enabled = True

    def on_go(ev):
        s.api_key = it["ApiKey"].Text.strip()
        s.reel_count = int(it["Count"].Value)
        s.target_duration = float(it["Target"].Value)
        s.min_duration = float(it["Min"].Value)
        s.max_duration = float(max(it["Max"].Value, it["Min"].Value))
        s.language = codes[int(it["Lang"].CurrentIndex)]
        s.whisper_model = WHISPER_MODELS[int(it["Whisper"].CurrentIndex)]
        s.instructions = it["Prompt"].PlainText
        s.remove_silences = bool(it["Silences"].Checked)
        s.remove_fillers = bool(it["Fillers"].Checked)
        s.vertical = bool(it["Vertical"].Checked)
        s.subtitles = bool(it["Subs"].Checked)
        s.subtitle_uppercase = bool(it["Upper"].Checked)
        s.render = bool(it["Render"].Checked)
        it["Go"].Enabled = False
        it["Status"].PlainText = "Traitement en cours... (Resolve peut sembler figé quelques minutes)"
        log(_run_safely(s, runner, log))
        it["Go"].Enabled = True

    win.On.Go.Clicked = on_go
    win.On.Motion.Clicked = on_motion
    win.On.ReadSub.Clicked = on_read_sub
    win.On.Close.Clicked = lambda ev: disp.ExitLoop()
    win.On.ReelAIWin.Close = lambda ev: disp.ExitLoop()
    win.Show()
    disp.RunLoop()
    win.Hide()


# ---------------------------------------------------------------- Tkinter
def show_tk_ui(runner, motion_runner=None, read_subtitle=None) -> None:
    import tkinter as tk
    from tkinter import ttk

    s = load_settings()
    root = tk.Tk()
    root.title("ReelAI - Reels automatiques par IA")
    frm = ttk.Frame(root, padding=12)
    frm.grid(sticky="nsew")

    v = {
        "api_key": tk.StringVar(value=s.api_key),
        "reel_count": tk.IntVar(value=s.reel_count),
        "target_duration": tk.IntVar(value=int(s.target_duration)),
        "language": tk.StringVar(value=s.language),
        "whisper_model": tk.StringVar(value=s.whisper_model),
        "remove_silences": tk.BooleanVar(value=s.remove_silences),
        "remove_fillers": tk.BooleanVar(value=s.remove_fillers),
        "vertical": tk.BooleanVar(value=s.vertical),
        "subtitles": tk.BooleanVar(value=s.subtitles),
        "render": tk.BooleanVar(value=s.render),
    }
    r = 0
    for label, key, widget in [
        ("Clé API Anthropic", "api_key", lambda var: ttk.Entry(frm, textvariable=var, show="•", width=40)),
        ("Nombre de reels", "reel_count", lambda var: ttk.Spinbox(frm, from_=1, to=10, textvariable=var)),
        ("Durée visée (s)", "target_duration", lambda var: ttk.Spinbox(frm, from_=10, to=180, textvariable=var)),
        ("Langue (fr, en... vide = auto)", "language", lambda var: ttk.Entry(frm, textvariable=var)),
        ("Modèle Whisper", "whisper_model", lambda var: ttk.Combobox(frm, values=WHISPER_MODELS, textvariable=var)),
    ]:
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w")
        widget(v[key]).grid(row=r, column=1, sticky="ew")
        r += 1
    ttk.Label(frm, text="Consignes pour l'IA").grid(row=r, column=0, sticky="nw")
    prompt = tk.Text(frm, height=4, width=40)
    prompt.insert("1.0", s.instructions)
    prompt.grid(row=r, column=1)
    r += 1
    for text, key in [("Couper les blancs", "remove_silences"), ("Couper les « euh »", "remove_fillers"),
                      ("Format vertical 9:16", "vertical"), ("Sous-titres", "subtitles"),
                      ("Exporter en MP4", "render")]:
        ttk.Checkbutton(frm, text=text, variable=v[key]).grid(row=r, column=1, sticky="w")
        r += 1
    status = tk.Text(frm, height=10, width=60)
    status.grid(row=r + 1, column=0, columnspan=2, pady=6)

    def log(msg):
        print(f"[ReelAI] {msg}")
        status.insert("end", msg + "\n")
        status.see("end")
        root.update()

    def go():
        for key, var in v.items():
            setattr(s, key, var.get())
        s.target_duration = float(s.target_duration)
        s.instructions = prompt.get("1.0", "end").strip()
        log(_run_safely(s, runner, log))

    ttk.Button(frm, text="Générer les reels", command=go).grid(row=r, column=0, columnspan=2, pady=6)

    # Motion design
    m = r + 2
    ttk.Separator(frm).grid(row=m, column=0, columnspan=2, sticky="ew", pady=6)
    hf_key = tk.StringVar(value=s.higgsfield_key)
    motion_text = tk.StringVar()
    style = tk.StringVar(value=s.motion_style)
    overlay = tk.BooleanVar(value=s.motion_text_overlay)
    for i, (label, widget) in enumerate([
        ("Clé Higgsfield", ttk.Entry(frm, textvariable=hf_key, show="•", width=40)),
        ("Texte du motion", ttk.Entry(frm, textvariable=motion_text, width=40)),
        ("Style", ttk.Combobox(frm, values=list(STYLES), textvariable=style)),
    ], start=m + 1):
        ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w")
        widget.grid(row=i, column=1, sticky="ew")
    ttk.Checkbutton(frm, text="Texte net ajouté par Resolve", variable=overlay).grid(row=m + 4, column=1, sticky="w")

    def read_sub():
        text = read_subtitle() if read_subtitle else ""
        if text:
            motion_text.set(text)

    def motion():
        s.api_key = v["api_key"].get()
        s.higgsfield_key, s.motion_style, s.motion_text_overlay = hf_key.get(), style.get(), overlay.get()
        log(_run_motion(s, motion_runner, motion_text.get(), log))

    ttk.Button(frm, text="↓ Sous-titre à la tête de lecture", command=read_sub).grid(row=m + 5, column=0, pady=4)
    ttk.Button(frm, text="✨ Créer le motion", command=motion).grid(row=m + 5, column=1, pady=4)
    status.grid(row=m + 6, column=0, columnspan=2, pady=6)
    root.mainloop()
