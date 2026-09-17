# PHASE 4 — déploiement externe des contrats médicaux

## État

Le déploiement local a été validé avec :

- trois vrais `Node` reliés par `SocketP2P` ;
- un processus de déploiement séparé des validateurs ;
- les trois artefacts Solidity vérifiés par `contracts/artifacts/SHA256SUMS` ;
- trois transactions de création signées ML-DSA ;
- inclusion dans des blocs réels et persistance dans `ChainStorage` ;
- même code de contrat présent dans l'état EVM des trois nœuds.

Le processus de déploiement ne demande aucun reçu EVM à `Node` : cette API
n'existe pas. Il conserve les informations réellement observables depuis le
transport et les blocs : adresse calculée, nonce, hash de transaction, hauteur,
hash de bloc et `state_root`.

## Architecture retenue

Le client de déploiement n'est pas un validateur et ne lance pas de `Node`.
Il possède une paire ML-DSA distincte :

```text
client de déploiement externe
  ├── deployment_public_key.bin
  └── deployment_secret_key.bin   (reste local, jamais copié)

        SocketP2P vers les 3 validateurs
                  │
        transactions de création signées
                  │
       node1 / node2 / node3 exécutent le même déploiement
```

Pour le déploiement historique de cette phase, les transactions sont
envoyées directement aux trois validateurs. Cette méthode reste un
contournement comparatif et ne constitue pas le scénario applicatif final de
la PHASE 5 : le relais applicatif est maintenant porté par `Node`, avec
déduplication des `tx_id`.

Les contrats ne sont donc pas copiés dans les répertoires des nœuds. Ils sont
inscrits une fois dans la blockchain par transactions ; chaque nœud rejoue ces
transactions et obtient le même code à la même adresse.

## Commande de déploiement

À exécuter depuis la machine d'administration qui possède le dépôt et la clé
de déploiement, après le démarrage des trois validateurs :

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate

python -m src.evm.deployer \
  --target-host 192.168.168.101 \
  --target-host 192.168.168.102 \
  --target-host 192.168.168.103 \
  --target-port 9001 \
  --key-dir ~/.blockchain-medical/deployment-key \
  --artifact-dir contracts/artifacts \
  --manifest ~/.blockchain-medical/medical-deployment.json
```

Le client :

1. crée ou recharge la clé de déploiement locale ;
2. vérifie le SHA-256 des trois artefacts ;
3. rejoint les trois validateurs par TCP ;
4. déploie `PatientRegistry` ;
5. déploie `ConsentManager` avec l'adresse du premier contrat ;
6. déploie `MedicalRecordRegistry` avec les deux adresses précédentes ;
7. attend l'inclusion de chaque transaction dans un bloc ;
8. écrit le manifeste public indiqué par `--manifest`.

Pour un réseau neuf, le nonce de départ par défaut est `0`. Pour une nouvelle
clé de déploiement déjà utilisée sur une autre chaîne, utiliser explicitement
un autre répertoire de clé et vérifier le nonce de départ avant de soumettre.

## Manifeste produit

Le manifeste ne contient aucune clé secrète. Il contient notamment :

- l'adresse publique du compte de déploiement ;
- les trois cibles TCP ;
- l'adresse de chaque contrat ;
- son nonce de création ;
- le hash de sa transaction ;
- la hauteur, le hash et la racine d'état du bloc d'inclusion ;
- le SHA-256 de l'artefact utilisé.

Les adresses sont calculées avec la formule EVM `CREATE` à partir de
l'adresse du déployeur et du nonce. Elles sont donc identiques sur les trois
nœuds lorsque la chaîne converge.

## Critères de fin de cette étape

- [x] Le client externe ne modifie pas `Node` ni `Node._accept_block()`.
- [x] Les trois contrats sont déployés par transactions réelles.
- [x] Les artefacts sont vérifiés avant émission.
- [x] Les trois validateurs reçoivent les transactions.
- [x] Les blocs sont persistés et les trois états EVM convergent.
- [x] La clé secrète de déploiement est distincte des clés de validateurs.
- [x] Le test d'intégration externe est passé.
- [ ] Déploiement inter-VM réel : étape suivante, après validation de la
  connectivité et de l'installation Python sur les trois VMs.
