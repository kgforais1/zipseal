# Security notes

Last reviewed: 2026-10-08

- **Contents are encrypted with AES-256** (WinZip AE-2), with an HMAC that
  detects tampering. zipseal never uses the broken legacy ZipCrypto scheme.
- **Names are not hidden by default.** A normal zip stores file names, sizes
  and dates in plain text. Anyone can list them without the password. Use
  `--hide-names` if names are sensitive. Even then, an observer sees each
  part's total size, the number of parts, and each part file's own date.
- **The password is the weak point.** AE-2 derives its key with
  PBKDF2-HMAC-SHA1 at only 1,000 iterations, so a short or guessable password
  can be cracked offline quickly. Prefer `--generate-password`.
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
