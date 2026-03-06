# 🏛️ Invyra - Architecture & Technical Deep Dive

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    CLIENT LAYER (Frontend)                  │
│  HTML5 | CSS3 | JavaScript | Ethers.js (Blockchain UI)      │
│  • Login/Signup Pages                                       │
│  • Invoice Upload Interface                                 │
│  • Dashboard & Analytics Views                              │
│  • Wallet Connection (MetaMask)                             │
└─────────────────┬───────────────────────────────────────────┘
                  │ HTTPS/TLS 1.3
                  │
┌─────────────────▼───────────────────────────────────────────┐
│                  API LAYER (Django Backend)                 │
│  Django 5.1.x | Gunicorn WSGI Server | Nginx Reverse Proxy  │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Authentication & Authorization (auth1 app)             │ │
│  │ • User registration & login                            │ │
│  │ • Session management with CSRF protection              │ │
│  │ • Guest session middleware                             │ │
│  │ • Role-based access control (Free/Pro/Enterprise)      │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Invoice Processing (invoices app)                      │ │
│  │ • File upload handling & validation                    │ │
│  │ • Tesseract OCR integration                            │ │
│  │ • Data extraction & normalization                      │ │
│  │ • Blockchain integration                               │ │
│  │ • Invoice model & ORM                                  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Fraud Detection (fraud_detection app)                  │ │
│  │ • ML model inference (Scikit-learn)                    │ │
│  │ • Anomaly scoring algorithm                            │ │
│  │ • Risk explanation generation                          │ │
│  │ • Vendor history analysis                              │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Subscription & Billing (subscriptions app)             │ │
│  │ • Stripe integration (checkout & webhooks)             │ │
│  │ • Plan management (Free/Pro/Enterprise)                │ │
│  │ • Usage tracking & limit enforcement                   │ │
│  │ • Invoice generation                                   │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Dashboard & Analytics (home app)                       │ |
│  │ • User dashboard rendering                             │ │
│  │ • Report generation                                    │ │
│  │ • Public homepage                                      │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Admin Interface (Django Jazzmin)                       │ │
│  │ • Content management                                   │ │
│  │ • User & subscription management                       │ │
│  │ • System monitoring                                    │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────┬──────────────────────────────────────┬────────┘
              │                                      │
    ┌─────────▼──────────┐               ┌──────────▼─────────┐
    │  DATA LAYER        │               │  BLOCKCHAIN LAYER  │
    │                    │               │                    │
    │ PostgreSQL DB      │               │ Ethereum Sepolia   │
    │ • Users            │               │ • Smart Contract   │
    │ • Invoices         │               │ • Invoice Hash     │
    │ • Fraud Records    │               │ • Cryptographic    │
    │ • Subscriptions    │               │   Verification     │
    │ • Vendor History   │               │ • Transaction Log  │
    │ • Audit Logs       │               │                    │
    │                    │               │ Alchemy RPC Node   │
    │                    │               │ (Sepolia Testnet)  │
    └────────────────────┘               └────────────────────┘
```

---

## Data Flow Diagram

### Invoice Upload to Verification Flow

```
1. USER UPLOADS INVOICE
   └─> POST /invoices/upload/
       • File validation (size, type)
       • CSRF protection
       • Session/user verification
       • Plan limit check

2. OCR PROCESSING (invoices/ocr_processor.py)
   └─> Tesseract Engine (C binary)
       • PDF/Image to text conversion
       • Confidence scoring
       • Multi-page handling
       • Error handling & logging

3. DATA EXTRACTION
   └─> Regex & NLP Processing
       • Vendor name extraction
       • Invoice number identification
       • Amount parsing (with currency)
       • Bank account detection
       • Date normalization
       • Duplicate field handling
       
       Output: Structured JSON
       {
         "vendor_name": "Acme Corp",
         "invoice_number": "INV-2026-001",
         "invoice_date": "2026-03-06",
         "amount": 5000.00,
         "currency": "USD",
         "bank_account": "****1234",
         "confidence": 0.94
       }

