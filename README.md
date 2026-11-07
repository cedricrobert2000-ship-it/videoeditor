# 🎬 ReelAI : des reels montés automatiquement par l'IA dans DaVinci Resolve

ReelAI est une extension pour **DaVinci Resolve**. Tu lui donnes une vidéo longue (podcast, interview, vlog, formation…). Elle crée **toute seule** plusieurs reels verticaux prêts à publier :

1. **Transcription** mot à mot de la vidéo, en local et gratuitement, avec [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
2. **Claude**, l'IA d'Anthropic, fait le monteur. Il choisit les meilleurs passages et place un **hook** fort au début. Il enlève les digressions et donne un titre, une description et des hashtags à chaque reel.
3. **Montage automatique** : une timeline **9:16 (1080×1920)** par reel, recadrée au centre.
4. **Coupe des blancs et des « euh »**, mot par mot.
5. **Sous-titres dynamiques** de 2 ou 3 mots, en majuscules, posés sur la piste de sous-titres.
6. Un **marqueur** sur chaque timeline avec le hook, la description et les hashtags, plus un fichier `légende.txt` à copier-coller.
7. **Export MP4** automatique (en option).

## Installation

### 1. Prérequis

- DaVinci Resolve 18.5 ou plus récent (version gratuite ou Studio).
- **Python 3.10 à 3.12 (64 bits)**, installé depuis [python.org](https://www.python.org/downloads/). Resolve s'en sert pour exécuter les scripts.
- Une clé API Anthropic. Tu la crées sur [console.anthropic.com](https://console.anthropic.com/).

### 2. Installer l'extension

```bash
git clone https://github.com/cedricrobert2000-ship-it/videoeditor.git
```

```bash
cd videoeditor
```

```bash
python3 install.py
```

> Sur **Mac**, la commande est `python3` (et non `python`). Si tu as installé Python 3.12 depuis python.org, utilise `python3.12 install.py`. Sur Windows, la commande est `python install.py`.

Le script installe les dépendances (`anthropic`, `faster-whisper`). Il copie aussi `ReelAI.py` dans le dossier Scripts de Resolve :

| Système | Dossier |
|---|---|
| Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility` |
| macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility` |
| Linux | `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility` |

Ensuite, **redémarre DaVinci Resolve**.

> ⚠️ Lance `install.py` avec le même Python que celui de Resolve. Pour le vérifier, ouvre la console de Resolve (*Workspace › Console*, onglet *Py3*) et tape `import sys; print(sys.executable)`.

## Utilisation

1. Importe ta vidéo dans le **Media Pool** et **sélectionne-la**.
2. Ouvre **Workspace › Scripts › ReelAI**.
3. Colle ta clé API. Elle est enregistrée dans `~/.reelai/config.json` et n'est demandée qu'une fois.
4. Choisis le nombre de reels, la durée visée, la langue et, si tu veux, des consignes. Par exemple : *« garde les conseils concrets, ton motivant »*.
5. Clique sur **🎬 Générer les reels**.

Resolve peut sembler figé pendant la transcription, de quelques secondes à quelques minutes selon la longueur de la vidéo. C'est normal. Ensuite, les timelines `Reel 1 - …`, `Reel 2 - …` apparaissent dans le chutier **ReelAI**. Les fichiers `.srt` et les légendes sont rangés dans un dossier `ReelAI/` à côté de ta vidéo.

La transcription est gardée en cache. Si tu relances avec d'autres consignes, seule l'étape de l'IA est refaite, en quelques secondes.

## Réglages avancés

Tous les réglages sont dans `~/.reelai/config.json` :

| Clé | Défaut | Rôle |
|---|---|---|
| `model` | `claude-opus-5-5` | Modèle Claude utilisé pour le choix des passages |
| `whisper_model` | `small` | `tiny`/`base` : rapide · `medium`/`large-v3` : plus précis |
| `max_silence` | `0.45` | Un blanc plus long (en secondes) est coupé |
| `padding` | `0.08` | Marge gardée autour des mots |
| `filler_words` | `euh, heu, hum…` | Mots retirés au montage |
| `subtitle_max_words` | `3` | Nombre de mots maximum par sous-titre |
| `output_dir` | *(vide)* | Dossier des exports et des fichiers SRT |

Sans fenêtre, avec Resolve Studio et le scripting externe activé :

```bash
python -m reelai --headless
```

## Bon à savoir

- **Coût** : une vidéo d'une heure correspond à environ 15 000 mots envoyés à Claude, soit quelques centimes par génération.
- **Sous-titres** : si ta version de Resolve refuse de poser le SRT tout seul, un message te le signale. Il suffit alors de glisser le fichier `.srt` du chutier ReelAI sur la timeline. Pour changer leur style (police, taille, contour), passe par l'inspecteur de la piste de sous-titres.
- **Cadrage** : le recadrage 9:16 se fait au centre. Si la personne filmée n'est pas centrée, ajuste la position dans l'inspecteur, ou utilise *Smart Reframe* (Resolve Studio).
- **Interface** : si la fenêtre native de Resolve n'est pas disponible dans ta version, ReelAI ouvre une fenêtre Tkinter à la place.

## Développement

```bash
pip install pytest anthropic
```

```bash
python -m pytest
```

Les tests utilisent un faux DaVinci Resolve et un faux client Claude. Ils couvrent les coupes, les sous-titres, la requête envoyée à l'IA et tout le pipeline.

```
ReelAI.py              script du menu Workspace › Scripts
install.py             installation
reelai/
  transcribe.py        transcription Whisper + cache
  editor_ai.py         choix des passages par Claude (sortie JSON structurée)
  cuts.py              coupe des blancs et des « euh », conversion en frames
  subtitles.py         sous-titres style reel (SRT)
  resolve_bridge.py    API de script de DaVinci Resolve
  pipeline.py          orchestration
  ui.py / launcher.py  fenêtre (UIManager de Resolve ou Tkinter)
```
