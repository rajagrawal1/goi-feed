# goi-feed

A scheduled GitHub Action republishes official Government of India (PIB) press
releases relevant to **GST** and **Income Tax** as `announcements.json`, integrity-
verified with an Ed25519 signature (`announcements.json.sig`).

- **Sources:** official PIB (`pib.gov.in`). No third-party content.
- **Verification:** Ed25519 detached signature; public key is `ed25519_pub.pem`.
- **No server** — runs on a schedule via GitHub Actions.

## License
Pipeline code is MIT. Announcement content is public government record, reproduced
from official PIB sources with attribution.