4. DATABASE STORAGE
   └─> Save Extracted Data
       • Create Invoice record in PostgreSQL
       • Link to user (or guest session)
       • Store extracted fields
       • Track processing timestamp
       • Log OCR quality metrics

5. FRAUD ANALYSIS (invoices/fraud_ml.py)
   └─> Run ML Anomaly Detection
       
       a) Historical Comparison
          • Fetch vendor history from DB
          • Compare invoice amount (Z-score)
          • Check bank account consistency
          • Validate frequency patterns
       
       b) Pattern Matching
          • Regex for phone/email validity
          • Bank account format validation
          • Invoice numbering consistency
          • Date reasonableness checks
       
       c) ML Scoring (Scikit-learn)
          • Isolation Forest algorithm
          • Multi-feature anomaly scoring
          • Weighted feature importance
          • Confidence threshold checking
       
       Output: Risk Score 0-100
       {
         "risk_score": 35,
         "risk_level": "low",
         "confidence": 0.95,
         "fraud_factors": [
           {
             "type": "amount_deviation",
             "severity": "low",
             "message": "5% above vendor average"
           }
         ]
       }

6. BLOCKCHAIN RECORDING (invoices/blockchain_utils.py)
   └─> Create Immutable Proof
       
       a) Hash Generation
          • Combine: vendor_name + amount + date + account
          • Apply Keccak-256 hash
          • Create unique fingerprint
       
       b) Transaction Building (EIP-1559)
          • Load private key from env
          • Build transaction struct:
            {
              to: CONTRACT_ADDRESS,
              data: recordInvoice(hash, riskLevel),
              value: 0,
              gasLimit: 500000,
              maxFeePerGas: base_fee + priority_fee,
              maxPriorityFeePerGas: 2 Gwei
            }
       
       c) Signing
          • Sign with Keccak-256(tx_data)
          • Return signed transaction
       
       d) RPC Submission
          • Send to Alchemy Sepolia endpoint
          • Monitor tx mempool
          • Wait for confirmation (typically 15-20s)
       
       e) Verification
          • Query transaction receipt
          • Verify block inclusion
          • Store tx_hash in DB
          • Link to invoice record

7. RESULTS COMPILATION
   └─> Combine All Data
       {
         "invoice_id": "inv_12345",
         "status": "verified",
         "extraction": { ... },
         "fraud_analysis": { ... },
         "blockchain": {
           "tx_hash": "0xabc...",
           "block_number": 4234567,
           "status": "confirmed"
         },
         "timestamp": "2026-03-06T16:30:00Z"
       }

8. USER NOTIFICATION
   └─> Display Results
       • Show risk score & explanation
       • Display extracted data
       • Confirm blockchain verification
       • Offer upgrade if needed
       • Store in user dashboard
```

---

## Database Schema

```sql
-- Authentication & Users
TABLE auth1_usercustom {
  id (PK)
  username (UNIQUE)
  email (UNIQUE)
  password_hash (bcrypt)
  first_name
  last_name
  company_name
  created_at
  updated_at
  is_active (boolean)
  is_staff (boolean)
  subscription_id (FK) -> subscription
}

-- Invoice Management
TABLE invoices_invoice {
  id (PK)
  user_id (FK) -> auth_user [NULLABLE for guest]
  guest_session_id (UUID) [NULLABLE]
  filename
  file_path
  upload_timestamp
  
  -- Extracted Data
  vendor_name
  invoice_number (UNIQUE per user)
  invoice_date
  amount (DECIMAL)
  currency
  bank_account (ENCRYPTED)
  line_items (JSON)
  
  -- Processing Status
  status (CHOICE: 'processing', 'verified', 'fraud', 'error')
  ocr_confidence (DECIMAL 0-1)
  extraction_quality_score
  
  -- Fraud Analysis
  risk_score (INTEGER 0-100)
  risk_level (CHOICE: 'low', 'medium', 'high')
  fraud_explanation (TEXT)
  fraud_factors (JSON)
  
  -- Blockchain
  blockchain_tx_hash
  blockchain_block_number
  blockchain_proof_hash
  blockchain_timestamp
  
  -- Audit
  created_at
  updated_at
  processed_at
  created_by_ip
}

