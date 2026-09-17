// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.24;

interface IPatientRegistryForConsent {
    function isController(bytes32 patientId, address candidate)
        external
        view
        returns (bool);

    function isActive(bytes32 patientId) external view returns (bool);
}

/// @title ConsentManager
/// @notice Stores scoped permissions without storing medical content.
contract ConsentManager {
    struct Consent {
        bool granted;
        uint256 expiresAt;
        uint256 grantedAt;
    }

    IPatientRegistryForConsent public immutable patientRegistry;
    mapping(bytes32 => mapping(address => mapping(bytes32 => Consent)))
        private _consents;

    error InvalidPatientRegistry();
    error NotController(bytes32 patientId, address caller);
    error InvalidBeneficiary();
    error ExpirationInPast(uint256 expiresAt);
    error ConsentNotFound(bytes32 patientId, address beneficiary, bytes32 scope);

    event ConsentGranted(
        bytes32 indexed patientId,
        address indexed beneficiary,
        bytes32 indexed scope,
        uint256 expiresAt
    );

    event ConsentRevoked(
        bytes32 indexed patientId,
        address indexed beneficiary,
        bytes32 indexed scope
    );

    constructor(address patientRegistryAddress) {
        if (patientRegistryAddress == address(0)) {
            revert InvalidPatientRegistry();
        }
        patientRegistry = IPatientRegistryForConsent(patientRegistryAddress);
    }

    /// @notice Grants or renews one explicit scoped permission.
    /// @dev expiresAt == 0 means no explicit expiration.
    function grantConsent(
        bytes32 patientId,
        address beneficiary,
        bytes32 scope,
        uint256 expiresAt
    ) external {
        _requireController(patientId);
        if (beneficiary == address(0)) revert InvalidBeneficiary();
        if (expiresAt != 0 && expiresAt <= block.timestamp) {
            revert ExpirationInPast(expiresAt);
        }

        _consents[patientId][beneficiary][scope] = Consent({
            granted: true,
            expiresAt: expiresAt,
            grantedAt: block.timestamp
        });

        emit ConsentGranted(patientId, beneficiary, scope, expiresAt);
    }

    /// @notice Revokes a permission. A later grant is a new explicit action.
    function revokeConsent(
        bytes32 patientId,
        address beneficiary,
        bytes32 scope
    ) external {
        _requireController(patientId);
        Consent storage consent = _consents[patientId][beneficiary][scope];
        if (!consent.granted) {
            revert ConsentNotFound(patientId, beneficiary, scope);
        }

        consent.granted = false;
        emit ConsentRevoked(patientId, beneficiary, scope);
    }

    function hasValidConsent(
        bytes32 patientId,
        address beneficiary,
        bytes32 scope
    ) external view returns (bool) {
        Consent storage consent = _consents[patientId][beneficiary][scope];
        if (!consent.granted || !patientRegistry.isActive(patientId)) {
            return false;
        }
        return consent.expiresAt == 0 || block.timestamp < consent.expiresAt;
    }

    function getConsent(
        bytes32 patientId,
        address beneficiary,
        bytes32 scope
    ) external view returns (bool granted, uint256 expiresAt, uint256 grantedAt) {
        Consent storage consent = _consents[patientId][beneficiary][scope];
        return (consent.granted, consent.expiresAt, consent.grantedAt);
    }

    function _requireController(bytes32 patientId) private view {
        if (!patientRegistry.isController(patientId, msg.sender)) {
            revert NotController(patientId, msg.sender);
        }
    }
}
