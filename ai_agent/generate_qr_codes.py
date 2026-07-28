"""
Generates one QR code per Nefashot sign-up link — for printing on
flyers/posters at events, or on-screen next to the agent's recommendation.

Update LINKS with real per-activity URLs once Nefashot provides them.
"""

import qrcode
import os

OUT_DIR = "/mnt/user-data/outputs/qr_codes"
os.makedirs(OUT_DIR, exist_ok=True)

# Real, currently-working Nefashot links (verified on nefashot.com today).
# Swap/add real per-activity signup links here once they exist.
LINKS = {
    "nefashot_linktree": "https://linktr.ee/nefashot",
    "nefashot_community_whatsapp": "https://chat.whatsapp.com/IJYqIdd5Y9q2YFnNYCXUT6",
    "nefashot_contact_page": "https://www.nefashot.com/en/contactus",
}

for name, url in LINKS.items():
    qr = qrcode.QRCode(
        version=None,          # auto-size to fit the URL
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    path = os.path.join(OUT_DIR, f"{name}.png")
    img.save(path)
    print(f"Saved {path}  ->  {url}")
