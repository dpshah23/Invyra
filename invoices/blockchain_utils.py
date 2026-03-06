import hashlib
import json
import os
from web3 import Web3
from django.conf import settings


def get_web3_connection():
    """Connect to blockchain RPC (Ganache for dev, testnet/mainnet for hosted RPC)."""
    # Backward compatible fallback order: BLOCKCHAIN_RPC_URL -> GANACHE_URL -> local default.
    blockchain_url = (
        getattr(settings, 'BLOCKCHAIN_RPC_URL', '')
        or os.getenv('BLOCKCHAIN_RPC_URL', '')
        or getattr(settings, 'GANACHE_URL', '')
        or os.getenv('GANACHE_URL', 'http://127.0.0.1:7545')
    )
    
    w3 = Web3(Web3.HTTPProvider(blockchain_url))
    
    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect to blockchain at {blockchain_url}")
    
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
    
    # Prefer explicit contract address from env/settings for hosted networks.
    configured_contract_address = (
        getattr(settings, 'BLOCKCHAIN_CONTRACT_ADDRESS', '')
        or os.getenv('BLOCKCHAIN_CONTRACT_ADDRESS', '')
    ).strip()

    if configured_contract_address:
        if not Web3.is_address(configured_contract_address):
            raise ValueError("BLOCKCHAIN_CONTRACT_ADDRESS is invalid.")
        contract_address = Web3.to_checksum_address(configured_contract_address)
    else:
        network_id = str(w3.net.version)
        networks = contract_json.get('networks', {})

        if network_id not in networks:
            raise ValueError(
                f"Contract not deployed on network {network_id}. "
                "Set BLOCKCHAIN_CONTRACT_ADDRESS or deploy with truffle migrate on this network."
            )

        contract_address = networks[network_id]['address']

    contract_abi = contract_json['abi']
    
    return w3.eth.contract(address=contract_address, abi=contract_abi), w3


def _get_signer_private_key():
    """Load signer private key for remote RPC transactions."""
    return (
        getattr(settings, 'BLOCKCHAIN_SIGNER_PRIVATE_KEY', '')
        or os.getenv('BLOCKCHAIN_SIGNER_PRIVATE_KEY', '')
    ).strip()


def _build_fee_fields(w3):
    """Build EIP-1559 fee fields when supported, fallback to gasPrice."""
    latest_block = w3.eth.get_block('latest')
    base_fee = latest_block.get('baseFeePerGas')

    if base_fee is None:
        return {'gasPrice': w3.eth.gas_price}

    try:
        priority_fee_gwei = int(
            getattr(settings, 'BLOCKCHAIN_PRIORITY_FEE_GWEI', '')
            or os.getenv('BLOCKCHAIN_PRIORITY_FEE_GWEI', '2')
        )
    except ValueError:
        priority_fee_gwei = 2

    max_priority_fee = w3.to_wei(priority_fee_gwei, 'gwei')
    max_fee = (base_fee * 2) + max_priority_fee
    return {
        'maxPriorityFeePerGas': max_priority_fee,
        'maxFeePerGas': max_fee,
    }


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
    document_hash = calculate_document_hash(invoice_data)

    try:
        contract, w3 = load_contract()

        tx_function = contract.functions.recordInvoice(
            str(invoice_data.get('invoice_number', '')),
            str(invoice_data.get('vendor_name', '')),
            str(invoice_data.get('total_amount', '')),
            str(invoice_data.get('risk_score', '0.0')),
            document_hash
        )

        signer_private_key = _get_signer_private_key()

        if signer_private_key:
            # Hosted RPC (Alchemy/Infura) path: sign transaction locally.
            signer = w3.eth.account.from_key(signer_private_key)
            sender_address = signer.address
            nonce = w3.eth.get_transaction_count(sender_address)

            tx_params = {
                'from': sender_address,
                'nonce': nonce,
                'chainId': w3.eth.chain_id,
            }
            tx_params.update(_build_fee_fields(w3))

            try:
                tx_params['gas'] = int(tx_function.estimate_gas({'from': sender_address}) * 1.2)
            except Exception:
                tx_params['gas'] = 300000

            unsigned_tx = tx_function.build_transaction(tx_params)
            signed_tx = w3.eth.account.sign_transaction(unsigned_tx, signer_private_key)
            raw_tx = getattr(signed_tx, 'rawTransaction', None) or getattr(signed_tx, 'raw_transaction')
            tx_hash = w3.eth.send_raw_transaction(raw_tx)
        else:
            # Local Ganache path with unlocked accounts.
            if from_account is None:
                available_accounts = w3.eth.accounts
                if not available_accounts:
                    raise ValueError(
                        "No unlocked account available. Set BLOCKCHAIN_SIGNER_PRIVATE_KEY for hosted RPC."
                    )
                from_account = available_accounts[0]

            tx_hash = tx_function.transact({'from': from_account})
        
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
            'document_hash': document_hash,
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
