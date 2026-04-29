




#!/usr/bin/env python3
"""
TS24 Dashboard — Password Generator
Run directly: python3 password_generator.py
"""
import secrets
import string
import hashlib
import subprocess

# ── ANSI colors ──────────────────────────────────────────────
BLUE   = "\033[94m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
DIM    = "\033[2m"

def sha256(pwd):
    return hashlib.sha256(pwd.strip().encode()).hexdigest()

def banner():
    print()
    print(f"{BLUE}{BOLD}{'='*52}{RESET}")
    print(f"{BLUE}{BOLD}   🔑  TS24 Dashboard — Password Generator{RESET}")
    print(f"{BLUE}{BOLD}{'='*52}{RESET}")
    print()

def generate_password(length=14, use_symbols=True):
    """Generate a cryptographically secure password."""
    lower   = string.ascii_lowercase
    upper   = string.ascii_uppercase
    digits  = string.digits
    symbols = "!@#$%^&*-_=+"

    pool = lower + upper + digits
    required = [
        secrets.choice(lower),
        secrets.choice(upper),
        secrets.choice(digits),
    ]
    if use_symbols:
        pool += symbols
        required.append(secrets.choice(symbols))

    remaining = length - len(required)
    rest = [secrets.choice(pool) for _ in range(remaining)]

    combined = required + rest
    secrets.SystemRandom().shuffle(combined)
    return "".join(combined)

def strength_label(pwd):
    score = 0
    if any(c.islower() for c in pwd):          score += 1
    if any(c.isupper() for c in pwd):          score += 1
    if any(c.isdigit() for c in pwd):          score += 1
    if any(c in "!@#$%^&*-_=+" for c in pwd): score += 1
    if len(pwd) >= 12:                         score += 1
    if len(pwd) >= 16:                         score += 1
    if score <= 2: return f"{RED}Weak{RESET}"
    if score <= 3: return f"{YELLOW}Fair{RESET}"
    if score <= 4: return f"{CYAN}Good{RESET}"
    return f"{GREEN}{BOLD}Strong{RESET}"

def ask(prompt, default=None, choices=None):
    hint = f" {CYAN}{BOLD}[{default}]{RESET}" if default is not None else ""
    if choices:
        hint += f" {DIM}({'/'.join(choices)}){RESET}"
    while True:
        try:
            val = input(f"{YELLOW}{BOLD}{prompt}{RESET}{hint}{YELLOW} → {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if not val and default is not None:
            return default
        if choices and val.lower() not in [c.lower() for c in choices]:
            print(f"  {RED}Please enter: {', '.join(choices)}{RESET}")
            continue
        return val

def copy_to_clipboard(text):
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        return True
    except Exception:
        return False

# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    banner()
    print(f"{DIM}Generates secure passwords for TS24 Dashboard users.{RESET}")
    print()

    while True:
        # ── Settings ──────────────────────────────────────────
        print(f"{BLUE}{BOLD}┌─ Settings ──────────────────────────────────────┐{RESET}")
        print(f"{DIM}  Enter a value, or press Enter to use the default {CYAN}[shown in cyan]{RESET}")
        print(f"{BLUE}{BOLD}└─────────────────────────────────────────────────┘{RESET}")

        len_str = ask("Password length", default="14")
        try:
            pwd_len = max(8, min(32, int(len_str)))
        except ValueError:
            pwd_len = 14

        sym_str = ask("Include symbols  (!@#$...)", default="y", choices=["y", "n"])
        use_sym = sym_str.lower() == "y"

        count_str = ask("How many options to generate", default="5")
        try:
            count = max(1, min(10, int(count_str)))
        except ValueError:
            count = 5

        # ── Generate ──────────────────────────────────────────
        print()
        print(f"{BOLD}── Generated Passwords ───────────────────────────{RESET}")
        passwords = [generate_password(pwd_len, use_sym) for _ in range(count)]

        for i, pwd in enumerate(passwords, 1):
            print(f"  {CYAN}{BOLD}[{i}]{RESET}  {GREEN}{BOLD}{pwd}{RESET}"
                  f"   {DIM}Strength:{RESET} {strength_label(pwd)}")
        print()

        # ── Select ────────────────────────────────────────────
        choice_str = ask(
            f"Choose [1-{count}], or press Enter to re-generate",
            default="0"
        )
        try:
            choice = int(choice_str)
        except ValueError:
            choice = 0

        if 1 <= choice <= count:
            selected = passwords[choice - 1]

            print()
            print(f"{BOLD}{'='*52}{RESET}")
            print(f"{BOLD}  ✅  Selected Password{RESET}")
            print(f"{BOLD}{'='*52}{RESET}")
            print()
            print(f"  {BOLD}Password :{RESET}  {GREEN}{BOLD}{selected}{RESET}")
            print(f"  {BOLD}Length   :{RESET}  {len(selected)} characters")
            print(f"  {BOLD}Strength :{RESET}  {strength_label(selected)}")
            print()
            print(f"  {DIM}SHA-256 hash (stored internally in config):{RESET}")
            print(f"  {DIM}{sha256(selected)}{RESET}")
            print()

            if copy_to_clipboard(selected):
                print(f"  {GREEN}📋 Password copied to clipboard!{RESET}")
            print()
            print(f"{BLUE}{'─'*52}{RESET}")
            print(f"  {YELLOW}⚠  Share only the PASSWORD with the user,{RESET}")
            print(f"  {YELLOW}   not the hash.{RESET}")
            print(f"{BLUE}{'─'*52}{RESET}")
            print()

            again = ask("Generate another password?", default="n", choices=["y", "n"])
            if again.lower() != "y":
                break
            print()
        else:
            print(f"  {DIM}Re-generating...{RESET}")
            print()

    print()
    print(f"{GREEN}{BOLD}Done!{RESET}")
    print()
    input("Press Enter to close... ")

