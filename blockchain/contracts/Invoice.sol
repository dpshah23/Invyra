// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Invoice {
    struct InvoiceRecord {
        string invoiceNumber;
        string vendorName;
        string totalAmount;  // Storing as string to avoid formatting/floating point issues in Solidity
        string riskScore;    // The ML AI risk score
        string documentHash; // The unique fingerprint (e.g., SHA-256 hash of the invoice image)
        uint256 timestamp;
        address recordedBy;
    }

    // Mapping from unique document hash to the invoice record
    mapping(string => InvoiceRecord) private invoices;
    
    // To track if a document hash already exists
    mapping(string => bool) private hashExists;

    event InvoiceRecorded(string indexed documentHash, string invoiceNumber, string vendorName, uint256 timestamp);

    /**
     * @dev Store the fingerprint of an invoice on the blockchain.
     * @param _invoiceNumber The parsed invoice number
     * @param _vendorName The parsed vendor name
     * @param _totalAmount The parsed total amount
     * @param _riskScore The calculated risk score from ML model
     * @param _documentHash The unique fingerprint/hash of the invoice document
     */
    function recordInvoice(
        string memory _invoiceNumber,
        string memory _vendorName,
        string memory _totalAmount,
        string memory _riskScore,
        string memory _documentHash
    ) public {
        require(!hashExists[_documentHash], "Invoice with this fingerprint already exists on the ledger.");

        invoices[_documentHash] = InvoiceRecord({
            invoiceNumber: _invoiceNumber,
            vendorName: _vendorName,
            totalAmount: _totalAmount,
            riskScore: _riskScore,
            documentHash: _documentHash,
            timestamp: block.timestamp,
            recordedBy: msg.sender
        });

        hashExists[_documentHash] = true;

        emit InvoiceRecorded(_documentHash, _invoiceNumber, _vendorName, block.timestamp);
    }

    /**
     * @dev Fetch an invoice's recorded details using its document hash to detect tampering.
     * @param _documentHash The unique fingerprint/hash of the invoice document
     */
    function verifyInvoice(string memory _documentHash) public view returns (
        bool exists,
        string memory invoiceNumber,
        string memory vendorName,
        string memory totalAmount,
        string memory riskScore,
        uint256 timestamp,
        address recordedBy
    ) {
        if (!hashExists[_documentHash]) {
            return (false, "", "", "", "", 0, address(0));
        }

        InvoiceRecord memory record = invoices[_documentHash];
        return (
            true,
            record.invoiceNumber,
            record.vendorName,
            record.totalAmount,
            record.riskScore,
            record.timestamp,
            record.recordedBy
        );
    }
}