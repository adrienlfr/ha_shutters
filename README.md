# Solar Shutters pour Home Assistant

Solar Shutters automatise les volets selon l’orientation de chaque fenêtre, la
position réelle du soleil, la température et la présence des occupants. Toute
la configuration se fait dans l’interface Home Assistant, sans YAML.

## Fonctions

- autant de fenêtres que nécessaire, chacune avec son volet, son thermomètre et
  sa plage d’azimut ;
- un seul comportement commun à toutes les fenêtres, saisi uniquement lors de
  la création de la première fenêtre ;
- fermeture lorsque le soleil est face à la fenêtre et que la température
  dépasse le seuil réglable ;
- seuil de réouverture avec une hystérésis de 0,5 °C pour éviter les mouvements
  répétés autour de la consigne ;
- fonctionnement permanent ou uniquement lorsque personne n’est à la maison ;
- mode télétravail qui autorise l’automatisation pendant une plage horaire,
  même si la maison est occupée ;
- fermeture au crépuscule et ouverture à l’aube en cas d’absence ;
- plages d’azimut traversant le nord, par exemple 300° → 40° ;
- conversion automatique d’un thermomètre exprimé en °F vers °C ;
- protection des commandes manuelles : une action humaine suspend la fermeture
  solaire jusqu’à la fin du cycle en cours ;
- restauration après redémarrage : l’intégration ne rouvre que les volets
  qu’elle avait elle-même fermés.

## Installation avec HACS

1. Dans HACS, ouvrir **Intégrations** puis le menu ⋮.
2. Choisir **Dépôts personnalisés**.
3. Ajouter `https://github.com/adrienlfr/ha_shutters` avec la catégorie
   **Intégration**.
4. Rechercher **Solar Shutters**, télécharger l’intégration puis redémarrer
   Home Assistant.
5. Ouvrir **Paramètres → Appareils et services → Ajouter une intégration** et
   rechercher **Solar Shutters** (ou **Volets solaires** en français).

## Configuration

Ajoutez une intégration par fenêtre. Lors de la première fenêtre seulement,
Home Assistant demande aussi le comportement commun. Pour chaque fenêtre,
indiquez :

- un nom ;
- l’entité `cover` du volet ;
- le capteur de température ;
- toutes les entités `person` ou `device_tracker` représentant les occupants ;
- l’azimut auquel le soleil entre dans l’axe de la fenêtre et celui auquel il
  en sort.

Repères : nord 0°, est 90°, sud 180°, ouest 270°. L’entité `sun.sun` de Home
Assistant fournit automatiquement l’azimut et l’élévation du soleil.

Un appareil global **Solar Shutters** expose les commandes communes :

- quatre interrupteurs : automatisation, absence seulement, télétravail,
  aube/crépuscule en cas d’absence ;
- deux heures pour la plage de télétravail ;
- un seuil de température.

Chaque fenêtre apparaît aussi comme un appareil séparé avec trois diagnostics
indiquant le soleil direct, l’autorisation de l’automatisation et la demande de
fermeture solaire. Une modification sur l’appareil global est appliquée
immédiatement à toutes les fenêtres.

Le mode télétravail est un **complément au mode absence** : si « uniquement en
cas d’absence » est actif, le volet peut quand même être piloté lorsque le mode
télétravail est actif et que l’heure courante se trouve dans sa plage.

## Comportement de sécurité

- Sans entité de présence valide, le logement est considéré occupé.
- Si le thermomètre est indisponible, aucune fermeture liée à la chaleur n’est
  lancée. La fermeture nocturne reste indépendante.
- Désactiver l’automatisation rouvre un volet uniquement si Solar Shutters
  l’avait fermé.
- Un volet fermé au crépuscule reste fermé si un occupant rentre pendant la
  nuit ; il est restauré à l’aube (sauf si la protection solaire le réclame).
- À l’aube, un volet peut rester fermé si les conditions d’ensoleillement et de
  température demandent déjà de l’ombre.

## Publication initiale sur GitHub

Les commandes exactes sont données dans la section « Publication » du message
de livraison. Le dépôt officiel de cette version est
`https://github.com/adrienlfr/ha_shutters`.

Le contrôle HACS ignore uniquement l’absence de marque graphique officielle.
Une marque dans `home-assistant/brands` n’est nécessaire que pour demander
l’ajout du dépôt à la liste publique par défaut de HACS ; elle ne l’est pas pour
installer ce dépôt comme dépôt personnalisé.

## Licence

MIT