-- Fraud Records & Analysis
TABLE fraud_detection_fraudrecord {
  id (PK)
  invoice_id (FK) -> invoices_invoice
  user_id (FK) -> auth_user
  fraud_score
  fraud_type (CHOICE)
  factors (JSON)
  is_confirmed (boolean)
  confirmed_by (FK) -> auth_user [NULLABLE]
  false_positive (boolean)
  created_at
}

-- Vendor History
TABLE fraud_detection_vendorhistory {
  id (PK)
  vendor_name (UNIQUE)
  total_invoices (INTEGER)
  total_amount (DECIMAL)
  average_amount (DECIMAL)
  amount_std_dev (DECIMAL)
  invoice_frequency_days (INTEGER)
  common_bank_accounts (JSON array)
  fraud_count
  last_processed_date
  created_at
  updated_at
}

-- Subscriptions & Plans
TABLE subscriptions_subscription {
  id (PK)
  user_id (FK) -> auth_user (UNIQUE)
  plan_type (CHOICE: 'free', 'pro', 'enterprise')
  plan_limit (INTEGER: invoices/month)
  
  -- Stripe Integration
  stripe_customer_id
  stripe_subscription_id
  
  -- Lifecycle
  started_date
  renewal_date
  is_active (boolean)
  
  -- Tracking
  invoices_used_this_month (INTEGER)
  created_at
  updated_at
}

-- Audit Logs
TABLE audit_log {
  id (PK)
  user_id (FK) [NULLABLE]
  action (VARCHAR)
  resource_type (VARCHAR)
  resource_id
  changes (JSON)
  ip_address
  user_agent
  timestamp
}
```

---

## Authentication & Authorization Flow

```
┌──────────────────────────────────────────────────────────┐
│           REQUEST ARRIVES AT DJANGO                       │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│   CSRF MIDDLEWARE                                         │
│   (CsrfViewMiddleware)                                    │
│   ✓ Validates CSRF token in form/header                 │
│   ✓ Prevents cross-site form submissions                │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│   SESSION MIDDLEWARE                                      │
│   (SessionMiddleware)                                     │
│   ✓ Extract session ID from cookie                      │
│   ✓ Load session data from cache/DB                     │
│   ✓ Available as request.session dict                   │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│   GUEST SESSION MIDDLEWARE                                │
│   (GuestSessionMiddleware - Custom)                       │
│   ✓ Detect unauthenticated users                        │
│   ✓ Generate UUID for guest session                     │
│   ✓ Set 30-minute expiration                            │
│   ✓ Store in request.session['guest_session_id']        │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│   AUTHENTICATION MIDDLEWARE                               │
│   (AuthenticationMiddleware)                              │
│   ✓ Populate request.user (User object or AnonymousUser)│
│   ✓ Check user permissions                              │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│   VIEW/DECORATOR AUTHORIZATION                           │
│   • Check request.user.is_authenticated                  │
│   • Verify subscription tier                             │
│   • Enforce plan limits                                  │
│   • Check guest vs registered                           │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│   PLAN LIMIT ENFORCEMENT                                 │
│   (In Views & before DB operations)                      │
│                                                          │
│   if is_guest:                                          │
│     check: guest_invoice_count >= 1                     │
│   else:                                                 │
│     plan_limit = subscription.plan_limit                │
│     used_count = invoice_count_this_month               │
│     check: used_count >= plan_limit                     │
└─────────────────────────────────────────────────────────┘
```

---

## Machine Learning Fraud Detection

### Anomaly Detection Algorithm

```python
# Scikit-learn Isolation Forest Approach

from sklearn.ensemble import IsolationForest

