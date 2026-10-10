# xp-photocraft — guide d'installation

**Generative Fill** et **Remove (IA)** dans PhotoCraft, sur votre propre ComfyUI. Vous sélectionnez
une zone, vous tapez ce que vous voulez y voir, le résultat arrive dans un nouveau calque masqué.
Rien ne quitte votre machine avec le modèle intégré (Qwen Image Edit) ; Nano Banana est en option,
via le cloud comfy.org.

Trois morceaux, à installer dans cet ordre. **Tout reste dans un seul dossier** (celui où vous
dézippez) : le pont, ses réglages dans `data\`, et ComfyUI dans `ComfyUI-xp\`. Vous pouvez tout
vérifier, tout déplacer, et désinstaller en supprimant le dossier.

| Morceau | Rôle | Où |
|---|---|---|
| **PhotoCraft (build XP)** | l'application, avec la barre d'outils IA sous la sélection et le menu **XP** | release du fork PhotoCraft XP, dézippée à côté |
| **xp-photocraft** (ce dossier) | le pont : PhotoCraft ↔ ComfyUI | `install.bat` / `install.sh` |
| **ComfyUI** + modèles | la génération, sur ce PC ou sur un autre PC avec un bon GPU | `install-comfyui.bat` / `.sh` → `ComfyUI-xp\`, ou un ComfyUI existant |

Il n'y a **rien d'autre à installer** avant : ni Python, ni Git. Le pont est un exécutable autonome
et l'installeur ComfyUI apporte lui-même son Python (par l'outil `uv`).

## 1. Ce qu'il faut

- Windows 10/11 64 bits, ou Linux (binaire construit sur Fedora 41, glibc 2.40 ou plus récente).
- Pour générer **en local** : une carte NVIDIA. 24 Go de VRAM pour le confort (RTX 3090/4090/5090),
  16 Go possible, 12 Go et moins : lent (le modèle déborde en RAM), prévoyez 32 Go de RAM ou plus.
  Sans GPU : utilisez le ComfyUI d'un autre PC (§ 4) ou Nano Banana (§ 5).
- Environ 40 Go de disque pour ComfyUI et les modèles.

## 2. Installer le pont (Windows)

1. Créez un dossier (par exemple `C:\PhotoCraftXP`) et dézippez-y les deux archives : celle de
   PhotoCraft XP et celle-ci. Vous obtenez `PhotoCraft-XP\photocraft.exe` et
   `xp-photocraft-…-windows-x64\xp-photocraft.exe`.
2. Double-cliquez **`install.bat`**. Il ajoute ce dossier à votre PATH utilisateur (pour que la barre
   de PhotoCraft trouve le pont), crée `data\` (réglages et dossier de travail) et dépose l'exemple
   Nano Banana. Rien n'est copié ailleurs, pas de droits administrateur.
3. Lancez PhotoCraft avec **`start-photocraft.bat`** (il démarre PhotoCraft avec son serveur de
   contrôle et le dossier de travail partagé `data\work`). Il trouve `photocraft.exe` dans un dossier
   `PhotoCraft*` à côté ; sinon glissez l'exe dessus une fois, ou écrivez son chemin dans
   `photocraft-path.txt`.

Linux : `./install.sh` (liens dans `~/.local/bin`), puis `start-photocraft`.

## 3. Installer ComfyUI sur ce PC (NVIDIA)

Double-cliquez **`install-comfyui.bat`** (Linux : `./install-comfyui.sh`). Il installe dans
`ComfyUI-xp\`, à côté : l'outil `uv` et un Python à lui, ComfyUI, PyTorch CUDA (choisi d'après votre
pilote NVIDIA), les quatre fichiers du workflow intégré (Qwen Image Edit 2511, encodeur, VAE, LoRA
Lightning, ~32 Go) et un **`start-comfyui.bat`**. Comptez 3 Go puis 32 Go de téléchargement ; il
reprend là où il s'est arrêté si vous le relancez.

- RTX 30 (3090, 3080…) : avant de lancer, ouvrez une console et tapez `set XP_QWEN_VARIANT=int8`
  puis `install-comfyui.bat` ; les poids int8 sont plus rapides sur ces cartes.
- Vous avez déjà ComfyUI ? Inutile de réinstaller : ouvrez-y le modèle *Qwen Image Edit 2511*
  (menu Templates), il télécharge les mêmes fichiers. Le pont les retrouve par leur nom.

Ensuite : lancez `start-comfyui.bat` (gardez la fenêtre ouverte), puis dans une console :

```
xp-photocraft connect http://127.0.0.1:8188
```

Réponse attendue : `ComfyUI connected - built-in Qwen models OK`. Le menu **XP** de PhotoCraft a le
même champ (*ComfyUI server* ▸ *Test & save*).

## 4. ComfyUI sur un autre PC

Sur le PC GPU, démarrez ComfyUI avec `--listen` **sur un réseau de confiance** (ComfyUI n'a aucune
authentification : jamais exposé à internet), puis sur le PC PhotoCraft :
`xp-photocraft connect http://ADRESSE-DU-PC:8188`. Plus sûr : un tunnel SSH
(`ssh -N -L 8188:127.0.0.1:8188 vous@pc-gpu`) et l'adresse par défaut `http://127.0.0.1:8188`.

