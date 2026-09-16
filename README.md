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
- mode progressif facultatif par fenêtre : ouverture calculée selon la géométrie
  solaire et la température intérieure, avec anticipation de la chaleur extérieure ;
- fonctionnement permanent ou uniquement lorsque personne n’est à la maison ;
- mode télétravail qui autorise l’automatisation pendant une plage horaire,
  même si la maison est occupée, et se désactive automatiquement à l’heure
  de fin ;
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
À l’heure de fin configurée, l’interrupteur télétravail repasse sur désactivé
pour toutes les fenêtres. Il faut le réactiver pour une prochaine journée.

## Ouverture progressive

Le mode progressif se règle dans les options de chaque fenêtre. Il est désactivé
par défaut : les fenêtres existantes conservent leur fonctionnement ouvert/fermé.
Il convient aux volets descendant du haut vers le bas, dont le pourcentage est
approximativement proportionnel à la hauteur ouverte : **0 % fermé, 100 % ouvert**.
Les volets sans commande de position conservent le fonctionnement ouvert/fermé.

Pour l’activer, renseignez les quatre mesures suivantes (aucune dimension n’est
supposée automatiquement) :

| Réglage | Mesure |
| --- | --- |
| Orientation de la façade | Direction perpendiculaire à la vitre, vers l’extérieur ; nord 0°, est 90°, sud 180°, ouest 270°. |
| Hauteur de l’ouverture vitrée | Hauteur découverte avec le volet complètement ouvert, en mètres. |
| Hauteur du bas de la fenêtre | Distance verticale entre le sol et le bas de l’ouverture vitrée, en mètres ; 0 pour une baie au niveau du sol. |
| Profondeur de soleil autorisée | Distance maximale de pénétration du soleil au sol, mesurée perpendiculairement à la façade, en mètres. |

La plage d’azimut existante continue à limiter l’exposition. Le calcul utilise
aussi l’élévation du soleil et exclut les rayons venant de derrière la façade.
Il choisit la hauteur ouverte pour limiter la pénétration au sol. Un soleil bas
peut nécessiter une fermeture complète. Ce modèle ne prend pas en compte les
nuages ou les obstacles latéraux : avec les paliers et temporisations, la
profondeur est un objectif approximatif, pas une limite garantie à chaque instant.

### Températures intérieure et extérieure

Le capteur de chaque fenêtre doit mesurer la température **intérieure**. Une
source extérieure facultative se sélectionne à la création de la première
fenêtre ou dans les options de n’importe quelle fenêtre. Cette source est commune
à toutes les fenêtres : capteur de température ou température actuelle d’une
entité météo. Effacer la sélection désactive l’anticipation pour toutes les
fenêtres. Les unités sont converties en Celsius.

Si l’extérieur est plus chaud, le seuil intérieur est abaissé progressivement :
aucune correction pour un écart jusqu’à 2 °C, −0,5 °C pour un écart de 4 °C,
−1 °C pour un écart de 6 °C ou plus. Une source extérieure absente ou invalide
désactive seulement cette correction.

La protection commence au seuil ainsi corrigé et reste active jusqu’à ce que la
température intérieure descende sous ce seuil moins 0,5 °C. Au seuil, toute la
profondeur configurée est autorisée ; à +1 °C, elle est divisée par deux ; à +2 °C,
le volet est complètement fermé. Sans mesure intérieure valide, la demande est
une fermeture complète en présence de soleil direct, avec les mêmes temporisations.

### Limitation des mouvements

- La cible est arrondie vers le bas par paliers de 10 points : 57 % devient 50 %.
- Pour un dernier palier commandé `P`, il reste inchangé tant que le calcul est
  compris entre `P − 5` et `P + 15`. Par exemple, une cible de 50 % est conservée
  pour des calculs entre 45 et 65 %.
- Un nouveau palier doit rester identique pendant 5 minutes avant une commande.
- Les ajustements solaires sont espacés d’au moins 30 minutes, y compris après
  un échec de commande. Le volet rejoint directement le palier utile.
- Aucun ordre n’est envoyé pendant un déplacement ou lorsque la position est
  déjà à 3 points ou moins de la cible.
- Après 5 minutes sans soleil direct, un volet piloté par l’intégration est
  rouvert à 100 %, sans attendre la fin des 30 minutes.
- La fermeture nocturne et la libération du volet à la désactivation de
  l’automatisation ou à la fin de son autorisation sont prioritaires ; elles
  peuvent déroger au délai solaire. Une commande prioritaire en échec n’est
  pas répétée chaque minute.

Une intervention manuelle suspend le pilotage jusqu’à la fin du cycle de
protection ; le volet n’est alors pas rouvert par l’intégration. Si les données
solaires sont indisponibles, la position est conservée plutôt que d’interpréter
la panne comme une absence de soleil. Le délai entre commandes et la prise en
charge sont restaurés après redémarrage ; la confirmation de 5 minutes recommence.

Le diagnostic **Demande de protection solaire** expose aussi les attributs
`calculated_position`, `last_commanded_position`, `effective_temperature_threshold`,
`outdoor_temperature_celsius` et `wait_reason`. Les principaux motifs d’attente
sont `target_confirmation` (5 minutes de stabilité), `command_interval`
(30 minutes entre commandes), `no_sun_confirmation`, `manual_override`, `moving`,
`at_target`, `not_managed`, `sun_unavailable`, `cover_unavailable`,
`position_unavailable`, `command_failed` et `binary_fallback`.

Commencez par une seule fenêtre et vérifiez physiquement que 50 % correspond
approximativement à une demi-hauteur ouverte avant d’activer les autres.

## Comportement de sécurité

- Sans entité de présence valide, le logement est considéré occupé.
- Si le thermomètre est absent, indisponible ou fournit une valeur invalide,
  la température est considérée comme supérieure au seuil (24 °C par défaut).
  La protection solaire reste donc active selon le soleil et la présence.
  Dès qu’une mesure valide revient, elle est de nouveau utilisée.
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
