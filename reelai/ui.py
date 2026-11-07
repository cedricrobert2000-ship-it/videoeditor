"""Fenêtre ReelAI : interface native Resolve (UIManager), sinon Tkinter."""

from __future__ import annotations

import traceback
from typing import Callable

from .config import Settings, load_settings, save_settings
from .motion import STYLES
from .montage_ai import LOOKS

LANGUAGES = [("fr", "Français"), ("en", "English"), ("es", "Español"), ("de", "Deutsch"),
             ("it", "Italiano"), ("pt", "Português"), ("", "Auto")]
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
SOURCES = [("media_pool", "Tout le Media Pool (montage de plans)"),
           ("selected", "Clip sélectionné (vidéo parlée)")]
PACES = ["Lent", "Moyen", "Rapide"]
NO_MUSIC = "— Pas de musique —"
TEXT_ANIMATIONS = [("reelai", "ReelAI : typo animée (rapide, gratuit, dès le montage)"),
                   ("higgsfield", "Higgsfield : plan réanimé par l'IA (après le montage)")]
AUTO_MUSIC = "Automatique (1re musique du Media Pool)"
LOOK_CHOICES = ["Auto"] + LOOKS


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
def show_resolve_ui(fusion, bmd, runner, motion_runner=None, read_subtitle=None, music_names=(),
                    selected_music=None, texts_runner=None) -> None:
    ui = fusion.UIManager
    disp = bmd.UIDispatcher(ui)
    s = load_settings()

    def row(label, widget):
        return ui.HGroup({"Weight": 0}, [ui.Label({"Text": label, "MinimumSize": [170, 0], "Weight": 0}), widget])

    left = ui.VGroup({"Spacing": 5}, [
        ui.Label({"Text": "<h3>🎬 Reels automatiques</h3>", "Weight": 0}),
        row("Source", ui.ComboBox({"ID": "Source"})),
        row("Musique", ui.ComboBox({"ID": "Music"})),
        ui.HGroup({"Weight": 0}, [ui.Label({"Text": "", "MinimumSize": [170, 0], "Weight": 0}),
                                  ui.Button({"ID": "PickMusic", "Text": "🎵 Prendre la musique sélectionnée dans le Media Pool"})]),
        row("Rythme du montage", ui.ComboBox({"ID": "Pace"})),
        row("Look (étalonnage)", ui.ComboBox({"ID": "Look"})),
        ui.CheckBox({"ID": "Texts", "Text": "Textes sur les plans (accroche, message, appel à l'action)",
                     "Checked": s.montage_texts, "Weight": 0}),
        row("Animation des textes", ui.ComboBox({"ID": "TextAnim"})),
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
        ui.TextEdit({"ID": "Prompt", "PlainText": s.instructions, "Weight": 1, "MinimumSize": [0, 50],
                     "PlaceholderText": "Ex : garde les conseils concrets, ton motivant, cible entrepreneurs"}),
        ui.HGroup({"Weight": 0}, [
            ui.VGroup([
                ui.CheckBox({"ID": "Silences", "Text": "Couper les blancs", "Checked": s.remove_silences}),
                ui.CheckBox({"ID": "Fillers", "Text": "Couper les « euh »", "Checked": s.remove_fillers}),
                ui.CheckBox({"ID": "Vertical", "Text": "Vertical 9:16", "Checked": s.vertical})]),
            ui.VGroup([
                ui.CheckBox({"ID": "Subs", "Text": "Sous-titres", "Checked": s.subtitles}),
                ui.CheckBox({"ID": "Upper", "Text": "Sous-titres MAJUSCULES", "Checked": s.subtitle_uppercase}),
                ui.CheckBox({"ID": "Render", "Text": "Exporter en MP4", "Checked": s.render})])]),
        ui.Button({"ID": "Go", "Text": "🎬 Générer les reels", "Weight": 0, "MinimumSize": [0, 34]}),
    ])
    right = ui.VGroup({"Spacing": 5}, [
        ui.Label({"Text": "<h3>✍️ Textes après le montage</h3>Ouvre la timeline d'un reel puis ajoute les "
                          "textes proposés par l'IA.", "Weight": 0, "WordWrap": True}),
        ui.HGroup({"Weight": 0}, [
            ui.Button({"ID": "AddTexts", "Text": "✍️ Ajouter les textes (ReelAI)"}),
            ui.Button({"ID": "AddTextsHF", "Text": "✨ Animer les textes avec Higgsfield"})]),
        ui.Label({"Text": "<h3>✨ Motion design (Higgsfield)</h3>Ouvre la timeline d'un reel, place la tête de "
                          "lecture, choisis le texte puis crée le motion.", "Weight": 0, "WordWrap": True}),
        row("Clé Higgsfield", ui.LineEdit({"ID": "HfKey", "Text": s.higgsfield_key, "EchoMode": "Password",
                                            "PlaceholderText": "key-id:key-secret"})),
        row("Texte du motion", ui.LineEdit({"ID": "MotionText", "PlaceholderText": "Ex : Ta coupe, ta signature"})),
        ui.HGroup({"Weight": 0}, [ui.Label({"Text": "", "MinimumSize": [170, 0], "Weight": 0}),
                                  ui.Button({"ID": "ReadSub", "Text": "↓ Reprendre le sous-titre sous la tête de lecture"})]),
        row("Style", ui.ComboBox({"ID": "MotionStyle"})),
        row("Durée (s)", ui.SpinBox({"ID": "MotionDur", "Minimum": 3, "Maximum": 10, "Value": int(s.motion_duration)})),
        ui.CheckBox({"ID": "MotionOverlay", "Text": "Texte net ajouté par Resolve (recommandé)",
                     "Checked": s.motion_text_overlay, "Weight": 0}),
        ui.Button({"ID": "Motion", "Text": "✨ Créer le motion", "Weight": 0, "MinimumSize": [0, 34]}),
        ui.Label({"Text": "<b>Messages :</b>", "Weight": 0}),
        ui.TextEdit({"ID": "Status", "ReadOnly": True, "Weight": 1, "MinimumSize": [0, 120], "PlainText": "Prêt."}),
        ui.Button({"ID": "Close", "Text": "Fermer", "Weight": 0}),
    ])
    win = disp.AddWindow(
        {"ID": "ReelAIWin", "WindowTitle": "ReelAI - Reels automatiques par IA", "Geometry": [80, 50, 1080, 720]},
        ui.HGroup({"Spacing": 16}, [left, right]),
    )
    it = win.GetItems()
    it["Lang"].AddItems([name for _, name in LANGUAGES])
    codes = [c for c, _ in LANGUAGES]
    it["Lang"].CurrentIndex = codes.index(s.language) if s.language in codes else 0
    it["Whisper"].AddItems(WHISPER_MODELS)
    it["Whisper"].CurrentIndex = WHISPER_MODELS.index(s.whisper_model) if s.whisper_model in WHISPER_MODELS else 2

    it["Source"].AddItems([label for _, label in SOURCES])
    src_codes = [c for c, _ in SOURCES]
    it["Source"].CurrentIndex = src_codes.index(s.source_mode) if s.source_mode in src_codes else 0
    musics = [AUTO_MUSIC, NO_MUSIC] + list(music_names)
    it["Music"].AddItems(musics)
    if s.music_name == "-":
        it["Music"].CurrentIndex = 1
    else:
        it["Music"].CurrentIndex = musics.index(s.music_name) if s.music_name in musics else 0
    anim_codes = [c for c, _ in TEXT_ANIMATIONS]
    it["TextAnim"].AddItems([label for _, label in TEXT_ANIMATIONS])
    it["TextAnim"].CurrentIndex = anim_codes.index(s.text_animation) if s.text_animation in anim_codes else 0
    it["Look"].AddItems(LOOK_CHOICES)
    it["Look"].CurrentIndex = LOOK_CHOICES.index(s.montage_look) if s.montage_look in LOOK_CHOICES else 0
    it["Pace"].AddItems(PACES)
    it["Pace"].CurrentIndex = PACES.index(s.montage_pace) if s.montage_pace in PACES else 1

    styles = list(STYLES)
    it["MotionStyle"].AddItems(styles)
    it["MotionStyle"].CurrentIndex = styles.index(s.motion_style) if s.motion_style in styles else 0

    def log(msg):
        print(f"[ReelAI] {msg}")
        it["Status"].Append(msg)

    def on_pick_music(ev):
        name = selected_music() if selected_music else ""
        if not name:
            log("Clique d'abord sur ta musique dans le Media Pool (un clip audio), puis sur ce bouton.")
            return
        if name not in musics:
            musics.append(name)
            it["Music"].AddItem(name)
        it["Music"].CurrentIndex = musics.index(name)
        log(f"🎵 Musique choisie : {name}")

    def on_add_texts(mode):
        def handler(ev):
            if texts_runner is None:
                return
            s.api_key = it["ApiKey"].Text.strip()
            s.higgsfield_key = it["HfKey"].Text.strip()
            save_settings(s)
            it["Status"].PlainText = "Ajout des textes..." + (" (Higgsfield : 1 à 5 minutes)" if mode == "higgsfield" else "")
            warnings = texts_runner(s, mode, log)
            log("✔ Textes ajoutés." if not warnings else "Terminé avec des avertissements (voir ci-dessus).")
        return handler

    def on_read_sub(ev):
        text = read_subtitle() if read_subtitle else ""
        if text:
            it["MotionText"].Text = text
        else:
            log("Aucun sous-titre sous la tête de lecture.")

    def guarded(fn):
        def wrapper(ev):
            try:
                fn(ev)
            except Exception as exc:
                traceback.print_exc()
                log(f"Erreur : {exc}")
                it["Go"].Enabled = True
                it["Motion"].Enabled = True
        return wrapper

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
        s.source_mode = src_codes[int(it["Source"].CurrentIndex)]
        music = musics[int(it["Music"].CurrentIndex)]
        s.music_name = {AUTO_MUSIC: "", NO_MUSIC: "-"}.get(music, music)
        s.montage_look = LOOK_CHOICES[int(it["Look"].CurrentIndex)]
        s.montage_texts = bool(it["Texts"].Checked)
        s.text_animation = anim_codes[int(it["TextAnim"].CurrentIndex)]
        s.higgsfield_key = it["HfKey"].Text.strip()
        s.montage_pace = PACES[int(it["Pace"].CurrentIndex)]
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

    win.On.Go.Clicked = guarded(on_go)
    win.On.Motion.Clicked = guarded(on_motion)
    win.On.ReadSub.Clicked = guarded(on_read_sub)
    win.On.PickMusic.Clicked = guarded(on_pick_music)
    win.On.AddTexts.Clicked = guarded(on_add_texts("reelai"))
    win.On.AddTextsHF.Clicked = guarded(on_add_texts("higgsfield"))
    win.On.Close.Clicked = lambda ev: disp.ExitLoop()
    win.On.ReelAIWin.Close = lambda ev: disp.ExitLoop()
    win.Show()
    disp.RunLoop()
    win.Hide()


# ---------------------------------------------------------------- Tkinter
def show_tk_ui(runner, motion_runner=None, read_subtitle=None, music_names=()) -> None:
    import tkinter as tk
    from tkinter import ttk

    s = load_settings()
    root = tk.Tk()
    root.title("ReelAI - Reels automatiques par IA")
    frm = ttk.Frame(root, padding=12)
    frm.grid(sticky="nsew")

    v = {
        "source_mode": tk.StringVar(value=s.source_mode),
        "music_name": tk.StringVar(value=s.music_name),
        "montage_pace": tk.StringVar(value=s.montage_pace),
        "montage_look": tk.StringVar(value=s.montage_look),
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
        ("Source (media_pool / selected)", "source_mode",
         lambda var: ttk.Combobox(frm, values=[c for c, _ in SOURCES], textvariable=var)),
        ("Musique (vide = auto, - = aucune)", "music_name",
         lambda var: ttk.Combobox(frm, values=["", "-"] + list(music_names), textvariable=var)),
        ("Look", "montage_look", lambda var: ttk.Combobox(frm, values=LOOK_CHOICES, textvariable=var)),
        ("Rythme", "montage_pace", lambda var: ttk.Combobox(frm, values=PACES, textvariable=var)),
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
