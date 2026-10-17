# Security notes

Last reviewed: 2026-10-08

- **Contents are encrypted with AES-256** (WinZip AE-2), with an HMAC that
  detects tampering. zipseal never uses the broken legacy ZipCrypto scheme.
- **Names are not hidden by default.** A normal zip stores file names, sizes
  and dates in plain text. Anyone can list them without the password. Use
  `--hide-names` if names are sensitive. Even then, an observer sees each
  part's total size, the number of parts, and each part file's own date.
- **The password is the weak point.** AE-2 derives its key with
  PBKDF2-HMAC-SHA1 at only 1,000 iterations. The format fixes that number, so
  it cannot be raised without producing archives other tools cannot open.
  What this means in practice: a password with enough entropy in it stays safe
  even at 1,000 iterations, while a short or guessable one does not. See
  [Choosing a password](#choosing-a-password) below.
- **Send the password separately.** Use a different channel from the one
  carrying the zip.
- **All parts share one password.** That is fine with AES-256.
- **Prefer the prompt or a password file on shared machines.**
  `--password-env` keeps the password off the command line, but other
  processes run by the same user can read a process's environment. Keep
  password files at mode `600`.
- **Output files are created with mode `600`.** Only you can read them until
  you share them.
- **No plaintext is written to disk.** That includes temporary files and the
  `--hide-names` inner zip, which is streamed straight into the encrypted
  outer entry.
- **Memory is not wiped.** Python cannot reliably erase the password from
  memory, so it lives for the length of the run.

## Choosing a password

Use `--generate-password` whenever you can. It prints the password once and
then leaves you to deliver it, which is the safest option available.

Some archives need a password you choose: one your team already uses, one a
partner will receive, or one you must be able to retype. In that case aim for
**at least 16 characters drawn at random**, or **five or more unrelated
words**. Both sit far beyond offline guessing at 1,000 iterations. Four words
from a large word list is also workable; a single word is not.

To put those numbers in perspective, `--generate-password` produces 24
characters from a 62-symbol alphabet, about 143 bits, while 16 random
characters is about 95 bits and five words from a 7,776-word list is about 65.
Length does most of the work. Avoid passwords built from one word plus
punctuation, names, dates, or anything a person who knows you could guess,
since those fall in the range a cracking tool tries first.

zipseal warns when a password is shorter than 12 characters or contains
non-ASCII characters, but it accepts them: a warning is advice, not a block.
Nothing checks how guessable a password is, so that judgement stays with you.
