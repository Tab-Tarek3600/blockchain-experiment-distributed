// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.24;

/// @title PatientRegistry
/// @notice Stores only pseudonymous patient identifiers and their controller.
/// @dev No real-world identity or medical data is accepted by this contract.
contract PatientRegistry {
    struct Patient {
        address controller;
        uint256 registeredAt;
        bool active;
    }

    mapping(bytes32 => Patient) private _patients;

    error PatientAlreadyRegistered(bytes32 patientId);
    error PatientNotRegistered(bytes32 patientId);
    error PatientAlreadyInactive(bytes32 patientId);
    error NotController(bytes32 patientId, address caller);
    error InvalidController();

    event PatientRegistered(
        bytes32 indexed patientId,
        address indexed controller,
        uint256 registeredAt
    );

    event PatientDeactivated(
        bytes32 indexed patientId,
        address indexed controller,
        uint256 deactivatedAt
    );

    /// @notice Registers a pseudonymous patient identifier for msg.sender.
    function registerPatient(bytes32 patientId) external {
        if (msg.sender == address(0)) revert InvalidController();
        Patient storage patient = _patients[patientId];
        if (patient.controller != address(0)) {
            revert PatientAlreadyRegistered(patientId);
        }

        patient.controller = msg.sender;
        patient.registeredAt = block.timestamp;
        patient.active = true;

        emit PatientRegistered(patientId, msg.sender, block.timestamp);
    }

    /// @notice Deactivates a patient without deleting its historical entry.
    function deactivatePatient(bytes32 patientId) external {
        Patient storage patient = _patients[patientId];
        if (patient.controller == address(0)) {
            revert PatientNotRegistered(patientId);
        }
        if (patient.controller != msg.sender) {
            revert NotController(patientId, msg.sender);
        }
        if (!patient.active) {
            revert PatientAlreadyInactive(patientId);
        }

        patient.active = false;
        emit PatientDeactivated(patientId, msg.sender, block.timestamp);
    }

    function isRegistered(bytes32 patientId) external view returns (bool) {
        return _patients[patientId].controller != address(0);
    }

    function isActive(bytes32 patientId) external view returns (bool) {
        return _patients[patientId].active;
    }

    function controllerOf(bytes32 patientId) external view returns (address) {
        return _patients[patientId].controller;
    }

    /// @dev This checks both identity of the controller and active status.
    function isController(
        bytes32 patientId,
        address candidate
    ) external view returns (bool) {
        Patient storage patient = _patients[patientId];
        return patient.active && patient.controller == candidate;
    }
}