## 5. Nano Banana (qualité cloud, en option)

Nano Banana 2.1 est un *nœud partenaire* de ComfyUI : il tourne chez comfy.org et se facture à votre
compte (quelques centimes par image). Il faut un ComfyUI récent (0.39 ou plus, ce que
`install-comfyui` installe) et une clé API comfy.org :

1. Créez un compte sur [comfy.org](https://www.comfy.org), achetez quelques crédits, et générez une
   clé API dans votre profil (*API Keys* sur platform.comfy.org). Copiez-la : elle ne se réaffiche pas.
2. Ouvrez **`data\.env`** (créé par `install.bat` depuis `.env.example`) et renseignez la ligne
   `XP_PHOTOCRAFT_COMFY_API_KEY=votre-clé`. Le pont lit ce fichier à chaque génération : rien à
   relancer. Une variable d'environnement du même nom, si vous en avez une, a priorité.
3. Dans PhotoCraft, menu **XP ▸ Generative fill ▸ Nano Banana 2.1 (comfy.org)**. Le réglage se
   garde par action : Qwen local pour le *Remove*, Nano Banana pour le *Fill*, par exemple.

Sans clé, la barre d'état dit « GeminiNanoBanana…: Unauthorized: Please login first to use this
node ». La clé n'est jamais affichée et ne sort que vers votre ComfyUI, qui la présente à comfy.org.

## 6. Utiliser

Sélectionnez une zone (rectangle, lasso…). Une barre apparaît dessous :

- **Generative fill** : tapez ce que vous voulez dans le champ, cliquez. Une carte barrée prend la
  place pendant la génération, vous continuez à travailler ; le résultat la remplace, en calque
  masqué par votre sélection.
- **Remove (IA)** : efface ce qui est sélectionné et reconstruit le fond. Prenez l'ombre dans la
  sélection.
- **Remove** : le remplissage classique de PhotoCraft, sans IA.

Chaque résultat est aussi gardé **à côté du fichier du document**, dans `xp-work\<nom du document>\`
(image du modèle + un `.json` avec le prompt, le workflow et la graine) : un dossier par projet, rien
ne s'accumule ailleurs. Sur un document jamais enregistré, la barre propose d'abord de l'enregistrer.

Conseils : une marge autour de l'objet aide le modèle ; pour ajouter quelque chose dans une zone
uniforme (ciel, mur), adoucissez la sélection (Feather 20–30 px) et laissez de la place pour l'ombre
ou la fumée. Une génération écrase le presse-papiers (limite connue).

## 7. En cas de problème

```
xp-photocraft doctor
```

Il vérifie, ligne par ligne : le dossier de travail, la liaison avec PhotoCraft (est-il lancé par
`start-photocraft` ?), le serveur ComfyUI, les workflows et leurs modèles.

- *« PhotoCraft does not answer »* : PhotoCraft n'a pas été lancé par `start-photocraft.bat`.
- *« ComfyUI server unreachable »* : ComfyUI n'est pas démarré, ou l'adresse enregistrée est fausse
  (`xp-photocraft connect …`).
- *« models not on the ComfyUI server »* : relancez `install-comfyui.bat` (il reprend les
  téléchargements) ou installez le modèle *Qwen Image Edit 2511* depuis les templates de ComfyUI.
- Première génération lente (~1 min) : les modèles se chargent ; ensuite 10 à 30 s selon la carte.

## 8. Désinstaller

Supprimez le dossier (pont, `data\`, `ComfyUI-xp\` avec son `uv`, son Python et ses modèles) et
retirez-le de votre PATH utilisateur (Paramètres ▸ Variables d'environnement). Linux : supprimez
aussi les deux liens dans `~/.local/bin`. Rien d'autre n'a été écrit sur la machine.
