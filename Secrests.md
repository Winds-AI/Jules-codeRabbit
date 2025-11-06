**Proposed plan: end-to-end encrypted per-request Jules key**

1. **Publish a public key** (RSA/ECDSA) on your service’s `/github/setup` page. Users download this once.
2. **Client-side encryption helper** (CLI snippet or small JS widget) encrypts the user’s Jules API key with that public key. Only the ciphertext travels to your server.
3. **Request format**  
   - Webhook or review trigger includes a header like `X-Jules-Key: <base64 ciphertext>` plus a short-lived nonce/timestamp.  
   - Body still carries the GitHub payload.
4. **Server handling**  
   - Decrypt ciphertext using your private key just before calling Jules.  
   - Reject replays by checking timestamp + nonce (store last few in memory or a bounded cache).  
   - Immediately discard the plaintext key after the outbound Jules request; do not log headers/body.
5. **Operational safety**  
   - Rotate the keypair periodically and publish the new public key.  
   - Monitor for decryption failures/replay attempts.  
   - Document the contract so users understand nothing is persisted.

**Other approaches (trade-offs)**  
1. **Plain per-request header over HTTPS** – simplest (no crypto baggage) but your server sees the raw key.  
2. **GitHub App secrets per-installation** – users manage a secret in their GitHub App; your webhook fetches it through GitHub’s API. Requires storing an installation token and still briefly exposes the secret server-side.  
3. **Signed JWT wrapper** – users sign a JWT embedding their key; server verifies signature and decrypts. More complex than RSA-only approach but allows expiration, audience checks, etc.