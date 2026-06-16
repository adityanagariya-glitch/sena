#!/usr/bin/env python3
"""Test RSA-SHA256 signing with real key from config."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "services" / "ai_chatbot"))

import services.ai_chatbot.config as config
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
import base64
import time

print("\n" + "="*60)
print("RSA-SHA256 PUBLIC/PRIVATE KEY HANDSHAKE TEST")
print("="*60)

# Step 1: Load Private Key from Config (from .env)
print("\n1️⃣  LOAD PRIVATE KEY FROM CONFIG")
print("-" * 60)

if not config.AI_WEBHOOK_PRIVATE_KEY_PEM:
    print("⚠️  AI_WEBHOOK_PRIVATE_KEY_PEM is not set in .env")
    print("   Generating test key instead...")

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Save it to show what to put in .env
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )

    print("❌ To test with real key, add this to .env:")
    print("\nAI_WEBHOOK_PRIVATE_KEY_PEM=" + private_pem.decode()[:50] + "...")

else:
    print("✅ Loading private key from config (AI_WEBHOOK_PRIVATE_KEY_PEM)")
    try:
        private_key = serialization.load_pem_private_key(
            config.AI_WEBHOOK_PRIVATE_KEY_PEM.encode(),
            password=None,
        )
        print("✅ Private key loaded successfully!")
    except Exception as e:
        print(f"❌ Failed to load private key: {e}")
        sys.exit(1)

public_key = private_key.public_key()

# Get the keys in PEM format
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)
public_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)

print(f"✅ Key pair ready")
print(f"   Private key: {len(private_pem)} bytes")
print(f"   Public key: {len(public_pem)} bytes")

# Step 2: Message to Sign
print("\n2️⃣  CREATE MESSAGE TO SIGN")
print("-" * 60)

timestamp = str(int(time.time()))
body = b'{"conversationId": "conv-123", "message": "What are my shifts?"}'

message_to_sign = f"{timestamp}.".encode() + body

print(f"   Timestamp: {timestamp}")
print(f"   Body: {body.decode()}")
print(f"   Full message: {timestamp}.<json>")
print(f"   Total bytes to sign: {len(message_to_sign)}")

# Step 3: Sign the Message (SENDER does this with PRIVATE KEY)
print("\n3️⃣  SIGN MESSAGE WITH PRIVATE KEY")
print("-" * 60)

signature = private_key.sign(
    message_to_sign,
    padding.PKCS1v15(),
    hashes.SHA256()
)

signature_b64 = base64.b64encode(signature).decode()

print(f"✅ Signature created!")
print(f"   Raw bytes: {len(signature)}")
print(f"   Base64: {signature_b64[:50]}...")

# Step 4: Send Over Network
print("\n4️⃣  SEND OVER NETWORK")
print("-" * 60)

request_headers = {
    "X-AI-Timestamp": timestamp,
    "X-AI-Signature": signature_b64,
    "Content-Type": "application/json"
}

print("✅ Sender would send:")
for k, v in request_headers.items():
    if len(v) > 50:
        print(f"   {k}: {v[:50]}...")
    else:
        print(f"   {k}: {v}")

# Step 5: Receiver Verifies (RECEIVER uses PUBLIC KEY)
print("\n5️⃣  RECEIVER VERIFIES SIGNATURE")
print("-" * 60)

# Receiver has:
# - The body (from request)
# - The timestamp (from header)
# - The signature (from header)
# - The public key (from config/store)

try:
    # Reconstruct the exact message that was signed
    received_timestamp = request_headers["X-AI-Timestamp"]
    received_signature_b64 = request_headers["X-AI-Signature"]
    received_body = body

    # Rebuild the message
    received_message = f"{received_timestamp}.".encode() + received_body

    # Decode signature from base64
    received_signature = base64.b64decode(received_signature_b64)

    # Verify using PUBLIC KEY
    public_key.verify(
        received_signature,
        received_message,
        padding.PKCS1v15(),
        hashes.SHA256()
    )

    print("✅ SIGNATURE VERIFIED!")
    print(f"   Timestamp matches: {received_timestamp} == {timestamp}")
    print(f"   Body matches: {len(received_body)} bytes")
    print(f"   Signature is authentic (signed with private key)")

except Exception as e:
    print(f"❌ SIGNATURE VERIFICATION FAILED: {e}")
    sys.exit(1)

# Step 6: What if someone tries to cheat?
print("\n6️⃣  TEST: WHAT IF MESSAGE WAS TAMPERED?")
print("-" * 60)

tampered_body = b'{"conversationId": "conv-123", "message": "Hack attempt!"}'
tampered_message = f"{timestamp}.".encode() + tampered_body

try:
    public_key.verify(
        signature,  # Original signature (signed different message)
        tampered_message,  # Different message
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    print("❌ SECURITY ISSUE: Tampered message verified!")
    sys.exit(1)
except Exception as e:
    print(f"✅ TAMPERED MESSAGE REJECTED!")
    print(f"   Error: {str(e)[:60]}...")
    print(f"   (Signature doesn't match tampered content)")

# Step 7: What if timestamp expired?
print("\n7️⃣  TEST: WHAT IF TIMESTAMP IS OLD?")
print("-" * 60)

old_timestamp = str(int(time.time()) - 400)  # 6+ minutes old
print(f"   Current time: {timestamp}")
print(f"   Message time: {old_timestamp}")
print(f"   Difference: {int(timestamp) - int(old_timestamp)} seconds")

# This would be checked by receiver
max_age = 300  # 5 minutes
age = int(timestamp) - int(old_timestamp)

if age > max_age:
    print(f"✅ EXPIRED: Message is {age} seconds old (max {max_age})")
    print(f"   (Would be rejected by server)")
else:
    print(f"✅ VALID: Message is {age} seconds old")

