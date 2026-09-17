"""
Exceptions de la couche EVM.

Toutes les erreurs levees par src/evm/ derivent de EVMError, ce qui
permet a un appelant de les intercepter globalement sans connaitre le
detail de l'implementation.

Distinction fondamentale, a ne pas confondre :

    EVMError            -> defaillance de l'INFRASTRUCTURE d'execution
                           (etat corrompu, adresse malformee, appel
                           incoherent). C'est un bug, il doit remonter.

    Receipt(status=0)   -> la transaction a ECHOUE a l'execution
                           (revert, out-of-gas, nonce invalide, solde
                           insuffisant). Ce n'est PAS une erreur : le
                           fait est enregistre dans un recu et le bloc
                           reste parfaitement valide.

Cette distinction est ce qui protege le consensus. Si une transaction
qui revert levait une exception remontant jusqu'a Node._accept_block(),
un noeud rejetterait un bloc que les autres acceptent : fork immediat.
Une transaction qui echoue est un FAIT deterministe, partage par tous
les noeuds, pas une anomalie locale.
"""

from __future__ import annotations

from src.crypto.address import AddressError as CryptoAddressError


class EVMError(Exception):
    """Erreur de base de la couche EVM."""


class StateError(EVMError):
    """
    Erreur d'acces ou de manipulation de l'etat du monde.

    Exemples : adresse de longueur invalide, valeur negative, cle de
    stockage hors bornes, racine d'etat introuvable dans la base.
    """


class ExecutionError(EVMError):
    """
    Erreur d'infrastructure survenue pendant l'execution.

    A NE PAS utiliser pour un revert ou un out-of-gas, qui sont des
    resultats normaux traduits en Receipt(status=0). Reservee aux cas
    ou l'executeur lui-meme ne peut pas fonctionner : bytecode absent
    la ou il est requis, contexte de bloc incoherent, incompatibilite
    de l'API py-evm.
    """


class BlockGasLimitExceeded(EVMError):
    """
    Le gas annonce par un bloc depasse BLOCK_GAS_LIMIT.

    Exception DELIBEREMENT distincte de ExecutionError. Ce n'est ni un
    bug d'infrastructure, ni un echec de transaction : c'est un bloc
    INVALIDE, au sens du consensus. La distinction compte parce que les
    trois cas appellent trois reactions differentes :

        ExecutionError      -> bug local, a investiguer.
        Receipt(status=0)   -> fait normal, le bloc reste valide.
        BlockGasLimitExceeded -> le bloc doit etre REJETE par tous.

    La condition est calculee sur les gas_limit ANNONCES, jamais sur le
    gas reellement consomme. C'est ce qui la rend verifiable sans rien
    executer, donc utilisable comme rempart anti-DoS : un bloc hostile
    est ecarte avant que la moindre instruction EVM ne tourne. Elle est
    aussi purement deterministe -- les trois noeuds lisent les memes
    entiers dans le meme ordre et concluent identiquement, sans fork
    possible.
    """


class AddressError(EVMError, CryptoAddressError):
    """
    Adresse EVM invalide.

    Double heritage deliberé. src.crypto.address definit DEJA une
    exception nommee AddressError, et la PHASE 1 leve celle-la. Deux
    classes homonymes dans un meme systeme sont un piege : selon le
    module importe, un `except AddressError` en attraperait une et
    laisserait passer l'autre, avec un plantage a l'execution sur les
    trois VMs pour seule alerte.

    Heriter des deux supprime le piege. Une adresse EVM invalide est
    interceptee aussi bien par un appelant qui connait la couche EVM
    (`except EVMError`) que par du code PHASE 1 existant
    (`except AddressError` depuis src.crypto.address). Aucun code deja
    ecrit ne change de comportement.

    L'alternative — reutiliser directement l'exception crypto — a ete
    ecartee : elle placerait hors de EVMError une erreur levee par
    src/evm/, brisant la garantie que toute la couche EVM est
    interceptable d'un seul bloc.
    """
