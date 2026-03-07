"""
Fraud Detection Testing Script
Tests various fraud scenarios against the fraud detection system.
Usage: python test_fraud_scenarios.py
"""

import os
import json
import django
import requests
from io import BytesIO
from PIL import Image, ImageDraw

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'InvGuard.settings')
django.setup()

from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from auth1.models import UserCustom as User
from invoices.models import invoices

# Configuration
BASE_URL = "http://127.0.0.1:8000"
FRAUD_API = f"{BASE_URL}/fraud_detection/detect-risk/"

# Load fraud scenarios
with open('fraud_transaction_samples.json', 'r') as f:
    scenarios_file = json.load(f)
    FRAUD_SCENARIOS = scenarios_file['fraud_scenarios']


def create_test_invoice_image(invoice_data, filename="test_invoice.png"):
    """Create a sample invoice image with given data"""
    img = Image.new('RGB', (1200, 800), 'white')
    draw = ImageDraw.Draw(img)
    
    y = 30
    draw.text((30, y), "INVOICE", fill='black')
    y += 50
    
    draw.text((30, y), f"Invoice #: {invoice_data['invoice_number']}", fill='black')
    y += 30
    draw.text((30, y), f"Vendor: {invoice_data['vendor_name']}", fill='black')
    y += 30
    draw.text((30, y), f"Invoice Date: {invoice_data['invoice_date']}", fill='black')
    y += 30
    draw.text((30, y), f"Due Date: {invoice_data['due_date']}", fill='black')
    y += 30
    draw.text((30, y), f"Total Amount: {invoice_data['currency']} {invoice_data['total_amount']}", fill='black')
    y += 30
    draw.text((30, y), f"Bank Account: {invoice_data['bank_account']}", fill='black')
    y += 30
    draw.text((30, y), f"OCR Confidence: {invoice_data.get('ocr_confidence', 0.90):.0%}", fill='black')
    
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def test_fraud_scenario(scenario):
    """Test a single fraud scenario via API"""
    print(f"\n{'='*80}")
    print(f"Testing: {scenario['name']} (ID: {scenario['id']})")
    print(f"{'='*80}")
    print(f"Description: {scenario['description']}\n")
    print(f"Fraud Indicators:")
    for indicator in scenario['fraud_indicators']:
        print(f"  • {indicator}")
    
    # Prepare payload
    payload = scenario['payload']
    
    # Test via fraud detection API
    print(f"\n[API Test] POST {FRAUD_API}")
    print(f"Payload: {json.dumps(payload, indent=2)}\n")
    
    try:
        response = requests.post(
            FRAUD_API,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"[✓ SUCCESS] Response Status: {response.status_code}\n")
            print(f"Risk Analysis Results:")
            print(f"  Risk Score:     {result.get('risk_score', 'N/A'):.4f}")
            print(f"  Risk Label:     {result.get('risk_label', 'N/A').upper()}")
            print(f"  Is Fraud:       {result.get('is_fraud', False)}")
            print(f"  Reason:         {result.get('reason', 'N/A')}")
            print(f"  Model Version:  {result.get('model_version', 'N/A')}\n")
            
            # Compare with expected values
            expected_score = scenario.get('expected_risk_score', 0.0)
            expected_label = scenario.get('expected_label', 'unknown')
            actual_score = result.get('risk_score', 0.0)
            actual_label = result.get('risk_label', 'unknown')
            
            score_match = abs(actual_score - expected_score) < 0.2
            label_match = actual_label == expected_label
            
            print(f"Expected vs Actual:")
            print(f"  Expected Score: {expected_score:.4f} | Actual: {actual_score:.4f} | Match: {score_match}")
            print(f"  Expected Label: {expected_label.upper()} | Actual: {actual_label.upper()} | Match: {label_match}")
            
            if score_match and label_match:
                print(f"\n[✓ DETECTION WORKING] Fraud correctly identified!")
            elif label_match:
                print(f"\n[⚠ PARTIAL MATCH] Label correct but score variance (OK for ML models)")
            else:
                print(f"\n[⚠ DETECTION ISSUE] Expected {expected_label.upper()}, got {actual_label.upper()}")
        else:
            print(f"[✗ ERROR] Status: {response.status_code}")
            print(f"Response: {response.text}")
    
    except Exception as e:
        print(f"[✗ EXCEPTION] {type(e).__name__}: {str(e)}")
        print("Make sure the Django server is running at http://127.0.0.1:8000")


def main():
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*20 + "INVYRA FRAUD DETECTION TEST SUITE" + " "*24 + "║")
    print("╚" + "="*78 + "╝")
    
    print("\n[INFO] This script tests fraud detection against various scenarios.")
    print("[INFO] Ensure Django server is running: python manage.py runserver\n")
    
    # Group scenarios by fraud vs legitimate
    fraud_scenarios = [s for s in FRAUD_SCENARIOS if s['id'].startswith('FRAUD')]
    legit_scenarios = [s for s in FRAUD_SCENARIOS if s['id'].startswith('LEGIT')]
    
    print(f"Total Scenarios: {len(FRAUD_SCENARIOS)}")
    print(f"  - Fraudulent: {len(fraud_scenarios)}")
    print(f"  - Legitimate: {len(legit_scenarios)}\n")
    
    # Test all scenarios
    for scenario in FRAUD_SCENARIOS:
        test_fraud_scenario(scenario)
    
    # Summary
    print(f"\n\n{'='*80}")
    print("TEST SUITE COMPLETE")
    print(f"{'='*80}")
    print("""
Next Steps:
1. Review detection accuracy for each scenario
2. Note any false positives or false negatives
3. Adjust ML model thresholds if needed (fraud_detection/views.py)
4. Document any operational tuning performed

For manual testing:
- Upload invoices via /invoices/upload/ dashboard
- Check /invoices/<invoice_id>/ for detailed results
- View fraud analysis history in admin panel (/admin/)

For API integration:
- Use the POST /fraud_detection/detect-risk/ endpoint
- Required fields: username, invoice_number, total_amount, currency
- Returns: risk_score, risk_label, is_fraud, reason
""")


if __name__ == '__main__':
    main()