# Training Data Features:
features = [
  'amount',           # Deviation from vendor average
  'frequency_days',   # Days since last invoice from vendor
  'bank_account',     # Numeric token of account (0=new, 1=known)
  'invoice_date_gap', # Days between consecutive invoices
  'amount_variance',  # Z-score of amount vs vendor avg
  'text_confidence'   # OCR extraction confidence
]

# Example Training Flow:
1. Load historical invoices (verified non-fraudulent)
2. Calculate feature matrix:
   - amount_std = stdev(vendor_invoices.amount)
   - z_score = (current_amount - mean) / amount_std
   - frequency = days_since_last_invoice
   - bank_match = 1 if account in known_accounts else 0

3. Fit Isolation Forest:
   model = IsolationForest(
     contamination=0.1,  # Assume 10% anomalies
     n_estimators=100,
     random_state=42
   )
   model.fit(feature_matrix)

4. Predict Anomaly Score:
   anomaly_score = model.decision_function(new_invoice_features)
   # Range: -1 (normal) to +1 (anomaly)
   # Normalize to 0-100 scale

5. Risk Level Classification:
   if anomaly_score < -0.5:
     risk_level = "low"
   elif anomaly_score < 0.2:
     risk_level = "medium"
   else:
     risk_level = "high"
```

### Rule-Based Checks

```python
def perform_rule_based_fraud_check(invoice):
    """
    Rule-based checks that run BEFORE ML scoring
    """
    flags = []
    
    # Rule 1: Duplicate Detection
    if Invoice.objects.filter(
        vendor_name=invoice.vendor_name,
        invoice_number=invoice.invoice_number,
        amount=invoice.amount
    ).exists():
        flags.append({
            "rule": "duplicate",
            "severity": "high",
            "message": "Duplicate invoice detected"
        })
    
    # Rule 2: Amount Validation
    vendor_history = VendorHistory.objects.get(vendor_name)
    amount_deviation = abs(
        (invoice.amount - vendor_history.average_amount) / 
        vendor_history.average_amount * 100
    )
    if amount_deviation > 30:
        flags.append({
            "rule": "amount_deviation",
            "severity": "medium" if amount_deviation < 50 else "high",
            "message": f"Amount {amount_deviation:.1f}% above vendor average"
        })
    
    # Rule 3: Bank Account Change
    if invoice.bank_account not in vendor_history.common_bank_accounts:
        flags.append({
            "rule": "new_bank_account",
            "severity": "high",
            "message": "New bank account detected"
        })
    
    # Rule 4: Frequency Anomaly
    if vendor_history.invoice_frequency_days:
        days_since_last = (now() - vendor_history.last_processed_date).days
        expected_days = vendor_history.invoice_frequency_days
        if days_since_last < expected_days * 0.5:
            flags.append({
                "rule": "unusual_frequency",
                "severity": "low",
                "message": f"Invoice submitted {days_since_last} days after last"
            })
    
    return flags
