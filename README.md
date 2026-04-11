# Prométhée Défis

Application Streamlit de suivi de défis avec :
- espace personnel par profil
- validation admin des défis
- progression globale par ordre de défis
- stockage des données dans Supabase

## Structure

- [app.py](C:\Users\lll\Documents\GitHub\prometheedefis\app.py) : application Streamlit complète
- [requirements.txt](C:\Users\lll\Documents\GitHub\prometheedefis\requirements.txt) : dépendances Python
- [.streamlit/config.toml](C:\Users\lll\Documents\GitHub\prometheedefis\.streamlit\config.toml) : thème Streamlit
- [.streamlit/secrets.example.toml](C:\Users\lll\Documents\GitHub\prometheedefis\.streamlit\secrets.example.toml) : exemple de secrets à configurer

## Secrets requis

Configurer ces secrets dans Streamlit Cloud ou dans un fichier local `.streamlit/secrets.toml` :

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-supabase-service-or-anon-key"
```

Le mot de passe admin reste codé en dur dans [app.py](C:\Users\lll\Documents\GitHub\prometheedefis\app.py), conformément au fonctionnement actuel.

## Lancer en local

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## Points métier à connaître

- la progression des profils est stockée comme un index global dans la liste complète des défis
- ajouter un défi dans une catégorie renvoie les profils actifs concernés directement sur ce nouveau défi
- les profils déjà terminés restent terminés quand un nouveau défi est ajouté, pour éviter de rouvrir tout le parcours
- supprimer un défi décale automatiquement la progression pour éviter de casser le défi courant des profils
- le réordonnancement d'un défi est bloqué si un profil est actuellement positionné sur l'un des défis à permuter
- les PIN sont désormais stockés sous forme hashée pour les nouveaux profils et migrés automatiquement lors de la prochaine connexion d'un profil encore en clair

## Déploiement Streamlit

Si l'app Streamlit déployée pointe sur ce dépôt et sur la branche `main`, un push sur `main` mettra le code de production à jour au prochain redéploiement.
