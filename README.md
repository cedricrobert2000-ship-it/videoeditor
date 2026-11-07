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

Le script installe les dépendances (`anthropic`, `faster-whisper`, `higgsfield-client`). Il copie aussi `ReelAI.py` dans le dossier Scripts de Resolve :

| Système | Dossier |
|---|---|
| Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility` |
| macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility` |
| Linux | `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility` |

Ensuite, **redémarre DaVinci Resolve**.

> `install.py` retient le Python avec lequel tu l'as lancé. Si le Python interne de Resolve n'a pas les outils, ReelAI fait automatiquement le travail lourd dans ce Python-là.

## Utilisation

Ouvre **Workspace › Scripts › ReelAI** (en français : *Espace de travail › Scripts*). Il y a deux sources possibles.

### Mode « Tout le Media Pool » (montage de plans) : par défaut

Ce mode convient aux plans tournés sans parole : salon, produit, lifestyle, événement…

1. Importe tous tes plans et une musique dans le Media Pool. Inutile de sélectionner quoi que ce soit.
2. Dans ReelAI, choisis **Source : Tout le Media Pool**, ta **Musique**, puis le **Rythme** (Lent, Moyen ou Rapide).
3. Clique sur **🎬 Générer les reels**.

ReelAI fabrique pour chaque clip une **planche de 6 vignettes horodatées** et signale les images floues. Le décodage est rapide, se fait en parallèle et passe par un cache : une relance est quasi instantanée. **Claude regarde les planches** et compose un montage de pro :
- il choisit **le meilleur passage de chaque clip** autour des vignettes nettes et belles ;
- il ouvre sur un plan qui accroche, raconte une mini-histoire et garde le plus fort pour la fin ;
- les durées de plans varient et se comptent en temps de musique, avec des coupes **calées sur le tempo** ;
- il choisit **le bon passage de la musique** : ReelAI mesure l'énergie mesure par mesure et propose les meilleurs départs (montée, partie la plus énergique), Claude prend celui qui sert le montage, et la durée totale est arrondie à des mesures entières ;
- le cadrage 9:16 suit le sujet de chaque plan, avec un léger zoom sur les détails ;
- un **look** d'étalonnage est appliqué à tous les plans.

**Musique** : clique sur ta musique dans le Media Pool, puis sur **🎵 Prendre la musique sélectionnée**. Tu peux aussi la choisir dans la liste.

**Textes sur les plans** : Claude propose 2 à 4 textes (accroche, message, appel à l'action), chacun sur un plan précis et à une position qui ne cache pas le sujet.
- **ReelAI (par défaut)** : les textes sont rendus en vidéo transparente (ProRes 4444) à la durée exacte du plan, avec une typo grasse, une apparition mot par mot, une ombre douce et un fondu de sortie. Ils sont posés sur V3 dès le montage. C'est rapide et gratuit.
- **Higgsfield** : il intervient **après** le montage. Ouvre la timeline du reel et clique sur **✨ Animer les textes avec Higgsfield** : chaque plan concerné est réanimé par l'IA avec le texte intégré à la scène, puis posé sur V2. Si un plan échoue, il reçoit le texte ReelAI.
- Le bouton **✍️ Ajouter les textes (ReelAI)** ajoute après coup les textes proposés, si la case n'était pas cochée au montage.

### Mode « Clip sélectionné » (vidéo parlée)

Ce mode convient aux podcasts, interviews, vlogs et formations.

1. Sélectionne **un clip vidéo** dans le Media Pool. Ce doit être un clip, pas une timeline.
2. Choisis **Source : Clip sélectionné** et clique sur **🎬 Générer les reels**.

Dans ce mode, ReelAI transcrit la vidéo, choisit les meilleurs passages avec un hook au début, coupe les blancs et les « euh », puis ajoute des sous-titres.

### Dans les deux cas

- Les timelines `Reel 1 - …`, `Reel 2 - …` apparaissent dans le chutier **ReelAI**.
- Une légende `.txt` (titre, description, hashtags) est créée pour chaque reel.
- Les messages et les erreurs s'affichent dans la zone **Messages** de la fenêtre.
- Resolve peut sembler figé pendant le traitement. C'est normal.

## ✨ Motion design avec Higgsfield

Tu choisis une phrase, ReelAI crée un **clip de motion design pro** adapté au contenu et le pose sur ta timeline.

1. Ouvre la timeline d'un reel et place la **tête de lecture** à l'endroit voulu.
2. Dans la section **Motion design** de la fenêtre ReelAI, écris ton texte. Tu peux aussi cliquer sur **↓ Sous-titre** pour reprendre la phrase prononcée à cet endroit.
3. Choisis un style : Auto, Minimal premium, Cinématique, Tech / néon, Luxe, Énergique ou Nature / lifestyle.
4. Clique sur **✨ Créer le motion à la tête de lecture**.

Voici ce qui se passe ensuite :
- **Claude** lit le contexte du reel (hook, sous-titres). Il écrit un brief de motion designer : une métaphore visuelle du message, la lumière, le mouvement de caméra et la palette.
- **Higgsfield** génère le clip 9:16 (de 3 à 10 s) en choisissant le meilleur modèle vidéo pour ce rendu. Compte de 1 à 5 minutes.
- Le clip est posé sur la piste **V2**, à la tête de lecture.
- Avec l'option « Texte net ajouté par Resolve » (recommandée), ton texte est ajouté en **Text+** sur V3, dans une couleur choisie par l'IA. Les IA vidéo déforment souvent les lettres, alors que Resolve garantit une typo parfaite. Tu peux ensuite l'animer ou changer la police dans l'inspecteur.

**Clé Higgsfield** : crée-la sur [cloud.higgsfield.ai](https://cloud.higgsfield.ai) et colle-la au format `key-id:key-secret`. Ton compte doit avoir accès à l'**Agent API** et disposer de crédits Higgsfield. Chaque motion consomme des crédits Higgsfield en plus des quelques centimes de Claude.

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
  montage_ai.py        montage de plans : analyse d'images par Claude, tempo, calage
  motion.py            motion design (brief Claude + génération Higgsfield)
  worker.py/backend.py travail lourd exécuté dans le bon Python
  ui.py / launcher.py  fenêtre (UIManager de Resolve ou Tkinter)
```
