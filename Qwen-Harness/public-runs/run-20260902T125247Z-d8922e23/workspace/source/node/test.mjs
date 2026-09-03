// Node's bare `node --test` discovery matches test.mjs but not test_*.mjs;
// this shim keeps `npm test` / `node --test` working while the graded suite
// stays in test_payload_contract.mjs as required by the deliverable contract.
import "./test_payload_contract.mjs";