```

---

## Blockchain Smart Contract Architecture

### Solidity Contract Structure

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

contract Invoice {
    // Invoice record structure
    struct InvoiceRecord {
        bytes32 invoiceHash;           // Keccak-256 hash of invoice data
        address submittedBy;           // User's wallet address
        uint256 timestamp;             // Block timestamp of recording
        string riskLevel;              // "low", "medium", "high"
        bool isFraudulent;             // Fraud determination
        bytes32 analysisHash;          // Hash of fraud analysis
        uint256 gasUsed;               // Gas consumed for saving
        string metadata;               // Additional JSON metadata
    }
    
    // Contract owner (admin)
    address public owner;
    
    // Main storage: invoiceHash => InvoiceRecord
    mapping(bytes32 => InvoiceRecord) public invoices;
    
    // Index for querying: user => [invoiceHashes]
    mapping(address => bytes32[]) public userInvoices;
    
    // Events for off-chain indexing
    event InvoiceRecorded(
        bytes32 indexed invoiceHash,
        address indexed submittedBy,
        string riskLevel,
        uint256 timestamp
    );
    
    event InvoiceFraudMarked(
        bytes32 indexed invoiceHash,
        bool isFraudulent,
        uint256 timestamp
    );
    
    // Constructor - sets contract owner
    constructor() {
        owner = msg.sender;
    }
    
    // Record invoice hash on blockchain
    function recordInvoice(
        bytes32 _invoiceHash,
        string memory _riskLevel,
        bytes32 _analysisHash
    ) public {
        // Validation
        require(_invoiceHash != 0, "Invalid invoice hash");
        require(bytes(_riskLevel).length > 0, "Risk level required");
        
        // Create record
        InvoiceRecord memory record = InvoiceRecord({
            invoiceHash: _invoiceHash,
            submittedBy: msg.sender,
            timestamp: block.timestamp,
            riskLevel: _riskLevel,
            isFraudulent: false,
            analysisHash: _analysisHash,
            gasUsed: gasleft(),
            metadata: ""
        });
        
        // Store in mapping
        invoices[_invoiceHash] = record;
        userInvoices[msg.sender].push(_invoiceHash);
        
        // Emit event for indexing
        emit InvoiceRecorded(
            _invoiceHash,
            msg.sender,
            _riskLevel,
            block.timestamp
        );
    }
    
    // Retrieve invoice record
    function getInvoice(bytes32 _invoiceHash)
        public
        view
        returns (InvoiceRecord memory)
    {
        return invoices[_invoiceHash];
    }
    
    // Mark invoice as fraudulent (owner only)
    function markAsFraudulent(bytes32 _invoiceHash) public onlyOwner {
        require(invoices[_invoiceHash].submittedBy != address(0), "Invoice not found");
        invoices[_invoiceHash].isFraudulent = true;
        emit InvoiceFraudMarked(_invoiceHash, true, block.timestamp);
    }
    
    // Verify invoice authenticity
    function verifyInvoice(bytes32 _invoiceHash) public view returns (bool) {
        InvoiceRecord memory record = invoices[_invoiceHash];
        return record.submittedBy != address(0) && !record.isFraudulent;
    }
    
    // Get user's invoice count
    function getUserInvoiceCount(address _user) public view returns (uint256) {
        return userInvoices[_user].length;
    }
    
    // Modifier: only owner
    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can call this");
        _;
    }
}
```

### Transaction Flow

```
Django Backend
    │
    ├─> Generate Invoice Hash
    │   keccak256(abi.encodePacked(
    │     vendor_name, amount, invoice_date, bank_account
    │   ))
    │
    ├─> Build Transaction
    │   {
    │     to: CONTRACT_ADDRESS,
    │     data: recordInvoice(hash, "low", analysisHash),
    │     value: 0,
    │     gas: 500000,
    │     gasPrice: 2.5 Gwei (Sepolia avg)
    │   }
    │
    ├─> Sign Transaction
    │   Using private key: BLOCKCHAIN_SIGNER_PRIVATE_KEY
    │   (EIP-191 personal_sign)
    │
    ├─> Submit to RPC
    │   POST https://eth-sepolia.g.alchemy.com/v2/API_KEY
    │   Method: eth_sendRawTransaction
    │
    ├─> Monitor Confirmation
    │   Poll eth_getTransactionReceipt()
    │   Wait for status = 1 (success)
    │
    └─> Store on Database
        UPDATE invoices
        SET blockchain_tx_hash = '0x...',
            blockchain_block = 4234567,
            blockchain_timestamp = 1234567890
```

---

## Security Implementation Details

### Password Security

```python
# Django's default password hasher uses PBKDF2 with SHA256
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',  # Default
    'django.contrib.auth.hashers.Argon2PasswordHasher',  # Strong (optional)
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',  # Fallback
]

# Usage:
from django.contrib.auth.hashers import make_password
hashed = make_password("user_password")  # Auto-salted & hashed
```

### HTTPS/TLS Configuration

```nginx
# Nginx reverse proxy configuration
server {
    listen 443 ssl http2;
    server_name invyra.example.com;
    
    # SSL certificate (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/invyra.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/invyra.example.com/privkey.pem;
    
    # Strong TLS settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Content-Security-Policy "default-src 'self'" always;
}
```

