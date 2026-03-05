import hashlib
import json
import os
from web3 import Web3
from django.conf import settings


def get_web3_connection():
    """Connect to Ganache blockchain"""
    ganache_url = getattr(settings, 'GANACHE_URL', 'http://127.0.0.1:7545')
    w3 = Web3(Web3.HTTPProvider(ganache_url))
    
    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect to Ganache at {ganache_url}")
    
    return w3


def load_contract():
    """Load the compiled Invoice smart contract"""
    contract_path = os.path.join(
        settings.BASE_DIR,
        'blockchain',
        'build',
        'contracts',
        'Invoice.json'
    )
    
    if not os.path.exists(contract_path):
        raise FileNotFoundError(f"Contract JSON not found at {contract_path}. Run 'truffle migrate' first.")
    
    with open(contract_path, 'r') as f:
        contract_json = json.load(f)
    
    w3 = get_web3_connection()
    
    # Get contract address from networks (assumes network_id 5777 for Ganache)
    network_id = str(w3.net.version)
    networks = contract_json.get('networks', {})
    
    if network_id not in networks:
        raise ValueError(f"Contract not deployed on network {network_id}. Deploy with 'truffle migrate --reset'")
    
    contract_address = networks[network_id]['address']
    contract_abi = contract_json['abi']
    
    return w3.eth.contract(address=contract_address, abi=contract_abi), w3


def calculate_document_hash(invoice_data):
    """
    Calculate SHA-256 hash of invoice data for blockchain fingerprinting
    
    Args:
        invoice_data: dict containing invoice details
    
    Returns:
        str: SHA-256 hash string
    """
    # Create deterministic string from invoice key fields
    hash_string = (
        f"{invoice_data.get('invoice_number', '')}"
        f"{invoice_data.get('vendor_name', '')}"
        f"{invoice_data.get('total_amount', '')}"
        f"{invoice_data.get('invoice_date', '')}"
        f"{invoice_data.get('raw_text', '')[:500]}"  # First 500 chars of OCR text
    )
    
    # Calculate SHA-256 hash
    doc_hash = hashlib.sha256(hash_string.encode('utf-8')).hexdigest()
    return doc_hash


def record_invoice_on_blockchain(invoice_data, from_account=None):
    """
    Record invoice fingerprint on blockchain
    
    Args:
        invoice_data: dict with keys: invoice_number, vendor_name, total_amount, risk_score
        from_account: Ethereum account address (default: first Ganache account)
    
    Returns:
        dict: {
            'success': bool,
            'tx_hash': str,
            'document_hash': str,
            'block_number': int,
            'error': str (if failed)
        }
    """
    try:
        contract, w3 = load_contract()
        
        # Use first account if not specified
        if from_account is None:
            from_account = w3.eth.accounts[0]
        
        # Calculate document hash
        document_hash = calculate_document_hash(invoice_data)
        
        # Prepare transaction
        tx_hash = contract.functions.recordInvoice(
            str(invoice_data.get('invoice_number', '')),
            str(invoice_data.get('vendor_name', '')),
            str(invoice_data.get('total_amount', '')),
            str(invoice_data.get('risk_score', '0.0')),
            document_hash
        ).transact({'from': from_account})
        
        # Wait for transaction receipt
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        return {
            'success': tx_receipt['status'] == 1,
            'tx_hash': tx_hash.hex(),
            'document_hash': document_hash,
            'block_number': tx_receipt['blockNumber'],
            'gas_used': tx_receipt['gasUsed'],
            'error': None
        }
        
    except Exception as e:
        return {
            'success': False,
            'tx_hash': None,
            'document_hash': calculate_document_hash(invoice_data),
            'block_number': None,
            'error': str(e)
        }


def verify_invoice_on_blockchain(document_hash):
    """
    Verify if invoice exists on blockchain and retrieve details
    
    Args:
        document_hash: SHA-256 hash of invoice document
    
    Returns:
        dict: Invoice details from blockchain or None if not found
    """
    try:
        contract, w3 = load_contract()
        
        result = contract.functions.verifyInvoice(document_hash).call()
        
        # Result tuple: (exists, invoiceNumber, vendorName, totalAmount, riskScore, timestamp, recordedBy)
        if result[0]:  # exists
            return {
                'exists': True,
                'invoice_number': result[1],
                'vendor_name': result[2],
                'total_amount': result[3],
                'risk_score': result[4],
                'timestamp': result[5],
                'recorded_by': result[6],
            }
        else:
            return {'exists': False}
            
    except Exception as e:
        return {
            'exists': False,
            'error': str(e)
        }
