# Builder Account Generator

A Flask-based web application that automates the creation of [Builder.io](https://www.builder.io/) accounts using temporary email addresses and Firebase authentication. The tool handles the entire sign-up flow, including email verification, and saves the generated credentials locally.

> **Disclaimer:** This tool is for educational purposes only. Use it responsibly and in compliance with Builder.io’s Terms of Service. Do not use it for spam or any malicious activity.

---

## Features

- **Bulk account creation** – Generate 1–50 accounts in a single run.
- **Temporary email** – Uses [Mail.tm](https://mail.tm/) for disposable email addresses.
- **Full automation** – Handles Firebase sign‑up, email verification (via OOB code), and Builder.io organization creation.
- **Live progress streaming** – Real‑time logs and progress bar via Server‑Sent Events (SSE).
- **Account management** – View, copy, export to CSV, and clear the account list.
- **Responsive UI** – Works on desktop and mobile with a dark/light theme.

---

## Prerequisites

- Python 3.8+
- `pip` (Python package manager)

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/builder-account-generator.git
   cd builder-account-generator
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

   If `requirements.txt` is not provided, install manually:
   ```bash
   pip install flask requests
   ```

3. **Run the application:**
   ```bash
   python app.py
   ```

4. Open your browser at `http://localhost:5000`.

---

## Usage

1. **Set the number of accounts** (1–50) in the input field.
2. Optionally specify an **email prefix** and a **custom password** (leave blank for auto‑generation).
3. Click **Launch** to start the process.
4. Watch the live logs and progress bar.
5. Once finished, the new accounts appear in the middle panel.
6. Use the buttons below the form to:
   - **Show** – refresh the account list from `accounts.txt`.
   - **CSV** – export all accounts to a CSV file.
   - **Copy** – copy all credentials to the clipboard.
   - **Clear** – clear the displayed list (does not delete the file).

### Keyboard Shortcuts

- `Ctrl+Enter` (or `Cmd+Enter`) – launch the creation process.
- `Ctrl+L` (or `Cmd+L`) – scroll logs to the bottom.
- `Esc` – cancel an ongoing creation.

---

## How It Works

1. **Temporary Email Creation** – A Mail.tm account is created with a random or user‑supplied prefix.
2. **Firebase Sign‑up** – The email/password is registered with Firebase using the public API key.
3. **Verification Email** – Firebase sends a verification email to the temporary address.
4. **Waiting & OOB Code Extraction** – The app polls Mail.tm for an email from `help@builder.io` with a verification link. The link contains an `oobCode` and `apiKey`.
5. **Email Verification** – The `oobCode` is sent to Firebase’s `setAccountInfo` endpoint to mark the email as verified.
6. **Builder.io Organization Creation** – A request is made to `cdn.builder.io/api/v1/signup` with a generated organization payload, using the Firebase ID token.
7. **Account Storage** – The email and password are appended to `accounts.txt`.

---

## Configuration

All configuration is inside `app.py`. You can adjust the following constants:

- `FIREBASE_API_KEY` – Firebase Web API key (public, used for sign‑up and verification).
- `SIGNUP_URL` – Builder.io sign‑up endpoint.
- `MAILTM_BASE` – Mail.tm API base URL.
- `HEADERS` – HTTP headers used for Builder API calls.
- `SIGNUP_TEMPLATE` – JSON template for the Builder sign‑up payload.

> **Note:** The Firebase API key is hardcoded and is intended for demonstration. In a production environment, you should keep secrets in environment variables or a config file.

---

## File Structure

```
.
├── app.py               # Main Flask application
├── templates/
│   └── index.html       # Frontend UI (embedded HTML/CSS/JS)
├── accounts.txt         # Generated accounts (email,password) – created on first save
└── README.md            # This file
```

---

## Dependencies

- [Flask](https://flask.palletsprojects.com/) – web framework.
- [Requests](https://requests.readthedocs.io/) – HTTP client.
- (Frontend: Bootstrap 5, Font Awesome, Google Fonts)

---

## Limitations & Important Notes

- **Temporary emails** – Mail.tm addresses are disposable; they expire after a while and may not receive all emails reliably.
- **Rate limits** – Mail.tm and Firebase may throttle requests. The code includes retries with exponential backoff.
- **Builder.io anti‑abuse** – The tool uses realistic headers and payloads to mimic a legitimate browser, but heavy usage may trigger rate limiting or CAPTCHAs.
- **Security** – The Firebase API key is public and should only be used for client‑side operations (it is intentionally exposed in client‑side code). Do not store sensitive data in the code.
- **Account storage** – `accounts.txt` is stored in plain text. Keep it secure if you use this tool.

---

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for improvements or bug fixes.

---

## License

This project is provided **as‑is** without any warranty. You are free to use and modify it for personal and educational purposes. No official license is attached; consider it public domain / MIT style unless you choose otherwise.

---

## Contact / Support

For questions or suggestions, please open an issue in the repository.