### Payment Data Security

```python
# Stripe Integration - No Card Data Storage
# Stripe handles all PCI compliance

from stripe import Charge, Customer

# Create subscription
stripe_customer = stripe.Customer.create(
    email=user.email,
    payment_method=payment_method_id  # Stripe token, not actual card
)

stripe_subscription = stripe.Subscription.create(
    customer=stripe_customer.id,
    items=[{"price": plan.stripe_price_id}]
)

# Keys stored in environment variables
STRIPE_PUBLIC_KEY = os.getenv('STRIPE_PUBLIC_KEY')  # Safe to expose
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')  # Keep secret
```

### Encrypted Sensitive Fields

```python
# Bank account field encryption
from django.contrib.postgres.fields import EncryptedTextField

class Invoice(models.Model):
    bank_account = EncryptedTextField()  # Encrypted at DB level
    
# Usage:
invoice.bank_account = "1234567890"  # Stored encrypted
# Decryption happens automatically on retrieval
plaintext = invoice.bank_account  # Auto-decrypted
```

---

## Performance Optimization

### Database Query Optimization

```python
# BAD: N+1 queries
invoices = Invoice.objects.all()
for invoice in invoices:
    print(invoice.user.email)  # Query per invoice!

# GOOD: Single query with select_related
invoices = Invoice.objects.select_related('user').all()
# Now user data is pre-loaded, no extra queries
```

### Caching Strategy

```python
from django.views.decorators.cache import cache_page
from django.core.cache import cache

# Cache view for 5 minutes
@cache_page(60 * 5)
def analytics_view(request):
    stats = calculate_expensive_analytics()
    return render(request, 'analytics.html', stats)

# Manual cache
def get_vendor_history(vendor_name):
    cache_key = f"vendor_history:{vendor_name}"
    cached = cache.get(cache_key)
    
    if cached:
        return cached
    
    vendor_history = VendorHistory.objects.get(vendor_name=vendor_name)
    cache.set(cache_key, vendor_history, 60 * 60)  # 1 hour
    return vendor_history
```

### OCR Processing Optimization

```python
# Parallel processing for batch uploads
from multiprocessing import Pool

def process_invoice_batch(invoice_files):
    """Process multiple invoices in parallel"""
    with Pool(processes=4) as pool:
        results = pool.map(extract_invoice_text, invoice_files)
    return results

# Async task processing (Celery)
@shared_task
def extract_and_analyze_invoice(invoice_id):
    """Background task - doesn't block user"""
    invoice = Invoice.objects.get(id=invoice_id)
    invoice.status = 'processing'
    invoice.save()
    
    # Long-running tasks
    extracted = extract_text_with_ocr(invoice.file)
    fraud_score = analyze_fraud_risk(extracted)
    
    # Update when done
    invoice.extraction = extracted
    invoice.fraud_score = fraud_score
    invoice.status = 'verified'
    invoice.save()
```

---

## Monitoring & Observability

### Logging Strategy

```python
import logging

logger = logging.getLogger(__name__)

# Levels: DEBUG < INFO < WARNING < ERROR < CRITICAL
logger.info(f"Invoice uploaded: {invoice_id}")
logger.warning(f"Payment failed: {error_message}")
logger.error(f"Blockchain transaction failed: {tx_hash}", exc_info=True)
logger.critical(f"Database connection lost")
```

### Application Metrics

```python
# Key metrics to monitor
metrics = {
    "invoices_processed_daily": 156,
    "avg_processing_time_seconds": 1.8,
    "fraud_detection_accuracy": 0.947,
    "blockchain_confirmation_time": 18,
    "api_response_time_p95": 245,  # milliseconds
    "server_uptime_percentage": 99.92,
    "database_query_time_avg": 12,  # milliseconds
    "ocr_extraction_accuracy": 0.942,
}
```

---

**Last Updated**: March 6, 2026
**Version**: 1.0.0
