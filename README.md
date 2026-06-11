# Collatz Telegram Bot - Fixed Version

This version keeps the app as a Python Telegram bot and adds:

- Telegram connection diagnostics
- optional proxy support
- clearer error messages
- retry support during startup

## 1. Install dependencies

```powershell
python -m pip install --upgrade pip certifi
python -m pip install -r requirements.txt
```

## 2. Set your Telegram bot token

```powershell
$env:TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN_HERE"
```

## 3. Run the bot

```powershell
python bot.py
```

Then open your Telegram bot and send:

```text
27
```

or:

```text
/collatz 27
```

## If your network blocks Telegram

Your earlier error:

```text
certificate verify failed: Hostname mismatch, certificate is not valid for 'api.telegram.org' 8889783978:AAGd8-anLZsug69V27al3gzQfEwohSfSVok
```

means Python is not seeing Telegram's real certificate.

Try a mobile hotspot first. If that works, your normal network/VPN/proxy/antivirus is intercepting Telegram.

## Optional proxy setup

If you have an HTTP proxy:

```powershell
$env:TELEGRAM_PROXY="http://127.0.0.1:7890"
python bot.py
```

If you have a SOCKS5 proxy:

```powershell
python -m pip install "python-telegram-bot[socks]"
$env:TELEGRAM_PROXY="socks5://127.0.0.1:1080"
python bot.py
```