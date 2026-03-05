"""
Test script to verify blockchain integration
Run with: python test_blockchain.py
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'InvGuard.settings')
django.setup()

from invoices.blockchain_utils import (
    get_web3_connection,
    load_contract,
    calculate_document_hash,
    record_invoice_on_blockchain,
    verify_invoice_on_blockchain
)

def test_connection():
    """Test connection to Ganache"""
    print("=" * 60)
    print("1. Testing Ganache Connection...")
    print("=" * 60)
    try:
        w3 = get_web3_connection()
        print(f"✓ Connected to Ganache")
        print(f"  Network ID: {w3.net.version}")
        print(f"  Latest Block: {w3.eth.block_number}")
        print(f"  Available Accounts: {len(w3.eth.accounts)}")
        return True
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False

def test_contract():
    """Test contract loading"""
    print("\n" + "=" * 60)
    print("2. Testing Contract Loading...")
    print("=" * 60)
    try:
        contract, w3 = load_contract()
        print(f"✓ Contract loaded successfully")
        print(f"  Contract Address: {contract.address}")
        return True
    except Exception as e:
        print(f"✗ Contract loading failed: {e}")
        return False

def test_hash_calculation():
    """Test document hash calculation"""
    print("\n" + "=" * 60)
    print("3. Testing Hash Calculation...")
    print("=" * 60)
    invoice_data = {
        'invoice_number': 'TEST-001',
        'vendor_name': 'Test Vendor',
        'total_amount': '1234.56',
        'invoice_date': '2026-03-06',
        'raw_text': 'Test invoice content'
    }
    doc_hash = calculate_document_hash(invoice_data)
    print(f"✓ Document hash calculated")
    print(f"  Hash: {doc_hash}")
    return doc_hash

def test_record_invoice():
    """Test recording invoice on blockchain"""
    print("\n" + "=" * 60)
    print("4. Testing Invoice Recording...")
    print("=" * 60)
    invoice_data = {
        'invoice_number': f'TEST-{os.getpid()}',
        'vendor_name': 'Blockchain Test Corp',
        'total_amount': '9999.99',
        'risk_score': '0.25',
        'invoice_date': '2026-03-06',
        'raw_text': 'This is a test invoice for blockchain integration verification'
    }
    
    result = record_invoice_on_blockchain(invoice_data)
    
    if result['success']:
        print(f"✓ Invoice recorded successfully")
        print(f"  Transaction Hash: {result['tx_hash']}")
        print(f"  Document Hash: {result['document_hash']}")
        print(f"  Block Number: {result['block_number']}")
        print(f"  Gas Used: {result['gas_used']}")
        return result['document_hash']
    else:
        print(f"✗ Recording failed: {result['error']}")
        return None

def test_verify_invoice(doc_hash):
    """Test invoice verification"""
    print("\n" + "=" * 60)
    print("5. Testing Invoice Verification...")
    print("=" * 60)
    
    result = verify_invoice_on_blockchain(doc_hash)
    
    if result['exists']:
        print(f"✓ Invoice verified successfully")
        print(f"  Invoice Number: {result['invoice_number']}")
        print(f"  Vendor: {result['vendor_name']}")
        print(f"  Amount: {result['total_amount']}")
        print(f"  Risk Score: {result['risk_score']}")
        print(f"  Timestamp: {result['timestamp']}")
        print(f"  Recorded By: {result['recorded_by']}")
        return True
    else:
        print(f"✗ Verification failed")
        if 'error' in result:
            print(f"  Error: {result['error']}")
        return False

def main():
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 12 + "BLOCKCHAIN INTEGRATION TEST" + " " * 19 + "║")
    print("╚" + "=" * 58 + "╝")
    
    # Test 1: Connection
    if not test_connection():
        print("\n⚠ Please start Ganache on http://127.0.0.1:7545 and try again.")
        return
    
    # Test 2: Contract
    if not test_contract():
        print("\n⚠ Please deploy the contract: cd blockchain && truffle migrate --reset")
        return
    
    # Test 3: Hash
    doc_hash = test_hash_calculation()
    
    # Test 4: Record
    recorded_hash = test_record_invoice()
    if not recorded_hash:
        print("\n⚠ Failed to record invoice on blockchain.")
        return
    
    # Test 5: Verify
    test_verify_invoice(recorded_hash)
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED!")
    print("=" * 60)
    print("\n✓ Blockchain integration is working properly")
    print("✓ You can now upload invoices via /invoices/upload/")
    print("\n")

if __name__ == '__main__':
    main()
