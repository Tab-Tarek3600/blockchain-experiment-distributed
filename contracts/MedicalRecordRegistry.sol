// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.24;

interface IPatientRegistryForRecords {
    function isActive(bytes32 patientId) external view returns (bool);

    function isController(bytes32 patientId, address candidate)
        external
        view
        returns (bool);

    function controllerOf(bytes32 patientId) external view returns (address);
}

interface IConsentManagerForRecords {
    function hasValidConsent(
        bytes32 patientId,
        address beneficiary,
        bytes32 scope
    ) external view returns (bool);
}

/// @title MedicalRecordRegistry
/// @notice Stores references and integrity metadata for encrypted records.
/// @dev The medical content and encryption keys remain outside the chain.
contract MedicalRecordRegistry {
    uint256 public constant MAX_CID_LENGTH = 256;

    struct MedicalRecord {
        bytes32 patientId;
        bytes cid;
        bytes32 encryptedContentHash;
        address registeredBy;
        uint256 createdAt;
        bool active;
        bytes32 scope;
    }

    IPatientRegistryForRecords public immutable patientRegistry;
    IConsentManagerForRecords public immutable consentManager;
    mapping(bytes32 => MedicalRecord) private _records;

    error InvalidRegistryAddress();
    error InvalidRecordId();
    error RecordAlreadyRegistered(bytes32 recordId);
    error PatientNotActive(bytes32 patientId);
    error UnauthorizedRecordRegistration(
        bytes32 patientId,
        address caller,
        bytes32 scope
    );
    error InvalidCid();
    error RecordNotFound(bytes32 recordId);
    error RecordAlreadyInactive(bytes32 recordId);
    error NotPatientController(bytes32 patientId, address caller);

    event RecordRegistered(
        bytes32 indexed recordId,
        bytes32 indexed patientId,
        address indexed registeredBy,
        bytes32 encryptedContentHash,
        bytes32 scope
    );

    event RecordRevoked(bytes32 indexed recordId, address indexed revokedBy);

    constructor(address patientRegistryAddress, address consentManagerAddress) {
        if (
            patientRegistryAddress == address(0) ||
            consentManagerAddress == address(0)
        ) {
            revert InvalidRegistryAddress();
        }
        patientRegistry = IPatientRegistryForRecords(patientRegistryAddress);
        consentManager = IConsentManagerForRecords(consentManagerAddress);
    }

    /// @notice Registers an IPFS/reference pointer and encrypted-content hash.
    function registerRecord(
        bytes32 recordId,
        bytes32 patientId,
        bytes calldata cid,
        bytes32 encryptedContentHash,
        bytes32 scope
    ) external {
        if (recordId == bytes32(0)) revert InvalidRecordId();
        if (_records[recordId].registeredBy != address(0)) {
            revert RecordAlreadyRegistered(recordId);
        }
        if (!patientRegistry.isActive(patientId)) {
            revert PatientNotActive(patientId);
        }
        if (cid.length == 0 || cid.length > MAX_CID_LENGTH) {
            revert InvalidCid();
        }

        bool controller = patientRegistry.isController(patientId, msg.sender);
        if (!controller && !consentManager.hasValidConsent(patientId, msg.sender, scope)) {
            revert UnauthorizedRecordRegistration(patientId, msg.sender, scope);
        }

        _records[recordId] = MedicalRecord({
            patientId: patientId,
            cid: cid,
            encryptedContentHash: encryptedContentHash,
            registeredBy: msg.sender,
            createdAt: block.timestamp,
            active: true,
            scope: scope
        });

        emit RecordRegistered(
            recordId,
            patientId,
            msg.sender,
            encryptedContentHash,
            scope
        );
    }

    /// @notice Revokes a reference while retaining its historical metadata.
    function revokeRecord(bytes32 recordId) external {
        MedicalRecord storage record = _records[recordId];
        if (record.registeredBy == address(0)) {
            revert RecordNotFound(recordId);
        }
        if (!record.active) {
            revert RecordAlreadyInactive(recordId);
        }
        if (patientRegistry.controllerOf(record.patientId) != msg.sender) {
            revert NotPatientController(record.patientId, msg.sender);
        }

        record.active = false;
        emit RecordRevoked(recordId, msg.sender);
    }

    function isRecordActive(bytes32 recordId) external view returns (bool) {
        return _records[recordId].active;
    }

    function getRecord(bytes32 recordId)
        external
        view
        returns (
            bytes32 patientId,
            bytes memory cid,
            bytes32 encryptedContentHash,
            address registeredBy,
            uint256 createdAt,
            bool active,
            bytes32 scope
        )
    {
        MedicalRecord storage record = _records[recordId];
        if (record.registeredBy == address(0)) {
            revert RecordNotFound(recordId);
        }
        return (
            record.patientId,
            record.cid,
            record.encryptedContentHash,
            record.registeredBy,
            record.createdAt,
            record.active,
            record.scope
        );
    }
}
