"""
Adresses EVM : constantes, validation et derivation d'adresse de contrat.

Point d'architecture essentiel : AUCUNE conversion n'est necessaire
entre les adresses du projet et celles de l'EVM.

    src.crypto.address.public_key_to_address(pk) = sha256(pk)[-20:]

produit deja 20 octets, exactement la largeur d'une adresse EVM. Une
adresse derivee d'une cle publique ML-DSA est donc directement
utilisable comme adresse de compte, sans mapping ni table de
correspondance. C'est une propriete heritee de la PHASE 1, pas une
coincidence a exploiter au hasard : elle est verifiee par les tests.

Sur les imports : ce module utilise `rlp` et `eth_utils.keccak`, mais
JAMAIS `eth.*` (py-evm lui-meme). La regle d'isolation vise l'API beta
et instable de py-evm, confinee a src/evm/state.py. `rlp` et
`eth_utils` sont des paquets distincts, epingles dans requirements.txt,
dont l'API est stable depuis des annees.
"""

from __future__ import annotations

import rlp
from eth_utils import keccak

from src.crypto.address import ADDRESS_LENGTH
from src.crypto.address import address_to_hex as _crypto_address_to_hex
from src.crypto.address import is_valid_address as _crypto_is_valid_address
from src.evm.errors import AddressError

# --- Constantes -------------------------------------------------------

# ADDRESS_LENGTH est IMPORTEE de src.crypto.address, pas redefinie.
# La redefinir creerait deux constantes pouvant diverger en silence ;
# l'importer rend l'egalite des deux formats structurelle plutot que
# simplement constatee. Elle est reexportee ici pour que les modules
# EVM n'aient pas a dependre de la couche crypto pour une largeur
# d'adresse.

#: Adresse nulle. Utilisee comme destinataire pour signaler un
#: DEPLOIEMENT de contrat : une transaction dont recipient vaut
#: ZERO_ADDRESS transporte son initcode dans le champ `data`.
#:
#: Convention retenue faute d'alternative : Transaction.recipient est
#: valide par _validate_address_field(), qui impose exactement 20
#: octets et interdit donc `None`. Modifier Transaction pour autoriser
#: un destinataire absent reviendrait a toucher src/blockchain/, ce que
#: l'architecture proscrit. L'adresse nulle joue donc ce role, comme
#: dans plusieurs chaines EVM.
ZERO_ADDRESS = b"\x00" * ADDRESS_LENGTH


# --- Validation -------------------------------------------------------

def is_valid_address(address: object) -> bool:
    """
    Indique si `address` est une adresse EVM bien formee.

    Reexportee depuis src.crypto.address : meme predicat, importe pour
    eviter deux implementations d'une meme regle.
    """
    return _crypto_is_valid_address(address)


def validate_address(address: object, name: str = "address") -> bytes:
    """
    Valide une adresse et la retourne telle quelle.

    Retourner la valeur permet l'usage en ligne :
        sender = validate_address(tx.sender, "sender")

    Raises:
        AddressError: Si l'adresse n'est pas 20 octets exactement.
    """
    if not isinstance(address, bytes):
        raise AddressError(f"{name} must be bytes, got {type(address).__name__}")

    if len(address) != ADDRESS_LENGTH:
        raise AddressError(
            f"{name} must contain exactly {ADDRESS_LENGTH} bytes, "
            f"got {len(address)}"
        )

    return address


def is_zero_address(address: object) -> bool:
    """
    Indique si `address` est l'adresse nulle.

    Sert a distinguer un deploiement de contrat d'un appel ordinaire.
    Ne leve jamais : une valeur malformee n'est simplement pas
    l'adresse nulle, la validation est du ressort de l'appelant.
    """
    return address == ZERO_ADDRESS


# --- Derivation d'adresse de contrat ----------------------------------

def generate_contract_address(sender: bytes, nonce: int) -> bytes:
    """
    Calcule l'adresse d'un contrat cree par `sender` avec `nonce`.

    Formule Ethereum standard (CREATE) :

        address = keccak256(rlp([sender, nonce]))[-20:]

    Cette implementation a ete verifiee identique a
    eth._utils.address.generate_contract_address de py-evm sur les cas
    limites du codage RLP des entiers : 0, 127, 128, 255, 256 et 2**32.
    Elle est reimplementee ici plutot qu'importee afin de ne pas
    dependre d'un module prive de py-evm (`eth._utils`), dont rien ne
    garantit la stabilite entre deux versions beta.

    Determinisme : deux noeuds executant la meme transaction obtiennent
    forcement la meme adresse de contrat, puisque `sender` et `nonce`
    proviennent de l'etat, lui-meme issu d'une chaine identique. C'est
    la condition pour que les trois VMs referencent le meme contrat.

    Args:
        sender: Adresse du compte qui deploie (20 octets).
        nonce: Nonce du compte AVANT incrementation.

    Raises:
        AddressError: Si `sender` est malformee ou `nonce` invalide.
    """
    validate_address(sender, "sender")

    # isinstance(True, int) vaut True en Python : le booleen doit etre
    # exclu explicitement, sinon generate_contract_address(addr, True)
    # calculerait silencieusement l'adresse du nonce 1.
    if isinstance(nonce, bool) or not isinstance(nonce, int):
        raise AddressError("nonce must be an integer")

    if nonce < 0:
        raise AddressError("nonce must be >= 0")

    return keccak(rlp.encode([sender, nonce]))[-ADDRESS_LENGTH:]


# --- Confort d'affichage ----------------------------------------------

def address_to_hex(address: bytes) -> str:
    """
    Representation '0x...' d'une adresse, pour les journaux.

    Delegue a src.crypto.address : formatage identique des deux cotes,
    ce qui evite que les journaux EVM et PHASE 1 divergent.
    """
    return _crypto_address_to_hex(address)


def short_hex(address: bytes) -> str:
    """
    Forme abregee '0x1122..ffee', lisible dans les journaux.

    Les journaux du noeud impriment beaucoup d'adresses ; 40 caracteres
    hexadecimaux rendent une ligne illisible.
    """
    validate_address(address)
    full = address.hex()
    return f"0x{full[:4]}..{full[-4:]}"
